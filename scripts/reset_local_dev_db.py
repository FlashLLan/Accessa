"""Reset the LOCAL development database: drop it, recreate it, migrate, seed.

    python scripts/reset_local_dev_db.py            # asks you to type the database name
    python scripts/reset_local_dev_db.py --yes      # no prompt

ALL DATA in the database named by DATABASE_URL is destroyed, including the
append-only audit log (dropping the database is the only way to clear it).

Guards:
- refuses unless the host in DATABASE_URL and MIGRATION_DATABASE_URL is
  localhost / 127.0.0.1 / ::1, checked before any connection is opened;
- refuses if the two URLs point at different databases;
- asks for the database name to be typed unless --yes is given.

Stop the backend first: open connections of the application role cannot be
terminated by the schema owner, and the drop would fail.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parent.parent
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def fail(message: str) -> None:
    print(f"REFUSED: {message}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")  # explicitly set environment variables take precedence
    app_url_raw = os.getenv("DATABASE_URL")
    owner_url_raw = os.getenv("MIGRATION_DATABASE_URL")
    if not app_url_raw or not owner_url_raw:
        fail("DATABASE_URL and MIGRATION_DATABASE_URL must both be set (see .env.example).")

    app_url, owner_url = make_url(app_url_raw), make_url(owner_url_raw)

    # --- guard: local only, checked before connecting anywhere ------------------
    for name, url in (("DATABASE_URL", app_url), ("MIGRATION_DATABASE_URL", owner_url)):
        if not url.drivername.startswith("postgresql"):
            fail(f"{name} is not a PostgreSQL URL.")
        if (url.host or "") not in LOCAL_HOSTS:
            fail(f"{name} host is '{url.host}'. This script only resets a database on localhost.")
    if (app_url.host, app_url.port, app_url.database) != (owner_url.host, owner_url.port, owner_url.database):
        fail("DATABASE_URL and MIGRATION_DATABASE_URL point at different databases.")

    database, app_role = app_url.database, app_url.username
    print(f"About to DROP and recreate database '{database}' on {app_url.host}:{app_url.port or 5432}.")
    if not args.yes:
        if input(f"Type the database name ('{database}') to continue: ").strip() != database:
            fail("confirmation did not match.")

    # --- drop and recreate (as the schema owner, via the maintenance database) --
    maintenance = create_engine(
        owner_url.set(database="postgres").render_as_string(hide_password=False), isolation_level="AUTOCOMMIT"
    )
    try:
        with maintenance.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{database}"'))
    except Exception as exc:  # noqa: BLE001 - report and stop
        fail(f"could not drop/recreate the database ({exc.__class__.__name__}). Is the backend still running?")
    finally:
        maintenance.dispose()
    print(f"Recreated database '{database}'.")

    # --- database-level grants (same as docker/postgres/init/01-roles.sh) -------
    # Table grants and the append-only audit_logs come from the Alembic migrations.
    owner = create_engine(owner_url.render_as_string(hide_password=False), isolation_level="AUTOCOMMIT")
    with owner.connect() as conn:
        for statement in (
            f'REVOKE ALL ON DATABASE "{database}" FROM PUBLIC',
            f'GRANT CONNECT ON DATABASE "{database}" TO "{app_role}"',
            "REVOKE CREATE ON SCHEMA public FROM PUBLIC",
            f'GRANT USAGE ON SCHEMA public TO "{app_role}"',
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO \"{app_role}\"",
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO \"{app_role}\"",
        ):
            conn.execute(text(statement))
    owner.dispose()

    # --- schema and seed data ----------------------------------------------------
    for step in (
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        [sys.executable, "-m", "backend.core.seed_roles"],
        [sys.executable, "-m", "backend.core.seed_admin"],
    ):
        print("$", " ".join(step[1:]))
        subprocess.run(step, cwd=ROOT, check=True)

    print(f"\nDone. Log in at /w/default as admin@test.com (password from backend/core/seed_admin.py).")


if __name__ == "__main__":
    main()
