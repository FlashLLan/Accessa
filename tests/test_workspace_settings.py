"""Workspace setting ai_review_scope (FR-23): admin-only, audited, per workspace."""
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.models.audit_log import AuditLog
from backend.models.enums import AIReviewScope
from backend.models.workspace import Workspace

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def people(db, create_role, create_user):
    roles = {name: create_role(db, name, level=lvl) for name, lvl in
             [("junior", 1), ("mid", 2), ("senior", 3), ("lead", 4), ("admin", 5)]}
    return {name: create_user(db, role=role, label=name) for name, role in roles.items()}


def _audit(db):
    return db.query(AuditLog).filter(AuditLog.action == "WORKSPACE_SETTING_CHANGED").all()


def test_new_workspace_defaults_to_changed_files(client, db, create_role):
    create_role(db, "admin", level=5)
    signup = client.post("/auth/signup", json={
        "workspace_name": "Acme", "workspace_slug": "acme-co", "full_name": "Owner",
        "email": "owner@example.com", "password": "Password123",
    })
    token = signup.json()["access_token"]

    response = client.get("/workspace/settings", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    assert response.json() == {"ai_review_scope": "changed_files"}


def test_admin_reads_and_changes_scope_and_it_is_audited(client, db, people, login_user):
    login_user(people["admin"])
    assert client.get("/workspace/settings").json() == {"ai_review_scope": "changed_files"}

    response = client.patch("/workspace/settings", json={"ai_review_scope": "extended"},
                            headers={"User-Agent": "SettingsTest/1.0"})
    assert response.status_code == 200, response.text
    assert response.json() == {"ai_review_scope": "extended"}
    assert client.get("/workspace/settings").json() == {"ai_review_scope": "extended"}

    db.expire_all()
    assert db.get(Workspace, 1).ai_review_scope is AIReviewScope.EXTENDED

    [entry] = _audit(db)
    assert (entry.old_value, entry.new_value) == ("changed_files", "extended")
    assert entry.entity_type == "workspace" and entry.entity_id is None
    assert entry.user_id == people["admin"].id and entry.actor_role == "admin"
    assert entry.workspace_id == 1
    assert entry.severity == "medium"
    assert entry.user_agent == "SettingsTest/1.0"

    client.patch("/workspace/settings", json={"ai_review_scope": "changed_files"})
    assert [(e.old_value, e.new_value) for e in _audit(db)] == [
        ("changed_files", "extended"), ("extended", "changed_files"),
    ]


def test_saving_the_same_value_writes_no_audit_entry(client, db, people, login_user):
    login_user(people["admin"])
    response = client.patch("/workspace/settings", json={"ai_review_scope": "changed_files"})
    assert response.status_code == 200
    assert _audit(db) == []


@pytest.mark.parametrize("role", ["junior", "mid", "senior", "lead"])
def test_non_admins_can_neither_read_nor_change_the_setting(client, db, people, login_user, role):
    login_user(people[role])
    assert client.get("/workspace/settings").status_code == 403
    assert client.patch("/workspace/settings", json={"ai_review_scope": "extended"}).status_code == 403

    db.expire_all()
    assert db.get(Workspace, 1).ai_review_scope is AIReviewScope.CHANGED_FILES
    assert _audit(db) == []


@pytest.mark.parametrize("body", [{"ai_review_scope": "everything"}, {"ai_review_scope": "EXTENDED"}, {}])
def test_invalid_values_are_rejected(client, db, people, login_user, body):
    login_user(people["admin"])
    assert client.patch("/workspace/settings", json=body).status_code == 422
    assert _audit(db) == []


def test_change_only_affects_the_admins_own_workspace(client, db, people, login_user, create_workspace,
                                                     create_user, create_role):
    other = create_workspace(db, "Other", "other-ws")
    other_admin = create_user(db, role=people["admin"].role, label="other-admin", workspace=other)

    login_user(other_admin)
    assert client.patch("/workspace/settings", json={"ai_review_scope": "extended"}).status_code == 200

    db.expire_all()
    assert db.get(Workspace, other.id).ai_review_scope is AIReviewScope.EXTENDED
    assert db.get(Workspace, 1).ai_review_scope is AIReviewScope.CHANGED_FILES

    login_user(people["admin"])
    assert client.get("/workspace/settings").json() == {"ai_review_scope": "changed_files"}
    [entry] = _audit(db)
    assert entry.workspace_id == other.id


def test_database_rejects_unknown_scope(db, app_db_engine):
    with pytest.raises(IntegrityError):
        with app_db_engine.begin() as conn:
            conn.execute(text("UPDATE workspaces SET ai_review_scope = 'EVERYTHING' WHERE id = 1"))


def test_migration_gives_existing_workspaces_changed_files(db, owner_db_engine):
    config = Config(str(ROOT / "alembic.ini"))
    db.close()
    command.downgrade(config, "bf5fd76651b0")
    try:
        with owner_db_engine.begin() as conn:
            conn.execute(text("INSERT INTO workspaces (slug, name, public_id) "
                              "VALUES ('legacy-ws', 'Legacy', gen_random_uuid())"))
        command.upgrade(config, "7a1e3c9d2b40")
        with owner_db_engine.connect() as conn:
            scopes = conn.execute(text("SELECT slug, ai_review_scope FROM workspaces ORDER BY slug")).all()
        assert scopes == [("default-test", "CHANGED_FILES"), ("legacy-ws", "CHANGED_FILES")]
    finally:
        command.upgrade(config, "head")
