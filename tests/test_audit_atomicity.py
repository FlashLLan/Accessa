"""A state change and its audit entry are committed in one transaction, and every
audit entry records the client's IP address and User-Agent."""
import ast
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import text

from backend.models.audit_log import AuditLog
from backend.models.enums import RequestStatus

ROOT = Path(__file__).resolve().parent.parent
USER_AGENT = "AccessaTest/1.0 (audit)"
# TestClient connects from this pseudo-host; it is what request.client.host reports.
TEST_CLIENT_IP = "testclient"


@pytest.fixture
def people(db, create_role, create_user):
    roles = {name: create_role(db, name, level=lvl) for name, lvl in
             [("junior", 1), ("mid", 2), ("senior", 3), ("lead", 4), ("admin", 5)]}
    return {
        "roles": roles,
        "creator": create_user(db, role=roles["junior"], label="creator"),
        "reviewer": create_user(db, role=roles["mid"], label="reviewer"),
        "senior": create_user(db, role=roles["senior"], label="senior"),
        "admin": create_user(db, role=roles["admin"], label="admin"),
    }


@pytest.fixture
def pending(db, people, seed_change_request):
    return seed_change_request(
        db, creator_id=people["creator"].id, reviewer_id=people["reviewer"].id, status=RequestStatus.PENDING_REVIEW
    )


def _committed(app_db_engine, sql, **params):
    """Read through a separate connection: only committed data is visible."""
    with app_db_engine.connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


# --- client info on audit entries ---------------------------------------------

def test_approve_writes_exactly_one_audit_row_with_client_info(client, db, people, pending, login_user):
    before = db.query(AuditLog).count()

    login_user(people["reviewer"])
    response = client.post(
        f"/change-requests/{pending.id}/approve",
        json={"decision_comment": "ok"},
        headers={"User-Agent": USER_AGENT},
    )

    assert response.status_code == 200, response.text
    new_rows = db.query(AuditLog).order_by(AuditLog.id).all()[before:]
    assert len(new_rows) == 1
    entry = new_rows[0]
    assert entry.action == "REQUEST_APPROVED"
    assert entry.entity_id == pending.id
    assert entry.ip_address == TEST_CLIENT_IP
    assert entry.user_agent == USER_AGENT


def test_login_success_and_failure_record_client_info(client, db, people):
    people["reviewer"].hashed_password = "TESTHASH:Password123"
    db.commit()

    with patch("backend.api.auth.verify_password", side_effect=lambda p, h: h == f"TESTHASH:{p}"):
        ok = client.post("/auth/login", headers={"User-Agent": USER_AGENT}, json={
            "workspace_slug": "default-test", "email": people["reviewer"].email, "password": "Password123"})
        bad = client.post("/auth/login", headers={"User-Agent": USER_AGENT}, json={
            "workspace_slug": "default-test", "email": people["reviewer"].email, "password": "wrong"})

    assert (ok.status_code, bad.status_code) == (200, 401)
    for action in ("LOGIN_SUCCESS", "LOGIN_FAILED"):
        entry = db.query(AuditLog).filter(AuditLog.action == action).one()
        assert (entry.ip_address, entry.user_agent) == (TEST_CLIENT_IP, USER_AGENT)


def test_user_agent_is_truncated(client, db, people, pending, login_user):
    login_user(people["reviewer"])
    client.post(f"/change-requests/{pending.id}/approve", json={}, headers={"User-Agent": "x" * 5000})

    entry = db.query(AuditLog).filter(AuditLog.action == "REQUEST_APPROVED").one()
    assert len(entry.user_agent) == 512


def test_every_log_action_call_passes_client_info():
    """Static guard: no audit call in the API may omit ip_address / user_agent."""
    missing = []
    for path in sorted((ROOT / "backend" / "api").glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "log_action":
                keywords = {k.arg for k in node.keywords}
                if not {"ip_address", "user_agent"} <= keywords:
                    missing.append(f"{path.name}:{node.lineno}")
    assert missing == []


# --- atomicity: if the audit entry cannot be written, nothing is stored --------

def test_failed_audit_write_rolls_back_approval(client, db, app_db_engine, people, pending, login_user):
    login_user(people["reviewer"])
    with patch("backend.api.change_requests.log_action", side_effect=RuntimeError("audit store down")):
        with pytest.raises(RuntimeError, match="audit store down"):
            client.post(f"/change-requests/{pending.id}/approve", json={"decision_comment": "ok"})

    assert _committed(app_db_engine, "SELECT status FROM change_requests WHERE id = :id", id=pending.id) == "PENDING_REVIEW"
    assert _committed(app_db_engine, "SELECT count(*) FROM approvals WHERE change_request_id = :id", id=pending.id) == 0
    assert _committed(app_db_engine, "SELECT count(*) FROM audit_logs") == 0


@pytest.mark.parametrize("actor,method,path,body,module,check_sql,expected", [
    ("reviewer", "post", "/change-requests/{id}/reject", {"decision_comment": "no"}, "change_requests",
     "SELECT status FROM change_requests WHERE id = {id}", "PENDING_REVIEW"),
    ("reviewer", "post", "/change-requests/{id}/comments", {"comment_text": "hi"}, "change_requests",
     "SELECT count(*) FROM comments", 0),
    ("reviewer", "post", "/change-requests/{id}/escalate", {"target_reviewer_id": "senior"}, "review_actions",
     "SELECT assigned_reviewer_id = {reviewer} FROM change_requests WHERE id = {id}", True),
    ("reviewer", "post", "/change-requests/{id}/git-context", {"branch_name": "x"}, "git_context",
     "SELECT count(*) FROM git_context", 0),
    # AI review: covered in test_ai_review.py (needs GitHub and OpenAI mocked).
    ("admin", "patch", "/users/{creator}/deactivate", None, "users",
     "SELECT is_active FROM users WHERE id = {creator}", True),
])
def test_failed_audit_write_rolls_back_state_change(
    client, db, app_db_engine, people, pending, login_user, actor, method, path, body, module, check_sql, expected
):
    ids = {"id": pending.id, "creator": people["creator"].id, "reviewer": people["reviewer"].id}
    if body and body.get("target_reviewer_id") == "senior":
        body = {"target_reviewer_id": people["senior"].id}

    login_user(people[actor])
    with patch(f"backend.api.{module}.log_action", side_effect=RuntimeError("audit store down")):
        with pytest.raises(RuntimeError):
            client.request(method.upper(), path.format(**ids), json=body)

    assert _committed(app_db_engine, check_sql.format(**ids)) == expected
    assert _committed(app_db_engine, "SELECT count(*) FROM audit_logs") == 0


def test_failed_audit_write_rolls_back_new_change_request_and_git_context(client, db, app_db_engine, people, login_user):
    login_user(people["creator"])
    with patch("backend.api.change_requests.log_action", side_effect=[None, RuntimeError("audit store down")]):
        with pytest.raises(RuntimeError):
            client.post("/change-requests/", json={
                "title": "t", "description": "d", "request_type": "access_change", "target_system": "s",
                "environment": "development", "risk_level": "low", "assigned_reviewer_id": people["reviewer"].id,
                "git_context": {"branch_name": "feature/x"},
            })

    # The request, its git context and the first audit entry share one transaction.
    assert _committed(app_db_engine, "SELECT count(*) FROM change_requests") == 0
    assert _committed(app_db_engine, "SELECT count(*) FROM git_context") == 0
    assert _committed(app_db_engine, "SELECT count(*) FROM audit_logs") == 0
