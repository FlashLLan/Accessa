"""Data handling of migration c5ee582f5a9e on legacy rows.

The test database is moved back to the previous revision, legacy rows are
written as the schema owner (as they could exist in an older database), and the
migration is applied again. The database is always returned to head.
"""
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent
PREVIOUS = "5d4a194aa17b"
TARGET = "c5ee582f5a9e"


def _alembic(action, revision):
    getattr(command, action)(Config(str(ROOT / "alembic.ini")), revision)


@pytest.fixture
def legacy_schema(db, owner_db_engine):
    db.close()  # no open transaction may hold locks while tables are altered
    _alembic("downgrade", PREVIOUS)
    try:
        with owner_db_engine.begin() as conn:
            conn.execute(text("INSERT INTO roles (id, name, level) VALUES (1, 'junior', 1), (2, 'mid', 2)"))
            conn.execute(text(
                "INSERT INTO users (id, workspace_id, full_name, email, hashed_password, role_id, is_active, created_at, updated_at) VALUES "
                "(1, 1, 'Creator', 'c@example.com', 'x', 1, true,  '2026-03-01 10:00+00', NULL), "
                "(2, 1, 'Reviewer', 'r@example.com', 'x', 2, NULL, '2026-03-02 10:00+00', '2026-03-05 10:00+00'), "
                "(3, 1, 'No dates', 'n@example.com', 'x', 2, true, NULL, '2026-03-07 10:00+00')"
            ))
            conn.execute(text(
                "INSERT INTO change_requests (id, workspace_id, title, description, request_type, target_system, "
                "environment, risk_level, status, created_by, assigned_reviewer_id) VALUES "
                "(1, 1, 't', 'd', 'ACCESS_CHANGE', 's', 'DEV', 'LOW', 'PENDING_REVIEW', 1, 2), "
                "(2, 1, 't', 'd', 'ACCESS_CHANGE', 's', 'DEV', 'LOW', 'DRAFT', 1, 2)"
            ))
            conn.execute(text(
                "INSERT INTO review_actions (change_request_id, actor_id, action_type, target_reviewer_id, from_status, to_status) "
                "VALUES (1, 2, 'DELEGATE', 3, 'PENDING_REVIEW', 'PENDING_REVIEW')"
            ))
            conn.execute(text(
                "INSERT INTO git_context (change_request_id, pull_request_url, merge_request_url) VALUES "
                "(1, NULL, 'https://gitlab.com/o/r/-/merge_requests/1'), "
                "(2, 'https://github.com/o/r/pull/2', 'https://github.com/o/r/pull/2')"
            ))
        yield owner_db_engine
    finally:
        _alembic("upgrade", "head")


def test_migration_merges_urls_drops_columns_and_backfills_users(legacy_schema):
    _alembic("upgrade", TARGET)

    with legacy_schema.connect() as conn:
        urls = dict(conn.execute(text("SELECT change_request_id, pull_request_url FROM git_context")).all())
        assert urls == {
            1: "https://gitlab.com/o/r/-/merge_requests/1",  # copied from merge_request_url
            2: "https://github.com/o/r/pull/2",              # identical values collapse to one
        }

        git_cols = {r[0] for r in conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'git_context'"))}
        assert "merge_request_url" not in git_cols

        action_cols = {r[0]: r[1] for r in conn.execute(text(
            "SELECT column_name, is_nullable FROM information_schema.columns WHERE table_name = 'review_actions'"))}
        assert "from_status" not in action_cols and "to_status" not in action_cols
        assert action_cols["target_reviewer_id"] == "NO"
        assert conn.execute(text("SELECT action_type FROM review_actions")).scalar_one() == "DELEGATE"

        users = {r.id: r for r in conn.execute(text("SELECT id, is_active, created_at, updated_at FROM users"))}
        assert users[1].updated_at == users[1].created_at          # NULL updated_at <- created_at
        assert users[2].is_active is False                          # NULL is_active stays locked out
        assert users[3].created_at == users[3].updated_at          # NULL created_at <- updated_at

        nullable = {r[0]: r[1] for r in conn.execute(text(
            "SELECT column_name, is_nullable FROM information_schema.columns WHERE table_name = 'users' "
            "AND column_name IN ('is_active', 'created_at', 'updated_at')"))}
        assert nullable == {"is_active": "NO", "created_at": "NO", "updated_at": "NO"}


@pytest.mark.parametrize("bad_row", [
    "UPDATE change_requests SET status = 'ESCALATED' WHERE id = 1",
    "UPDATE change_requests SET status = 'CANCELLED' WHERE id = 1",
    "UPDATE review_actions SET action_type = 'COMMENT'",
    "UPDATE review_actions SET target_reviewer_id = NULL",
    "UPDATE git_context SET pull_request_url = 'https://github.com/o/r/pull/9' WHERE change_request_id = 1",
])
def test_migration_refuses_rows_that_would_lose_meaning(legacy_schema, bad_row):
    with legacy_schema.begin() as conn:
        conn.execute(text(bad_row))

    with pytest.raises(Exception) as exc:
        _alembic("upgrade", TARGET)
    assert "Resolve them before upgrading" in str(exc.value)

    # Nothing was changed: the upgrade ran in one transaction and rolled back.
    with legacy_schema.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert version == PREVIOUS

    # Undo the planted row so the fixture can bring the database back to head.
    with legacy_schema.begin() as conn:
        conn.execute(text("DELETE FROM review_actions"))
        conn.execute(text("DELETE FROM git_context"))
        conn.execute(text("UPDATE change_requests SET status = 'DRAFT'"))
