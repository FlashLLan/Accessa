"""What an audit entry stores and what the audit API returns."""
import ast
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.core.dependencies import get_current_user
from backend.models.audit_log import AuditLog
from backend.models.enums import RequestStatus
from backend.models.user import User
from backend.models.workspace import Workspace

ROOT = Path(__file__).resolve().parent.parent
USER_AGENT = "AccessaTest/2.0"


def _fake_hash(p):
    return f"TESTHASH:{p}"


@pytest.fixture(autouse=True)
def fake_bcrypt():
    with patch("backend.api.auth.verify_password", side_effect=lambda p, h: h == _fake_hash(p)), \
         patch("backend.api.auth.hash_password", side_effect=_fake_hash), \
         patch("backend.api.users.hash_password", side_effect=_fake_hash), \
         patch("backend.api.users.verify_password", side_effect=lambda p, h: h == _fake_hash(p)):
        yield


@pytest.fixture
def people(db, create_role, create_user):
    roles = {name: create_role(db, name, level=lvl) for name, lvl in
             [("junior", 1), ("mid", 2), ("senior", 3), ("lead", 4), ("admin", 5)]}
    return {
        "roles": roles,
        "admin": create_user(db, role=roles["admin"], label="admin"),
        "junior": create_user(db, role=roles["junior"], label="junior"),
        "mid": create_user(db, role=roles["mid"], label="mid"),
    }


def _list_audit(client, login_user, admin):
    login_user(admin)
    response = client.get("/audit-logs/", headers={"User-Agent": USER_AGENT})
    assert response.status_code == 200, response.text
    return response.json()


# --- actor_role ------------------------------------------------------------------

def test_audit_entry_keeps_actor_role_after_role_change(client, db, people, login_user, seed_change_request):
    req = seed_change_request(db, creator_id=people["junior"].id, reviewer_id=people["mid"].id)

    login_user(people["junior"])
    assert client.post(f"/change-requests/{req.id}/submit").status_code == 200

    login_user(people["admin"])
    changed = client.patch(f"/users/{people['junior'].id}/role", json={"role_id": people["roles"]["lead"].id})
    assert changed.status_code == 200, changed.text

    submitted = db.query(AuditLog).filter(AuditLog.action == "REQUEST_SUBMITTED").one()
    db.refresh(people["junior"])
    assert people["junior"].role.name == "lead"
    assert submitted.actor_role == "junior"  # the role at the time of the action

    role_changed = db.query(AuditLog).filter(AuditLog.action == "ROLE_CHANGED").one()
    assert role_changed.actor_role == "admin"
    assert (role_changed.old_value, role_changed.new_value) == ("junior", "lead")

    api_entry = next(e for e in _list_audit(client, login_user, people["admin"]) if e["action"] == "REQUEST_SUBMITTED")
    assert api_entry["actor_role"] == "junior"
    assert api_entry["user"]["role"]["name"] == "lead"


def test_audit_api_returns_ip_address_user_agent_and_actor_role(client, db, people, login_user, seed_change_request):
    req = seed_change_request(
        db, creator_id=people["junior"].id, reviewer_id=people["mid"].id, status=RequestStatus.PENDING_REVIEW
    )
    login_user(people["mid"])
    client.post(f"/change-requests/{req.id}/approve", json={}, headers={"User-Agent": USER_AGENT})

    entry = next(e for e in _list_audit(client, login_user, people["admin"]) if e["action"] == "REQUEST_APPROVED")
    assert entry["ip_address"] == "testclient"
    assert entry["user_agent"] == USER_AGENT
    assert entry["actor_role"] == "mid"


# --- entity references --------------------------------------------------------------

def test_audit_api_resolves_readable_entity_labels(client, db, people, login_user, seed_change_request):
    req = seed_change_request(db, creator_id=people["junior"].id, reviewer_id=people["mid"].id, title="Open port 443")
    login_user(people["junior"])
    client.post(f"/change-requests/{req.id}/submit")
    login_user(people["admin"])
    client.patch(f"/users/{people['mid'].id}/deactivate")
    _list_audit(client, login_user, people["admin"])  # writes AUDIT_VIEWED

    entries = {e["action"]: e for e in _list_audit(client, login_user, people["admin"])}

    submitted = entries["REQUEST_SUBMITTED"]
    assert (submitted["entity_id"], submitted["entity_label"]) == (req.id, "Open port 443")

    deactivated = entries["USER_DEACTIVATED"]
    mid = people["mid"]
    assert deactivated["entity_id"] == mid.id
    assert deactivated["entity_label"] == f"{mid.full_name} ({mid.email})"

    viewed = entries["AUDIT_VIEWED"]
    assert (viewed["entity_id"], viewed["entity_label"]) == (None, "Audit log")


def test_workspace_events_never_return_internal_workspace_id(client, db, create_role):
    create_role(db, "admin", level=5)
    signup = client.post("/auth/signup", json={
        "workspace_name": "Acme", "workspace_slug": "acme-co", "full_name": "Owner",
        "email": "owner@example.com", "password": "Password123",
    })
    token = signup.json()["access_token"]

    entries = client.get("/audit-logs/", headers={"Authorization": f"Bearer {token}"}).json()
    created = next(e for e in entries if e["action"] == "WORKSPACE_CREATED")

    workspace = db.query(Workspace).filter(Workspace.slug == "acme-co").one()
    assert created["entity_type"] == "workspace"
    assert created["entity_id"] is None
    assert created["entity_label"] == "acme-co"
    assert str(workspace.id) not in (created["details"] or "").split()
    assert workspace.slug in created["details"] and str(workspace.public_id) in created["details"]
    assert db.query(AuditLog).filter(AuditLog.action == "WORKSPACE_CREATED").one().entity_id is None


