"""Workspace (tenant) isolation tests.

Runs against PostgreSQL as the application role (see conftest.py). Sections follow
the requirements in the thesis; test names state the property being proven.
"""
from unittest.mock import patch

import psycopg.errors
import pytest
import jwt as pyjwt
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from backend.api import change_requests as change_requests_api
from backend.core.dependencies import get_current_user
from backend.core.security import ALGORITHM, SECRET_KEY, create_access_token
from backend.main import app
from backend.models.audit_log import AuditLog
from backend.models.change_request import ChangeRequest
from backend.models.comment import Comment
from backend.models.enums import RequestStatus, RiskLevel
from backend.models.review_action import ReviewAction
from backend.models.user import User
from backend.models.workspace import Workspace
from backend.services.approval_service import can_user_decide_request
from backend.services.workspace_service import RESERVED_SLUGS

PASSWORD = "Password123"


def _fake_hash(password):
    return f"TESTHASH:{password}"


def _fake_verify(plain, hashed):
    return hashed == _fake_hash(plain)


@pytest.fixture(autouse=True)
def fake_bcrypt():
    """Skip bcrypt cost; every module that hashes or verifies uses the same fake."""
    with patch("backend.api.auth.verify_password", side_effect=_fake_verify), \
         patch("backend.api.auth.hash_password", side_effect=_fake_hash), \
         patch("backend.api.users.verify_password", side_effect=_fake_verify), \
         patch("backend.api.users.hash_password", side_effect=_fake_hash):
        yield


def use_real_tokens():
    """Drop the get_current_user override so requests go through real JWT checks."""
    app.dependency_overrides.pop(get_current_user, None)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


SIGNUP = {
    "workspace_name": "Platform Team",
    "workspace_slug": "platform-team",
    "full_name": "Workspace Owner",
    "email": "owner@platform.com",
    "password": "StrongPass1!",
}


@pytest.fixture
def roles(db, create_role):
    return {
        name: create_role(db, name, level=level)
        for name, level in [("junior", 1), ("mid", 2), ("senior", 3), ("lead", 4), ("admin", 5)]
    }


@pytest.fixture
def ws(db, roles, create_workspace, create_user, seed_change_request):
    """Two unrelated workspaces. A is the default test workspace (id 1)."""
    a = db.get(Workspace, 1)
    b = create_workspace(db, "Other Team", "other-team")

    def user(role, label, workspace):
        u = create_user(db, role=roles[role], label=label, workspace=workspace)
        u.hashed_password = _fake_hash(PASSWORD)
        db.commit()
        return u

    data = {
        "a": a, "b": b,
        "admin_a": user("admin", "admin_a", a),
        "junior_a": user("junior", "junior_a", a),
        "mid_a": user("mid", "mid_a", a),
        "admin_b": user("admin", "admin_b", b),
        "junior_b": user("junior", "junior_b", b),
        "mid_b": user("mid", "mid_b", b),
        "lead_b": user("lead", "lead_b", b),
    }
    data["request_a"] = seed_change_request(
        db, creator_id=data["junior_a"].id, reviewer_id=data["mid_a"].id, status=RequestStatus.PENDING_REVIEW
    )
    data["request_b"] = seed_change_request(
        db, creator_id=data["junior_b"].id, reviewer_id=data["mid_b"].id, status=RequestStatus.PENDING_REVIEW
    )
    return data


def login(client, slug, email, password=PASSWORD):
    return client.post("/auth/login", json={"workspace_slug": slug, "email": email, "password": password})


# =============================================================================
# 1. Email is unique per workspace, not globally
# =============================================================================

def test_same_email_can_exist_in_two_workspaces(client, db, roles, ws, login_user):
    login_user(ws["admin_b"])
    response = client.post("/users/", json={
        "full_name": "Namesake", "email": ws["junior_a"].email, "password": PASSWORD, "role_id": roles["junior"].id,
    })

    assert response.status_code == 200, response.text
    same_email = db.query(User).filter(User.email == ws["junior_a"].email).all()
    assert {u.workspace_id for u in same_email} == {ws["a"].id, ws["b"].id}


