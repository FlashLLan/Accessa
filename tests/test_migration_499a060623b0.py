"""Migration 499a060623b0 drops change_requests.current_reviewer_id.

A request whose current_reviewer_id named a different user than its
assigned_reviewer_id is reassigned to that current reviewer before the column is
dropped, so the person who held the request keeps it.
"""
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent
PREVIOUS = "c5ee582f5a9e"
TARGET = "499a060623b0"


def _alembic(action, revision):
    getattr(command, action)(Config(str(ROOT / "alembic.ini")), revision)


@pytest.fixture
def legacy_schema(db, owner_db_engine):
    db.close()
    _alembic("downgrade", PREVIOUS)
    try:
        with owner_db_engine.begin() as conn:
            conn.execute(text("INSERT INTO roles (id, name, level) VALUES (1, 'junior', 1), (2, 'mid', 2), (3, 'senior', 3)"))
            conn.execute(text(
                "INSERT INTO users (id, workspace_id, full_name, email, hashed_password, role_id) VALUES "
                "(1, 1, 'Creator', 'c@example.com', 'x', 1), (2, 1, 'Assigned', 'a@example.com', 'x', 2), "
                "(3, 1, 'Holder', 'h@example.com', 'x', 3)"
            ))
            conn.execute(text(
                "INSERT INTO change_requests (id, workspace_id, title, description, request_type, target_system, "
                "environment, risk_level, status, created_by, assigned_reviewer_id, current_reviewer_id) VALUES "
                "(1, 1, 't', 'd', 'ACCESS_CHANGE', 's', 'DEV', 'LOW', 'PENDING_REVIEW', 1, 2, 3), "   # differs
                "(2, 1, 't', 'd', 'ACCESS_CHANGE', 's', 'DEV', 'LOW', 'PENDING_REVIEW', 1, 3, 3), "   # same
                "(3, 1, 't', 'd', 'ACCESS_CHANGE', 's', 'DEV', 'LOW', 'PENDING_REVIEW', 1, 2, NULL)"  # never moved
            ))
        yield owner_db_engine
    finally:
        _alembic("upgrade", "head")


def test_migration_reassigns_to_current_reviewer_and_drops_column(legacy_schema):
    _alembic("upgrade", TARGET)

    with legacy_schema.connect() as conn:
        assigned = dict(conn.execute(text("SELECT id, assigned_reviewer_id FROM change_requests")).all())
        assert assigned == {1: 3, 2: 3, 3: 2}

        columns = {r[0] for r in conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'change_requests'"))}
        assert "current_reviewer_id" not in columns

        constraints = {r[0] for r in conn.execute(text(
            "SELECT conname FROM pg_constraint WHERE conrelid = 'change_requests'::regclass"))}
        assert "fk_change_requests_workspace_id_current_reviewer_id_users" not in constraints
        assert "fk_change_requests_workspace_id_assigned_reviewer_id_users" in constraints
