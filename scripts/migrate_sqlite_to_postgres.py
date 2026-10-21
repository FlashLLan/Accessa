"""One-off copy of the legacy SQLite database (accessa.db) into PostgreSQL.

    python scripts/migrate_sqlite_to_postgres.py [--sqlite PATH]

Prerequisites: PostgreSQL is running and `alembic upgrade head` has been applied.
Connects with MIGRATION_DATABASE_URL (the schema-owner role): restoring rows with
their original ids and resetting sequences is a migration task, not something the
application role should be able to do.

What it does, in a single transaction:
- creates one workspace: name "Default workspace", slug "default";
- assigns every user, change request and audit log to it;
- copies roles and the child tables unchanged, preserving primary keys;
- converts naive SQLite timestamps (UTC by convention) to timezone-aware UTC;
- applies the later schema rules: merge_request_url is merged into
  pull_request_url, NULL users.is_active/created_at/updated_at are backfilled,
  and a set current_reviewer_id becomes the assigned reviewer;
- resets every PostgreSQL sequence to MAX(id);
- prints row counts per table for both databases.

Refuses to run if the target already contains data. Seed scripts must therefore
run *after* this script (they skip anything that already exists).

--skip-audit-logs leaves out the legacy audit rows, which store names/e-mails
and pre-workspace action codes, so the restored database starts with a clean,
empty audit log.
"""
import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import os  # noqa: E402

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import Boolean, DateTime, create_engine, func, insert, inspect, select, text, update  # noqa: E402

import backend.models  # noqa: E402,F401 — registers every model on Base.metadata
from database.base import Base  # noqa: E402

DEFAULT_WORKSPACE_NAME = "Default workspace"
DEFAULT_WORKSPACE_SLUG = "default"

# Parents before children, so every foreign key target exists when a row is inserted.
TABLE_ORDER = [
    "roles",
    "users",
    "change_requests",
    "comments",
    "approvals",
    "git_context",
    "ai_review_results",
    "review_actions",
    "audit_logs",
]
TENANT_TABLES = {"users", "change_requests", "audit_logs"}


def to_utc(value):
    if value is None or isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value))
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def convert_row(row: dict, table) -> dict:
    out = {}
    for name, value in row.items():
        col_type = table.c[name].type
        if isinstance(col_type, DateTime):
            value = to_utc(value)
        elif isinstance(col_type, Boolean) and value is not None:
            value = bool(value)
        out[name] = value
    return out


def adapt_legacy_row(name: str, raw: dict) -> dict:
    """Apply the same data rules as the Alembic migrations to legacy SQLite rows."""
    row = dict(raw)
    if name == "change_requests":
        # current_reviewer_id was removed (revision after c5ee582f5a9e): the reviewer
        # who held the request after a transfer becomes its assigned reviewer.
        current = row.pop("current_reviewer_id", None)
        if current is not None:
            row["assigned_reviewer_id"] = current
    if name == "git_context":
        # merge_request_url was merged into pull_request_url (revision c5ee582f5a9e).
        merge_url = row.pop("merge_request_url", None)
        if merge_url and row.get("pull_request_url") and merge_url != row["pull_request_url"]:
            fail(f"git_context id={row['id']} has different pull and merge request URLs; resolve it first.")
        row["pull_request_url"] = row.get("pull_request_url") or merge_url
    if name == "users":
        # is_active / created_at / updated_at are NOT NULL; NULL is_active was
        # treated as inactive by the application, so it stays inactive.
        if row.get("is_active") is None:
            row["is_active"] = False
        if row.get("created_at") is None:
            row["created_at"] = row.get("updated_at") or datetime.now(timezone.utc)
        if row.get("updated_at") is None:
            row["updated_at"] = row["created_at"]
    return row