def test_duplicate_email_in_one_workspace_is_rejected(client, db, roles, ws, login_user):
    login_user(ws["admin_a"])
    response = client.post("/users/", json={
        "full_name": "Duplicate", "email": ws["junior_a"].email, "password": PASSWORD, "role_id": roles["junior"].id,
    })

    assert response.status_code == 400
    assert db.query(User).filter(User.email == ws["junior_a"].email).count() == 1


def test_database_rejects_duplicate_email_in_one_workspace(app_db_engine, ws):
    with pytest.raises(IntegrityError) as exc, app_db_engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO users (workspace_id, full_name, email, hashed_password, role_id) "
            "VALUES (:ws, 'Dup', :email, 'x', :role)"
        ), {"ws": ws["a"].id, "email": ws["junior_a"].email, "role": ws["junior_a"].role_id})

    assert isinstance(exc.value.orig, psycopg.errors.UniqueViolation)
    assert "uq_users_workspace_id_email" in str(exc.value.orig)


# =============================================================================
# 2-3. Login is workspace-scoped and does not reveal which accounts exist
# =============================================================================

def test_login_with_right_credentials_but_wrong_workspace_slug_is_rejected(client, ws):
    assert login(client, ws["a"].slug, ws["junior_a"].email).status_code == 200

    response = login(client, ws["b"].slug, ws["junior_a"].email)

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid credentials"}


def test_login_failures_are_indistinguishable(client, db, ws):
    ws["junior_a"].is_active = False
    db.commit()

    responses = {
        "unknown slug": login(client, "no-such-workspace", ws["mid_a"].email),
        "unknown email": login(client, ws["a"].slug, "ghost@example.com"),
        "wrong password": login(client, ws["a"].slug, ws["mid_a"].email, "WrongPassword"),
        "inactive account": login(client, ws["a"].slug, ws["junior_a"].email),
    }

    observed = {(r.status_code, r.text, r.headers.get("content-type")) for r in responses.values()}
    assert observed == {(401, '{"detail":"Invalid credentials"}', "application/json")}, responses


def test_failed_login_for_unknown_email_is_audited_with_null_user(client, db, ws):
    login(client, ws["a"].slug, "ghost@example.com")
    login(client, "no-such-workspace", "ghost@example.com")

    failures = db.query(AuditLog).filter(AuditLog.action == "LOGIN_FAILED").all()
    assert len(failures) == 1  # unknown slug: no workspace to record it in
    assert failures[0].workspace_id == ws["a"].id
    assert failures[0].user_id is None


# =============================================================================
# 4. Change requests of another workspace are unreachable (404)
# =============================================================================

REQUEST_ENDPOINTS = [
    ("get", "/change-requests/{id}", None),
    ("patch", "/change-requests/{id}", {"title": "hijacked"}),
    ("post", "/change-requests/{id}/submit", None),
    ("post", "/change-requests/{id}/approve", {"decision_comment": "ok"}),
    ("post", "/change-requests/{id}/reject", {"decision_comment": "no"}),
    ("post", "/change-requests/{id}/escalate", {"target_reviewer_id": "lead_b"}),
    ("post", "/change-requests/{id}/delegate", {"target_reviewer_id": "mid_b"}),
    ("post", "/change-requests/{id}/apply", None),
    ("get", "/change-requests/{id}/approvals", None),
    ("get", "/change-requests/{id}/comments", None),
    ("post", "/change-requests/{id}/comments", {"comment_text": "hi"}),
    ("get", "/change-requests/{id}/review-actions", None),
    ("get", "/change-requests/{id}/git-context", None),
    ("post", "/change-requests/{id}/git-context", {"branch_name": "x"}),
    ("get", "/change-requests/{id}/ai-review", None),
    ("post", "/change-requests/{id}/ai-review", None),
]


