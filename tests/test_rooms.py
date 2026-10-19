from unittest.mock import patch

import pytest

from backend.core.security import create_access_token
from backend.models.audit_log import AuditLog
from backend.models.enums import RequestStatus, RiskLevel
from backend.models.room import Room, generate_room_public_id
from backend.models.user import User


def _fake_hash(password):
    return f"TESTHASH:{password}"


SIGNUP = {
    "room_name": "Platform Team",
    "full_name": "Room Owner",
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
def two_rooms(db, roles, create_room, create_user):
    """Room A is the default test room (id=1); room B is a second, unrelated tenant."""
    room_a = db.get(Room, 1)
    room_b = create_room(db, "Other Team", "200000000002")
    return {
        "room_a": room_a,
        "room_b": room_b,
        "admin_a": create_user(db, role=roles["admin"], label="admin_a", room=room_a),
        "junior_a": create_user(db, role=roles["junior"], label="junior_a", room=room_a),
        "admin_b": create_user(db, role=roles["admin"], label="admin_b", room=room_b),
        "junior_b": create_user(db, role=roles["junior"], label="junior_b", room=room_b),
        "mid_b": create_user(db, role=roles["mid"], label="mid_b", room=room_b),
    }


# --- room public id ------------------------------------------------------

def test_room_public_id_is_12_random_digits():
    ids = {generate_room_public_id() for _ in range(200)}
    assert len(ids) == 200
    for public_id in ids:
        assert len(public_id) == 12 and public_id.isdigit() and public_id[0] != "0"


# --- signup --------------------------------------------------------------

def test_signup_creates_room_and_sysadmin(client, db, roles):
    with patch("backend.api.auth.hash_password", side_effect=_fake_hash):
        response = client.post("/auth/signup", json=SIGNUP)

    assert response.status_code == 200, response.text
    token = response.json()["access_token"]

    me = client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["role"]["name"] == "admin"
    assert body["room"]["name"] == "Platform Team"
    assert len(body["room"]["public_id"]) == 12
    assert "id" not in body["room"]

    owner = db.query(User).filter(User.email == SIGNUP["email"]).one()
    assert owner.room.public_id == body["room"]["public_id"]
    actions = {log.action for log in db.query(AuditLog).filter(AuditLog.room_id == owner.room_id)}
    assert {"ROOM_CREATED", "USER_CREATED"} <= actions


def test_signup_rejects_existing_email(client, db, roles, create_user):
    existing = create_user(db, role=roles["junior"], label="taken")
    with patch("backend.api.auth.hash_password", side_effect=_fake_hash):
        response = client.post("/auth/signup", json={**SIGNUP, "email": existing.email})

    assert response.status_code == 400
    assert db.query(Room).count() == 1


def test_signup_rejects_short_password(client, db, roles):
    response = client.post("/auth/signup", json={**SIGNUP, "password": "short"})
    assert response.status_code == 400
    assert db.query(Room).count() == 1


def test_old_self_register_endpoint_is_gone(client, db, roles):
    response = client.post(
        "/auth/register",
        json={"full_name": "X", "email": "x@test.com", "password": "Password123"},
    )
    assert response.status_code in (404, 405)


# --- token binding -------------------------------------------------------

def test_token_without_room_claim_is_rejected(client, two_rooms):
    token = create_access_token({"sub": str(two_rooms["admin_a"].id)})
    response = client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_token_with_wrong_room_claim_is_rejected(client, two_rooms):
    token = create_access_token({"sub": str(two_rooms["admin_a"].id), "room": two_rooms["room_b"].public_id})
    response = client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


# --- user isolation ------------------------------------------------------

def test_admin_lists_only_users_of_own_room(client, two_rooms, login_user):
    login_user(two_rooms["admin_a"])
    response = client.get("/users/")

    assert response.status_code == 200
    emails = {u["email"] for u in response.json()}
    assert emails == {two_rooms["admin_a"].email, two_rooms["junior_a"].email}


@pytest.mark.parametrize("method,path", [
    ("get", "/users/{id}"),
    ("get", "/users/{id}/details"),
    ("patch", "/users/{id}/deactivate"),
    ("patch", "/users/{id}/reactivate"),
])
def test_admin_cannot_touch_users_of_another_room(client, two_rooms, login_user, method, path):
    login_user(two_rooms["admin_a"])
    response = getattr(client, method)(path.format(id=two_rooms["junior_b"].id))
    assert response.status_code == 404


def test_admin_cannot_change_role_of_user_in_another_room(client, db, roles, two_rooms, login_user):
    login_user(two_rooms["admin_a"])
    response = client.patch(
        f"/users/{two_rooms['junior_b'].id}/role", json={"role_id": roles["lead"].id}
    )
    assert response.status_code == 404
    db.refresh(two_rooms["junior_b"])
    assert two_rooms["junior_b"].role.name == "junior"


def test_created_user_joins_creators_room(client, db, roles, two_rooms, login_user):
    login_user(two_rooms["admin_b"])
    with patch("backend.api.users.hash_password", side_effect=_fake_hash):
        response = client.post("/users/", json={
            "full_name": "New Hire",
            "email": "newhire@test.com",
            "password": "Password123",
            "role_id": roles["mid"].id,
        })

    assert response.status_code == 200, response.text
    new_user = db.get(User, response.json()["id"])
    assert new_user.room_id == two_rooms["room_b"].id
    assert new_user.created_by == two_rooms["admin_b"].id


def test_full_name_only_has_to_be_unique_within_a_room(client, db, roles, two_rooms, login_user):
    login_user(two_rooms["admin_a"])
    with patch("backend.api.users.hash_password", side_effect=_fake_hash):
        response = client.post("/users/", json={
            "full_name": two_rooms["junior_b"].full_name,
            "email": "namesake@test.com",
            "password": "Password123",
            "role_id": roles["junior"].id,
        })
    assert response.status_code == 200, response.text


def test_reviewer_list_excludes_other_rooms(client, two_rooms, login_user):
    login_user(two_rooms["junior_a"])
    response = client.get("/users/reviewers")
    assert response.status_code == 200
    assert two_rooms["mid_b"].id not in {u["id"] for u in response.json()}


# --- change request isolation --------------------------------------------

@pytest.fixture
def request_in_room_b(db, two_rooms, seed_change_request):
    return seed_change_request(
        db,
        creator_id=two_rooms["junior_b"].id,
        reviewer_id=two_rooms["mid_b"].id,
        status=RequestStatus.PENDING_REVIEW,
    )


def test_admin_request_list_excludes_other_rooms(client, two_rooms, request_in_room_b, login_user):
    login_user(two_rooms["admin_a"])
    response = client.get("/change-requests/")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize("method,path,body", [
    ("get", "/change-requests/{id}", None),
    ("patch", "/change-requests/{id}", {"title": "hijacked"}),
    ("post", "/change-requests/{id}/approve", {"decision_comment": "ok"}),
    ("post", "/change-requests/{id}/reject", {"decision_comment": "no"}),
    ("post", "/change-requests/{id}/submit", None),
    ("post", "/change-requests/{id}/apply", None),
    ("get", "/change-requests/{id}/approvals", None),
    ("get", "/change-requests/{id}/comments", None),
    ("post", "/change-requests/{id}/comments", {"comment_text": "hi"}),
    ("get", "/change-requests/{id}/review-actions", None),
    ("get", "/change-requests/{id}/git-context", None),
    ("post", "/change-requests/{id}/git-context", {"branch_name": "x"}),
    ("get", "/change-requests/{id}/ai-review", None),
    ("post", "/change-requests/{id}/ai-review", None),
])
def test_admin_cannot_reach_request_of_another_room(
    client, two_rooms, request_in_room_b, login_user, method, path, body
):
    login_user(two_rooms["admin_a"])
    url = path.format(id=request_in_room_b.id)
    kwargs = {"json": body} if body is not None else {}
    response = getattr(client, method)(url, **kwargs)

    assert response.status_code == 404, (url, response.text)
    assert response.json()["detail"] == "Change request not found"


def test_cannot_assign_reviewer_from_another_room(client, two_rooms, login_user):
    login_user(two_rooms["junior_a"])
    response = client.post("/change-requests/", json={
        "title": "Cross-room",
        "description": "Should fail",
        "request_type": "access_change",
        "target_system": "srv",
        "environment": "development",
        "risk_level": RiskLevel.LOW.value,
        "assigned_reviewer_id": two_rooms["mid_b"].id,
    })
    assert response.status_code == 400
    assert response.json()["detail"] == "Assigned reviewer not found"


def test_cannot_delegate_to_user_in_another_room(
    client, db, roles, two_rooms, create_user, seed_change_request, login_user
):
    mid_a = create_user(db, role=roles["mid"], label="mid_a", room=two_rooms["room_a"])
    cr = seed_change_request(
        db,
        creator_id=two_rooms["junior_a"].id,
        reviewer_id=mid_a.id,
        status=RequestStatus.PENDING_REVIEW,
    )
    login_user(mid_a)
    response = client.post(
        f"/change-requests/{cr.id}/delegate",
        json={"target_reviewer_id": two_rooms["mid_b"].id},
    )
    assert response.status_code == 404


# --- audit log isolation -------------------------------------------------

def test_audit_log_only_shows_own_room(client, db, two_rooms, login_user):
    db.add(AuditLog(user_id=two_rooms["junior_a"].id, room_id=two_rooms["room_a"].id,
                    action="A_EVENT", entity_type="user", entity_id=1))
    db.add(AuditLog(user_id=two_rooms["junior_b"].id, room_id=two_rooms["room_b"].id,
                    action="B_EVENT", entity_type="user", entity_id=1))
    db.commit()

    login_user(two_rooms["admin_a"])
    response = client.get("/audit-logs/")

    assert response.status_code == 200
    actions = {entry["action"] for entry in response.json()}
    assert "A_EVENT" in actions
    assert "B_EVENT" not in actions

    viewed = db.query(AuditLog).filter(AuditLog.action == "AUDIT_VIEWED").one()
    assert viewed.room_id == two_rooms["room_a"].id
