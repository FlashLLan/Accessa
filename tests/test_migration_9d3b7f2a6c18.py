"""Migration 9d3b7f2a6c18 adds what an AI review was based on; existing results keep defaults."""
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

ROOT = Path(__file__).resolve().parent.parent


def test_existing_results_get_defaults_and_scope_is_checked(db, owner_db_engine):
    config = Config(str(ROOT / "alembic.ini"))
    db.close()
    command.downgrade(config, "2c4f8e1a9b63")
    try:
        with owner_db_engine.begin() as conn:
            conn.execute(text("INSERT INTO roles (id, name, level) VALUES (1, 'junior', 1)"))
            conn.execute(text("INSERT INTO users (id, workspace_id, full_name, email, hashed_password, role_id) "
                              "VALUES (1, 1, 'U', 'u@example.com', 'x', 1)"))
            conn.execute(text(
                "INSERT INTO change_requests (id, workspace_id, title, description, request_type, target_system, "
                "environment, risk_level, status, created_by, assigned_reviewer_id) "
                "VALUES (1, 1, 't', 'd', 'ACCESS_CHANGE', 's', 'DEV', 'LOW', 'PENDING_REVIEW', 1, 1)"))
            conn.execute(text("INSERT INTO ai_review_results (change_request_id, summary, model_name) "
                              "VALUES (1, 'stub', 'stub')"))
        command.upgrade(config, "9d3b7f2a6c18")
        with owner_db_engine.connect() as conn:
            row = conn.execute(text(
                "SELECT reviewed_commit, review_scope, files_reviewed, files_skipped, changed_files_total, "
                "input_truncated, secrets_masked FROM ai_review_results")).one()
        assert tuple(row) == (None, None, None, None, None, False, 0)

        with pytest.raises(IntegrityError):
            with owner_db_engine.begin() as conn:
                conn.execute(text("UPDATE ai_review_results SET review_scope = 'EVERYTHING'"))
    finally:
        command.upgrade(config, "head")