@pytest.mark.parametrize("actor", ["admin_a", "mid_a"])
@pytest.mark.parametrize("method,path,body", REQUEST_ENDPOINTS)
def test_user_gets_404_for_change_request_of_another_workspace(
    client, db, ws, login_user, actor, method, path, body
):
    if body and "target_reviewer_id" in body:
        body = {"target_reviewer_id": ws[body["target_reviewer_id"]].id}
    before = (ws["request_b"].title, ws["request_b"].status, ws["request_b"].assigned_reviewer_id)

    login_user(ws[actor])
    response = client.request(method.upper(), path.format(id=ws["request_b"].id), json=body)

    assert response.status_code == 404, response.text
    assert response.json() == {"detail": "Change request not found"}
    db.refresh(ws["request_b"])
    assert (ws["request_b"].title, ws["request_b"].status, ws["request_b"].assigned_reviewer_id) == before


def test_request_list_excludes_other_workspaces(client, ws, login_user):
    login_user(ws["admin_a"])
    response = client.get("/change-requests/")

    assert response.status_code == 200
    assert [r["id"] for r in response.json()] == [ws["request_a"].id]


def test_assigning_reviewer_from_another_workspace_looks_like_nonexistent_user(client, ws, login_user):
    login_user(ws["junior_a"])

    def create_with_reviewer(reviewer_id):
        return client.post("/change-requests/", json={
            "title": "Cross-workspace", "description": "Should fail", "request_type": "access_change",
            "target_system": "srv", "environment": "development", "risk_level": RiskLevel.LOW.value,
            "assigned_reviewer_id": reviewer_id,
        })

    other_workspace = create_with_reviewer(ws["mid_b"].id)
    nonexistent = create_with_reviewer(999_999)

    assert other_workspace.status_code == 404
    assert other_workspace.json() == {"detail": "Assigned reviewer not found"}
    assert (other_workspace.status_code, other_workspace.json()) == (nonexistent.status_code, nonexistent.json())


# =============================================================================
# 5. An admin cannot see or manage users of another workspace (404)
# =============================================================================

def test_admin_user_list_contains_only_own_workspace(client, ws, login_user):
    login_user(ws["admin_a"])
    response = client.get("/users/")

    assert response.status_code == 200
    assert {u["email"] for u in response.json()} == {ws["admin_a"].email, ws["junior_a"].email, ws["mid_a"].email}


def test_reviewer_list_contains_only_own_workspace(client, ws, login_user):
    login_user(ws["junior_a"])
    response = client.get("/users/reviewers")

    assert response.status_code == 200
    assert {u["id"] for u in response.json()} <= {ws["mid_a"].id, ws["admin_a"].id}


@pytest.mark.parametrize("method,path,body", [
    ("get", "/users/{id}", None),
    ("get", "/users/{id}/details", None),
    ("patch", "/users/{id}/role", {"role_id": "lead"}),
    ("patch", "/users/{id}/deactivate", None),
    ("patch", "/users/{id}/reactivate", None),
])
def test_admin_cannot_view_modify_or_deactivate_user_of_another_workspace(
    client, db, roles, ws, login_user, method, path, body
):
    if body:
        body = {"role_id": roles[body["role_id"]].id}
    target = ws["junior_b"]

    login_user(ws["admin_a"])
    response = client.request(method.upper(), path.format(id=target.id), json=body)

    assert response.status_code == 404
    db.refresh(target)
    assert (target.role.name, target.is_active) == ("junior", True)


# =============================================================================
# 6. Audit log listing is per workspace
# =============================================================================

def test_audit_log_listing_contains_no_entries_from_another_workspace(client, db, ws, login_user):
    db.add(AuditLog(user_id=ws["junior_a"].id, workspace_id=ws["a"].id, action="A_EVENT", entity_type="user", entity_id=1))
    db.add(AuditLog(user_id=ws["junior_b"].id, workspace_id=ws["b"].id, action="B_EVENT", entity_type="user", entity_id=1))
    db.commit()

    login_user(ws["admin_a"])
    response = client.get("/audit-logs/")

    assert response.status_code == 200
    actions = {entry["action"] for entry in response.json()}
    assert "A_EVENT" in actions
    assert "B_EVENT" not in actions
    viewed = db.query(AuditLog).filter(AuditLog.action == "AUDIT_VIEWED").one()
    assert viewed.workspace_id == ws["a"].id