def fail(message: str):
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sqlite", default=str(ROOT / "accessa.db"), help="path to the legacy SQLite file")
    parser.add_argument(
        "--skip-audit-logs",
        action="store_true",
        help="do not copy the legacy audit rows (they contain names/e-mails and legacy action codes); "
             "the audit log starts empty",
    )
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    target_url = os.getenv("MIGRATION_DATABASE_URL")
    if not target_url:
        fail("MIGRATION_DATABASE_URL is not set (see .env.example).")
    if not target_url.startswith("postgresql"):
        fail("MIGRATION_DATABASE_URL must point at PostgreSQL.")

    sqlite_path = Path(args.sqlite)
    if not sqlite_path.is_file():
        fail(f"SQLite file not found: {sqlite_path}")

    src = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    src_tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    missing = [t for t in TABLE_ORDER if t not in src_tables]
    if missing:
        fail(f"SQLite file is missing tables: {', '.join(missing)}")

    engine = create_engine(target_url)
    tables = Base.metadata.tables

    with engine.begin() as conn:
        # --- preconditions -------------------------------------------------
        existing = set(inspect(conn).get_table_names())
        if "alembic_version" not in existing or not set(tables) <= existing:
            fail("Target schema is missing. Run `alembic upgrade head` first.")

        non_empty = {
            name: conn.execute(select(func.count()).select_from(tables[name])).scalar_one()
            for name in ["workspaces", *TABLE_ORDER]
        }
        non_empty = {k: v for k, v in non_empty.items() if v}
        if non_empty:
            fail(
                "Target database already contains data, refusing to continue: "
                + ", ".join(f"{k}={v}" for k, v in non_empty.items())
            )

        print(f"Source: {sqlite_path}")
        print(f"Target: {engine.url.render_as_string(hide_password=True)}\n")

        # --- default workspace ---------------------------------------------
        workspace_id = conn.execute(
            insert(tables["workspaces"])
            .values(name=DEFAULT_WORKSPACE_NAME, slug=DEFAULT_WORKSPACE_SLUG)
            .returning(tables["workspaces"].c.id)
        ).scalar_one()
        print(f"Created workspace '{DEFAULT_WORKSPACE_NAME}' (slug '{DEFAULT_WORKSPACE_SLUG}', id {workspace_id})\n")

        # --- copy tables -----------------------------------------------------
        copied_tables = [t for t in TABLE_ORDER if not (args.skip_audit_logs and t == "audit_logs")]
        if args.skip_audit_logs:
            print("  audit_logs: skipped (--skip-audit-logs); the audit log starts empty")
        source_counts = {}
        for name in copied_tables:
            table = tables[name]
            src_rows = [adapt_legacy_row(name, dict(r)) for r in src.execute(f'SELECT * FROM "{name}" ORDER BY id')]
            source_counts[name] = len(src_rows)

            src_cols = {r[1] for r in src.execute(f'PRAGMA table_info("{name}")')}
            skipped = sorted(src_cols - set(table.c.keys()))
            if skipped:
                print(f"  {name}: ignoring legacy source column(s) {', '.join(skipped)}")

            rows = []
            for raw in src_rows:
                row = convert_row({k: v for k, v in raw.items() if k in table.c}, table)
                if name in TENANT_TABLES:
                    row["workspace_id"] = workspace_id
                rows.append(row)

            # users.created_by references users.id; insert without it first so the
            # order of rows cannot violate the self-referencing foreign key.
            created_by = {}
            if name == "users":
                for row in rows:
                    created_by[row["id"]] = row.pop("created_by", None)

            if rows:
                conn.execute(insert(table), rows)

            for user_id, creator_id in created_by.items():
                if creator_id is not None:
                    conn.execute(update(table).where(table.c.id == user_id).values(created_by=creator_id))

        # --- sequences ---------------------------------------------------------
        for name in ["workspaces", *TABLE_ORDER]:
            conn.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{name}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {name}), 1), "
                f"(SELECT MAX(id) FROM {name}) IS NOT NULL)"
            ))

        # --- verification ------------------------------------------------------
        print(f"\n{'table':<20}{'sqlite':>8}{'postgres':>10}")
        mismatch = False
        for name in copied_tables:
            target_count = conn.execute(select(func.count()).select_from(tables[name])).scalar_one()
            flag = "" if target_count == source_counts[name] else "   <-- MISMATCH"
            mismatch |= bool(flag)
            print(f"{name:<20}{source_counts[name]:>8}{target_count:>10}{flag}")
        if args.skip_audit_logs:
            audit_count = conn.execute(select(func.count()).select_from(tables["audit_logs"])).scalar_one()
            print(f"{'audit_logs':<20}{'skipped':>8}{audit_count:>10}")
        ws_count = conn.execute(select(func.count()).select_from(tables["workspaces"])).scalar_one()
        print(f"{'workspaces':<20}{'-':>8}{ws_count:>10}   (new)")

        if mismatch:
            fail("Row counts differ; transaction rolled back.")

    print("\nDone. Sequences reset to MAX(id).")


if __name__ == "__main__":
    main()