def test_old_workspace_rows_with_internal_id_are_masked(client, db, people, login_user):
    db.add(AuditLog(workspace_id=1, user_id=people["admin"].id, action="WORKSPACE_CREATED",
                    entity_type="workspace", entity_id=1, details="legacy row"))
    db.commit()

    entry = next(e for e in _list_audit(client, login_user, people["admin"]) if e["details"] == "legacy row")
    assert entry["entity_id"] is None
    assert entry["entity_label"] == "default-test"


def test_entity_label_is_not_resolved_across_workspaces(client, db, people, login_user, create_workspace, create_user):
    other = create_workspace(db, "Other", "other-ws")
    foreign_user = create_user(db, role=people["roles"]["mid"], label="foreign", workspace=other)
    db.add(AuditLog(workspace_id=1, user_id=people["admin"].id, action="USER_DEACTIVATED",
                    entity_type="user", entity_id=foreign_user.id, details="planted"))
    db.commit()

    entry = next(e for e in _list_audit(client, login_user, people["admin"]) if e["details"] == "planted")
    assert entry["entity_label"] is None


# --- no names or e-mails in audit rows ----------------------------------------------

def test_audit_rows_never_store_names_or_emails(client, db, people, login_user, seed_change_request):
    # Run every kind of action that writes an audit entry, then scan all rows.
    login_user(people["admin"])
    created = client.post("/users/", json={"full_name": "Zed Newcomer", "email": "zed@example.com",
                                           "password": "Password123", "role_id": people["roles"]["mid"].id})
    new_id = created.json()["id"]
    client.patch(f"/users/{new_id}/role", json={"role_id": people["roles"]["senior"].id})
    client.patch(f"/users/{new_id}/deactivate")
    client.patch(f"/users/{new_id}/reactivate")

    login_user(people["junior"])
    client.put("/users/me", json={"full_name": "Renamed Junior"})
    req = seed_change_request(db, creator_id=people["junior"].id, reviewer_id=people["mid"].id)
    client.post(f"/change-requests/{req.id}/comments", json={"comment_text": "ping mid@example.com please"})
    client.post(f"/change-requests/{req.id}/submit")

    lead = User(full_name="Lena Lead", email="lena@example.com", hashed_password="x",
                role_id=people["roles"]["lead"].id, workspace_id=1)
    db.add(lead)
    db.commit()
    login_user(people["mid"])
    client.post(f"/change-requests/{req.id}/escalate", json={"target_reviewer_id": lead.id})

    # Real logins: stop impersonating a user, keep the test database override.
    client.app.dependency_overrides.pop(get_current_user, None)
    people["junior"].hashed_password = _fake_hash("Password123")
    db.commit()
    client.post("/auth/login", json={"workspace_slug": "default-test", "email": people["junior"].email, "password": "Password123"})
    client.post("/auth/login", json={"workspace_slug": "default-test", "email": people["junior"].email, "password": "nope"})
    client.post("/auth/login", json={"workspace_slug": "default-test", "email": "ghost@example.com", "password": "nope"})

    rows = db.query(AuditLog).all()
    assert len(rows) >= 10
    users = db.query(User).all()
    forbidden = {u.email for u in users} | {u.full_name for u in users} | {"ghost@example.com", "Zed Newcomer"}
    email_pattern = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
    for row in rows:
        stored = " ".join(filter(None, [row.details, row.old_value, row.new_value, row.actor_role]))
        assert not email_pattern.search(stored), (row.action, stored)
        for value in forbidden:
            assert value not in stored, (row.action, value, stored)


def test_failed_login_with_unknown_email_is_listed_without_user(client, db, people, login_user):
    client.post("/auth/login", json={"workspace_slug": "default-test", "email": "ghost@example.com", "password": "x"})

    entry = next(e for e in _list_audit(client, login_user, people["admin"]) if e["action"] == "LOGIN_FAILED")
    assert entry["user"] is None
    assert entry["actor_role"] is None
    assert entry["entity_type"] == "workspace" and entry["entity_id"] is None


# --- frontend action list matches the backend -----------------------------------------

def _backend_action_codes() -> set[str]:
    codes = set()
    for path in (ROOT / "backend" / "api").glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "log_action":
                for kw in node.keywords:
                    if kw.arg == "action" and isinstance(kw.value, ast.Constant):
                        codes.add(kw.value.value)
            if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "audit_action" for t in node.targets):
                if isinstance(node.value, ast.Constant):
                    codes.add(node.value.value)
    return codes


def test_audit_page_lists_exactly_the_backend_action_codes():
    page = (ROOT / "frontend" / "src" / "pages" / "AuditLogPage.jsx").read_text()
    block = page[page.index("const ACTION_LABELS = {"):page.index("};", page.index("const ACTION_LABELS = {"))]
    frontend_codes = set(re.findall(r"^\s+([A-Z_]+):", block, re.M))

    assert frontend_codes == _backend_action_codes()
    assert not re.search(r"^\s+[a-z_]+:", block, re.M), "legacy lower-case action names are gone"