# =============================================================================
# 7. Escalation / delegation targets must be in the same workspace
# =============================================================================

@pytest.mark.parametrize("action,target", [("escalate", "lead_b"), ("delegate", "mid_b")])
def test_cannot_escalate_or_delegate_to_user_in_another_workspace(client, db, ws, login_user, action, target):
    login_user(ws["mid_a"])  # assigned reviewer of request_a
    response = client.post(
        f"/change-requests/{ws['request_a'].id}/{action}",
        json={"target_reviewer_id": ws[target].id},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Target reviewer not found or inactive"}
    db.refresh(ws["request_a"])
    assert ws["request_a"].assigned_reviewer_id == ws["mid_a"].id
    assert db.query(ReviewAction).count() == 0


# =============================================================================
# 8. Database level: composite FKs block cross-workspace references
# =============================================================================

@pytest.mark.parametrize("column,constraint", [
    ("assigned_reviewer_id", "fk_change_requests_workspace_id_assigned_reviewer_id_users"),
    ("created_by", "fk_change_requests_workspace_id_created_by_users"),
])
def test_database_rejects_change_request_referencing_user_of_another_workspace(app_db_engine, ws, column, constraint):
    values = {
        "created_by": ws["junior_a"].id,
        "assigned_reviewer_id": ws["mid_a"].id,
    }
    values[column] = ws["mid_b"].id  # user from workspace B on a workspace-A request

    with pytest.raises(IntegrityError) as exc, app_db_engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO change_requests (workspace_id, title, description, request_type, target_system, "
            "environment, risk_level, status, created_by, assigned_reviewer_id) "
            "VALUES (:ws, 'x', 'x', 'ACCESS_CHANGE', 'srv', 'DEV', 'LOW', 'DRAFT', "
            ":created_by, :assigned_reviewer_id)"
        ), {"ws": ws["a"].id, **values})

    assert isinstance(exc.value.orig, psycopg.errors.ForeignKeyViolation)
    assert constraint in str(exc.value.orig)


def test_database_accepts_change_request_with_users_of_its_own_workspace(app_db_engine, ws):
    with app_db_engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO change_requests (workspace_id, title, description, request_type, target_system, "
            "environment, risk_level, status, created_by, assigned_reviewer_id) "
            "VALUES (:ws, 'x', 'x', 'ACCESS_CHANGE', 'srv', 'DEV', 'LOW', 'DRAFT', :c, :r)"
        ), {"ws": ws["a"].id, "c": ws["junior_a"].id, "r": ws["mid_a"].id})


# =============================================================================
# 9. Database level: audit_logs is append-only for the application role
# =============================================================================

def test_tests_connect_as_application_role(app_db_engine):
    with app_db_engine.connect() as conn:
        assert conn.execute(text("SELECT current_user")).scalar_one() == "accessa_app"


@pytest.mark.parametrize("statement", [
    "UPDATE audit_logs SET details = 'tampered'",
    "DELETE FROM audit_logs",
    "TRUNCATE audit_logs",
])
def test_application_role_cannot_update_delete_or_truncate_audit_logs(app_db_engine, ws, statement):
    with app_db_engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO audit_logs (workspace_id, user_id, action, entity_type, entity_id) "
            "VALUES (:ws, :u, 'ORIGINAL', 'user', 1)"
        ), {"ws": ws["a"].id, "u": ws["junior_a"].id})

    with pytest.raises(ProgrammingError) as exc, app_db_engine.begin() as conn:
        conn.execute(text(statement))

    assert isinstance(exc.value.orig, psycopg.errors.InsufficientPrivilege)
    with app_db_engine.connect() as conn:
        assert conn.execute(text("SELECT details FROM audit_logs WHERE action = 'ORIGINAL'")).scalar_one() is None


def test_application_role_can_insert_and_read_audit_logs(app_db_engine, ws):
    with app_db_engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO audit_logs (workspace_id, action, entity_type, entity_id) VALUES (:ws, 'X', 'user', 1)"
        ), {"ws": ws["a"].id})
        assert conn.execute(text("SELECT count(*) FROM audit_logs WHERE action = 'X'")).scalar_one() == 1


