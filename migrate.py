"""
Database migration script.
Adds new columns to existing tables and creates new tables via SQLAlchemy.
Safe to run multiple times — skips columns that already exist.

Multi-room: rows created before rooms existed (room_id IS NULL) are moved into
a single room, so the existing data keeps working as one team.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "accessa.db"
DEFAULT_ROOM_NAME = "Accessa Team"
TENANT_TABLES = ["users", "change_requests", "audit_logs"]


def get_existing_columns(cursor, table: str) -> set[str]:
    cursor.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def add_column_if_missing(cursor, table: str, column: str, definition: str):
    existing = get_existing_columns(cursor, table)
    if column not in existing:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        print(f"  + {table}.{column}")
    else:
        print(f"  . {table}.{column} (already exists)")


def create_new_tables():
    # Let SQLAlchemy create tables that don't exist yet (rooms, git_context, ai_review_results, review_actions)
    print("\n[SQLAlchemy] creating new tables if they don't exist...")
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))

    import backend.models  # noqa: F401 — registers all models with Base
    from database.db import Base, engine
    Base.metadata.create_all(bind=engine)


def assign_legacy_rows_to_room(cur):
    orphaned = sum(
        cur.execute(f"SELECT COUNT(*) FROM {table} WHERE room_id IS NULL").fetchone()[0]
        for table in TENANT_TABLES
    )
    if not orphaned:
        print("  . no rows without a room")
        return

    from backend.models.room import generate_room_public_id

    cur.execute("SELECT id, public_id FROM rooms WHERE name = ? ORDER BY id LIMIT 1", (DEFAULT_ROOM_NAME,))
    row = cur.fetchone()
    if row:
        room_id, public_id = row
    else:
        public_id = generate_room_public_id()
        cur.execute(
            "INSERT INTO rooms (public_id, name, created_at) VALUES (?, ?, datetime('now'))",
            (public_id, DEFAULT_ROOM_NAME),
        )
        room_id = cur.lastrowid
        print(f"  + room '{DEFAULT_ROOM_NAME}' created with ID {public_id}")

    for table in TENANT_TABLES:
        cur.execute(f"UPDATE {table} SET room_id = ? WHERE room_id IS NULL", (room_id,))
        print(f"  + {table}: {cur.rowcount} row(s) moved into room {public_id}")


def run():
    create_new_tables()

    print(f"Connecting to {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    print("\n[users]")
    add_column_if_missing(cur, "users", "updated_at",     "DATETIME")
    add_column_if_missing(cur, "users", "deactivated_at", "DATETIME")
    add_column_if_missing(cur, "users", "created_by",     "INTEGER REFERENCES users(id)")
    add_column_if_missing(cur, "users", "last_login_at",  "DATETIME")
    add_column_if_missing(cur, "users", "room_id",        "INTEGER REFERENCES rooms(id)")

    print("\n[change_requests]")
    add_column_if_missing(cur, "change_requests", "current_reviewer_id", "INTEGER REFERENCES users(id)")
    add_column_if_missing(cur, "change_requests", "submitted_at",        "DATETIME")
    add_column_if_missing(cur, "change_requests", "closed_at",           "DATETIME")
    add_column_if_missing(cur, "change_requests", "room_id",             "INTEGER REFERENCES rooms(id)")

    print("\n[audit_logs]")
    add_column_if_missing(cur, "audit_logs", "request_id",  "INTEGER")
    add_column_if_missing(cur, "audit_logs", "ip_address",  "TEXT")
    add_column_if_missing(cur, "audit_logs", "user_agent",  "TEXT")
    add_column_if_missing(cur, "audit_logs", "severity",    "TEXT")
    add_column_if_missing(cur, "audit_logs", "old_value",   "TEXT")
    add_column_if_missing(cur, "audit_logs", "new_value",   "TEXT")
    add_column_if_missing(cur, "audit_logs", "room_id",     "INTEGER REFERENCES rooms(id)")

    print("\n[rooms]")
    for table in TENANT_TABLES:
        cur.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_room_id ON {table} (room_id)")
    assign_legacy_rows_to_room(cur)

    conn.commit()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    run()
