"""Migration 2c4f8e1a9b63 drops workspaces.ai_review_scope (the scope is chosen per AI review)."""
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent


def _columns(conn):
    return {r[0] for r in conn.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'workspaces'"))}


def test_workspace_scope_column_is_dropped(db, owner_db_engine):
    config = Config(str(ROOT / "alembic.ini"))
    db.close()
    command.downgrade(config, "7a1e3c9d2b40")
    try:
        with owner_db_engine.connect() as conn:
            assert "ai_review_scope" in _columns(conn)
        command.upgrade(config, "2c4f8e1a9b63")
        with owner_db_engine.connect() as conn:
            assert "ai_review_scope" not in _columns(conn)
            constraints = {r[0] for r in conn.execute(text(
                "SELECT conname FROM pg_constraint WHERE conrelid = 'workspaces'::regclass"))}
            assert "ck_workspaces_ai_review_scope" not in constraints
            # Existing workspaces survive the drop.
            assert conn.execute(text("SELECT slug FROM workspaces")).scalars().all() == ["default-test"]
    finally:
        command.upgrade(config, "head")