# =============================================================================
# 10. Tokens are bound to their workspace
# =============================================================================

def test_token_whose_workspace_does_not_match_users_workspace_is_rejected(client, ws):
    token = create_access_token({"sub": str(ws["admin_a"].id), "workspace": str(ws["b"].public_id)})
    assert client.get("/users/me", headers=auth(token)).status_code == 401


def test_token_with_matching_workspace_is_accepted(client, ws):
    token = create_access_token({"sub": str(ws["admin_a"].id), "workspace": str(ws["a"].public_id)})
    assert client.get("/users/me", headers=auth(token)).status_code == 200


@pytest.mark.parametrize("claims", [
    {},  # no workspace claim
    {"workspace": "not-a-uuid"},
    {"workspace": "00000000-0000-4000-8000-000000000000"},  # well-formed, no such workspace
    {"workspace": 1},  # internal integer id is not accepted
])
def test_token_with_missing_malformed_or_unknown_workspace_is_rejected(client, ws, claims):
    token = create_access_token({"sub": str(ws["admin_a"].id), **claims})
    assert client.get("/users/me", headers=auth(token)).status_code == 401


def test_login_token_carries_workspace_public_id_not_internal_id(client, ws):
    response = login(client, ws["a"].slug, ws["junior_a"].email)

    assert response.status_code == 200, response.text
    payload = pyjwt.decode(response.json()["access_token"], SECRET_KEY, algorithms=[ALGORITHM])
    assert payload["workspace"] == str(ws["a"].public_id)
    assert "workspace_id" not in payload
    assert payload["sub"] == str(ws["junior_a"].id)


def test_workspace_public_id_is_random_uuid4(db, create_workspace):
    first = create_workspace(db, "One", "one-ws")
    second = create_workspace(db, "Two", "two-ws")
    assert first.public_id.version == 4
    assert first.public_id != second.public_id


# =============================================================================
# 11-13. Sign-up only ever creates a new workspace
# =============================================================================

def test_signup_creates_workspace_and_admin(client, db, roles):
    response = client.post("/auth/signup", json=SIGNUP)

    assert response.status_code == 200, response.text
    me = client.get("/users/me", headers=auth(response.json()["access_token"]))
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["role"]["name"] == "admin"
    assert body["workspace"]["slug"] == "platform-team"
    assert body["workspace"]["name"] == "Platform Team"
    assert "id" not in body["workspace"]

    owner = db.query(User).filter(User.email == SIGNUP["email"]).one()
    assert str(owner.workspace.public_id) == body["workspace"]["public_id"]
    actions = {log.action for log in db.query(AuditLog).filter(AuditLog.workspace_id == owner.workspace_id)}
    assert {"WORKSPACE_CREATED", "USER_CREATED"} <= actions


@pytest.mark.parametrize("slug", sorted(RESERVED_SLUGS))
def test_signup_rejects_reserved_slug(client, db, roles, slug):
    response = client.post("/auth/signup", json={**SIGNUP, "workspace_slug": slug})
    assert response.status_code == 400
    assert db.query(Workspace).count() == 1


@pytest.mark.parametrize("slug", ["ab", "x" * 33, "-start", "end-", "Has Space", "under_score", "ümlaut"])
def test_signup_rejects_invalid_slug_format(client, db, roles, slug):
    response = client.post("/auth/signup", json={**SIGNUP, "workspace_slug": slug})
    assert response.status_code == 400
    assert db.query(Workspace).count() == 1


def test_signup_rejects_short_password(client, db, roles):
    response = client.post("/auth/signup", json={**SIGNUP, "password": "short"})
    assert response.status_code == 400
    assert db.query(Workspace).count() == 1


def test_register_endpoint_no_longer_exists(client, db):
    response = client.post("/auth/register", json={"full_name": "X", "email": "x@test.com", "password": PASSWORD})
    assert response.status_code == 404


