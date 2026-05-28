"""
Database migration script.
Adds new columns to existing tables and creates new tables via SQLAlchemy.
Safe to run multiple times — skips columns that already exist.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "accessa.db"


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


def run():
    print(f"Connecting to {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    print("\n[users]")
    add_column_if_missing(cur, "users", "updated_at",     "DATETIME")
    add_column_if_missing(cur, "users", "deactivated_at", "DATETIME")
    add_column_if_missing(cur, "users", "created_by",     "INTEGER REFERENCES users(id)")
    add_column_if_missing(cur, "users", "last_login_at",  "DATETIME")

    print("\n[change_requests]")
    add_column_if_missing(cur, "change_requests", "current_reviewer_id", "INTEGER REFERENCES users(id)")
    add_column_if_missing(cur, "change_requests", "submitted_at",        "DATETIME")
    add_column_if_missing(cur, "change_requests", "closed_at",           "DATETIME")

    print("\n[audit_logs]")
    add_column_if_missing(cur, "audit_logs", "request_id",  "INTEGER")
    add_column_if_missing(cur, "audit_logs", "ip_address",  "TEXT")
    add_column_if_missing(cur, "audit_logs", "user_agent",  "TEXT")
    add_column_if_missing(cur, "audit_logs", "severity",    "TEXT")
    add_column_if_missing(cur, "audit_logs", "old_value",   "TEXT")
    add_column_if_missing(cur, "audit_logs", "new_value",   "TEXT")

    conn.commit()
    conn.close()

    # Let SQLAlchemy create the new tables (git_context, ai_review_results, review_actions)
    print("\n[SQLAlchemy] creating new tables if they don't exist...")
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))

    import backend.models  # noqa: F401 — registers all models with Base
    from database.db import Base, engine
    Base.metadata.create_all(bind=engine)
    print("Done.")


if __name__ == "__main__":
    run()