def test_signup_ignores_role_and_workspace_id_in_body(client, db, roles, ws):
    response = client.post("/auth/signup", json={
        **SIGNUP,
        "role": "junior", "role_id": roles["junior"].id,
        "workspace_id": ws["a"].id, "workspace_public_id": str(ws["a"].public_id),
    })

    assert response.status_code == 200, response.text
    owner = db.query(User).filter(User.email == SIGNUP["email"]).one()
    assert owner.role.name == "admin"
    assert owner.workspace_id not in (ws["a"].id, ws["b"].id)
    assert owner.workspace.slug == SIGNUP["workspace_slug"]


def test_signup_with_existing_slug_returns_409_and_leaves_that_workspace_untouched(client, db, ws):
    def snapshot():
        db.expire_all()
        return (
            ws["b"].name,
            sorted((u.email, u.role_id) for u in db.query(User).filter(User.workspace_id == ws["b"].id)),
        )

    before = snapshot()
    response = client.post("/auth/signup", json={**SIGNUP, "workspace_slug": ws["b"].slug, "email": "intruder@example.com"})

    assert response.status_code == 409
    assert snapshot() == before
    assert db.query(User).filter(User.email == "intruder@example.com").count() == 0


# =============================================================================
# 14. POST /users: only admins, always into the admin's own workspace
# =============================================================================

def test_create_user_without_token_returns_401(client, roles):
    response = client.post("/users/", json={
        "full_name": "X", "email": "x@example.com", "password": PASSWORD, "role_id": roles["junior"].id,
    })
    assert response.status_code == 401


def test_create_user_with_non_admin_token_returns_403(client, roles, ws, login_user):
    login_user(ws["mid_a"])
    response = client.post("/users/", json={
        "full_name": "X", "email": "x@example.com", "password": PASSWORD, "role_id": roles["junior"].id,
    })
    assert response.status_code == 403


def test_admin_created_user_lands_in_admins_workspace_even_if_body_names_another(client, db, roles, ws, login_user):
    login_user(ws["admin_a"])
    response = client.post("/users/", json={
        "full_name": "New Hire", "email": "newhire@example.com", "password": PASSWORD,
        "role_id": roles["mid"].id, "workspace_id": ws["b"].id, "workspace": str(ws["b"].public_id),
    })

    assert response.status_code == 200, response.text
    new_user = db.get(User, response.json()["id"])
    assert new_user.workspace_id == ws["a"].id
    assert new_user.created_by == ws["admin_a"].id
    assert new_user.must_change_password is True


def test_full_name_only_has_to_be_unique_within_a_workspace(client, roles, ws, login_user):
    login_user(ws["admin_a"])
    response = client.post("/users/", json={
        "full_name": ws["junior_b"].full_name, "email": "namesake@example.com",
        "password": PASSWORD, "role_id": roles["junior"].id,
    })
    assert response.status_code == 200, response.text


def test_extra_fields_cannot_move_user_or_request_to_another_workspace(client, db, ws, login_user):
    login_user(ws["junior_a"])
    client.put("/users/me", json={"full_name": "Renamed", "workspace_id": ws["b"].id, "role_id": 5})

    draft = db.get(ChangeRequest, ws["request_a"].id)
    draft.status = RequestStatus.DRAFT
    db.commit()
    client.patch(f"/change-requests/{draft.id}", json={
        "title": "Edited", "workspace_id": ws["b"].id, "created_by": ws["junior_b"].id, "status": "APPROVED",
    })

    db.expire_all()
    me = db.get(User, ws["junior_a"].id)
    assert (me.full_name, me.workspace_id, me.role.name) == ("Renamed", ws["a"].id, "junior")
    cr = db.get(ChangeRequest, draft.id)
    assert (cr.title, cr.workspace_id, cr.created_by, cr.status) == (
        "Edited", ws["a"].id, ws["junior_a"].id, RequestStatus.DRAFT,
    )


# =============================================================================
# 15. Admin-set initial passwords must be changed before anything else
# =============================================================================

def test_must_change_password_blocks_other_endpoints_until_changed(client, db, roles, ws, login_user):
    login_user(ws["admin_a"])
    created = client.post("/users/", json={
        "full_name": "Fresh User", "email": "fresh@example.com", "password": "Initial123", "role_id": roles["mid"].id,
    })
    assert created.status_code == 200, created.text

    use_real_tokens()
    response = login(client, ws["a"].slug, "fresh@example.com", "Initial123")
    assert response.status_code == 200
    assert response.json()["must_change_password"] is True
    token = response.json()["access_token"]

    me = client.get("/users/me", headers=auth(token))
    assert me.status_code == 200 and me.json()["must_change_password"] is True

    for method, path in [("get", "/change-requests/"), ("get", "/users/reviewers"), ("get", "/users/me/stats"),
                         ("put", "/users/me"), ("get", "/audit-logs/")]:
        blocked = client.request(method.upper(), path, headers=auth(token), json={"full_name": "x"} if method == "put" else None)
        assert blocked.status_code == 403, (path, blocked.text)
        assert blocked.json()["detail"]["code"] == "password_change_required"

    changed = client.put("/users/me/password", headers=auth(token), json={
        "current_password": "Initial123", "new_password": "NewPass123", "confirm_password": "NewPass123",
    })
    assert changed.status_code == 200, changed.text

    # Next comes MFA enrolment (SEC-14): still blocked, now with mfa_setup_required.
    after = client.get("/change-requests/", headers=auth(token))
    assert after.status_code == 403
    assert after.json()["detail"]["code"] == "mfa_setup_required"
    assert db.query(User).filter(User.email == "fresh@example.com").one().must_change_password is False


# =============================================================================
# 16. The two-admin rule counts only admins of the request's workspace
# =============================================================================

def test_two_admin_rule_counts_only_admins_of_request_workspace(client, db, roles, ws, create_user, seed_change_request, login_user):
    # Workspace A: one active admin (+ one inactive). Workspace B: two active admins.
    inactive_admin_a = create_user(db, role=roles["admin"], label="admin_a2", workspace=ws["a"])
    inactive_admin_a.is_active = False
    create_user(db, role=roles["admin"], label="admin_b2", workspace=ws["b"])
    db.commit()

    assert change_requests_api._get_active_admin_count(db, ws["a"].id) == 1
    assert change_requests_api._get_active_admin_count(db, ws["b"].id) == 2

    # The approver must be the assigned reviewer to reach the two-admin check.
    admin_request = seed_change_request(
        db, creator_id=ws["admin_a"].id, reviewer_id=inactive_admin_a.id, status=RequestStatus.PENDING_REVIEW
    )
    # With a global count (3 active admins) this would be allowed; per workspace it is not.
    allowed, reason = can_user_decide_request(
        inactive_admin_a, admin_request, change_requests_api._get_active_admin_count(db, admin_request.workspace_id)
    )
    assert (allowed, reason) == (False, "admin_insufficient_admins")

    # The approve endpoint counts the request's workspace, not the caller's.
    login_user(ws["admin_a"])
    with patch.object(change_requests_api, "_get_active_admin_count", wraps=change_requests_api._get_active_admin_count) as spy:
        client.post(f"/change-requests/{admin_request.id}/approve", json={"decision_comment": "x"})
    spy.assert_called_once()
    assert spy.call_args.args[1] == ws["a"].id


# =============================================================================
# Stats are per workspace
# =============================================================================

def test_stats_ignore_child_rows_attached_to_another_workspaces_requests(client, db, ws, login_user):
    # A comment row pointing a workspace-B user at a workspace-A request can only be
    # created by bypassing the API (child tables have no composite FK, see residual
    # risks). Even then it must not show up in that user's workspace-B statistics.
    db.add(Comment(change_request_id=ws["request_b"].id, user_id=ws["junior_b"].id, comment_text="own"))
    db.add(Comment(change_request_id=ws["request_a"].id, user_id=ws["junior_b"].id, comment_text="planted"))
    db.commit()

    login_user(ws["junior_b"])
    stats = client.get("/users/me/stats").json()

    assert stats["comments_written"] == 1
    assert stats["requests_created"] == 1
