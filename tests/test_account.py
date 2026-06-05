from unittest.mock import patch


# --- security mock helpers ---------------------------------------------
# We avoid calling bcrypt in tests because passlib 1.7.x + bcrypt 4.x have
# a known incompatibility that raises ValueError on hashpw calls.
# Instead, patch the two functions imported into the users router.

_FAKE_PREFIX = "TESTHASH:"


def _fake_hash(password):
    return f"{_FAKE_PREFIX}{password}"


def _fake_verify(plain, hashed):
    return hashed == f"{_FAKE_PREFIX}{plain}"


def _make_user_with_password(db, role, label, password="password123"):
    """Create a user with a fake hash so password-change tests run without bcrypt."""
    from backend.models.user import User
    user = User(
        full_name=f"{label.capitalize()} User",
        email=f"{label}@test.com",
        hashed_password=_fake_hash(password),
        role_id=role.id,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


import pytest


@pytest.fixture
def patched_security():
    """Replace bcrypt calls in the users router with simple string operations."""
    with patch("backend.api.users.hash_password", side_effect=_fake_hash), \
         patch("backend.api.users.verify_password", side_effect=_fake_verify):
        yield


# --- GET /users/me -----------------------------------------------------

def test_get_me_returns_current_user(client, db, create_user, create_role, login_user):
    role = create_role(db, "mid", level=3)
    user = create_user(db, role=role, label="user")
    login_user(user)

    response = client.get("/users/me")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == user.id
    assert data["email"] == user.email


def test_unauthenticated_cannot_access_me(client, db):
    response = client.get("/users/me")
    # HTTPBearer returns 401 when no Authorization header is present
    assert response.status_code in (401, 403)


# --- PUT /users/me -----------------------------------------------------

def test_user_can_update_own_full_name(client, db, create_user, create_role, login_user):
    role = create_role(db, "mid", level=3)
    user = create_user(db, role=role, label="original")
    login_user(user)

    response = client.put("/users/me", json={"full_name": "Updated Name"})

    assert response.status_code == 200
    data = response.json()
    assert data["full_name"] == "Updated Name"
    assert data["id"] == user.id


def test_user_cannot_update_role_via_profile_endpoint(client, db, create_user, create_role, login_user):
    role = create_role(db, "mid", level=3)
    user = create_user(db, role=role, label="user")
    login_user(user)

    # role_id in body is silently ignored — only full_name is accepted
    response = client.put("/users/me", json={"full_name": "New Name", "role_id": 999})

    assert response.status_code == 200
    data = response.json()
    assert data["role"]["name"] == "mid"
    assert data["full_name"] == "New Name"


def test_user_cannot_update_active_status_via_profile_endpoint(client, db, create_user, create_role, login_user):
    role = create_role(db, "mid", level=3)
    user = create_user(db, role=role, label="user")
    login_user(user)

    # is_active in body is silently ignored — only full_name is accepted
    response = client.put("/users/me", json={"full_name": "New Name", "is_active": False})

    assert response.status_code == 200
    data = response.json()
    assert data["is_active"] is True


def test_update_me_rejects_empty_full_name(client, db, create_user, create_role, login_user):
    role = create_role(db, "mid", level=3)
    user = create_user(db, role=role, label="user")
    login_user(user)

    response = client.put("/users/me", json={"full_name": "   "})

    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


# --- PUT /users/me/password --------------------------------------------

def test_password_change_succeeds_with_correct_current_password(
    client, db, create_role, login_user, patched_security
):
    role = create_role(db, "mid", level=3)
    user = _make_user_with_password(db, role, "passuser", password="OldPass1!")
    login_user(user)

    response = client.put(
        "/users/me/password",
        json={
            "current_password": "OldPass1!",
            "new_password": "NewPass2@",
            "confirm_password": "NewPass2@",
        },
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Password changed successfully."


def test_password_change_fails_with_wrong_current_password(
    client, db, create_role, login_user, patched_security
):
    role = create_role(db, "mid", level=3)
    user = _make_user_with_password(db, role, "passuser2", password="OldPass1!")
    login_user(user)

    response = client.put(
        "/users/me/password",
        json={
            "current_password": "WrongPassword",
            "new_password": "NewPass2@",
            "confirm_password": "NewPass2@",
        },
    )

    assert response.status_code == 400
    assert "incorrect" in response.json()["detail"].lower()


def test_password_change_fails_when_confirmation_does_not_match(
    client, db, create_role, login_user, patched_security
):
    role = create_role(db, "mid", level=3)
    user = _make_user_with_password(db, role, "passuser3", password="OldPass1!")
    login_user(user)

    response = client.put(
        "/users/me/password",
        json={
            "current_password": "OldPass1!",
            "new_password": "NewPass2@",
            "confirm_password": "MismatchXX",
        },
    )

    assert response.status_code == 400
    assert "match" in response.json()["detail"].lower()


def test_password_change_fails_when_new_password_too_short(
    client, db, create_role, login_user, patched_security
):
    role = create_role(db, "mid", level=3)
    user = _make_user_with_password(db, role, "passuser4", password="OldPass1!")
    login_user(user)

    response = client.put(
        "/users/me/password",
        json={
            "current_password": "OldPass1!",
            "new_password": "short",
            "confirm_password": "short",
        },
    )

    assert response.status_code == 400
    assert "8" in response.json()["detail"]


def test_password_is_stored_hashed_not_plain(client, db, create_role, login_user, patched_security):
    role = create_role(db, "mid", level=3)
    user = _make_user_with_password(db, role, "hashcheck", password="OldPass1!")
    login_user(user)

    client.put(
        "/users/me/password",
        json={
            "current_password": "OldPass1!",
            "new_password": "BrandNew9$",
            "confirm_password": "BrandNew9$",
        },
    )

    db.refresh(user)
    # The stored value must not be the plain-text password
    assert user.hashed_password != "BrandNew9$"
    # The mock stores a transformed value, confirming the hash function was called
    assert user.hashed_password == _fake_hash("BrandNew9$")


# --- GET /users/me/stats -----------------------------------------------

def test_stats_returns_data_for_current_user(client, db, create_user, create_role, login_user):
    role = create_role(db, "mid", level=3)
    user = create_user(db, role=role, label="statsuser")
    login_user(user)

    response = client.get("/users/me/stats")

    assert response.status_code == 200
    data = response.json()
    assert "requests_created" in data
    assert "pending_requests" in data
    assert "approved_requests" in data
    assert "rejected_requests" in data
    assert "comments_written" in data
    assert "requests_reviewed" in data
    assert "approved_decisions" in data
    assert "rejected_decisions" in data
    assert "delegations_performed" in data
    assert "escalations_performed" in data


def test_non_admin_stats_have_null_admin_fields(client, db, create_user, create_role, login_user):
    role = create_role(db, "mid", level=3)
    user = create_user(db, role=role, label="nonadmin")
    login_user(user)

    response = client.get("/users/me/stats")

    assert response.status_code == 200
    data = response.json()
    assert data["users_created"] is None
    assert data["users_deactivated"] is None
    assert data["role_changes_performed"] is None
    assert data["admin_actions_logged"] is None


def test_admin_stats_include_admin_fields(client, db, create_user, create_role, login_user):
    admin_role = create_role(db, "admin", level=10)
    admin = create_user(db, role=admin_role, label="adminuser")
    login_user(admin)

    response = client.get("/users/me/stats")

    assert response.status_code == 200
    data = response.json()
    assert data["users_created"] is not None
    assert data["users_deactivated"] is not None
    assert data["role_changes_performed"] is not None
    assert data["admin_actions_logged"] is not None


def test_stats_counts_requests_created_by_user(
    client, db, create_user, create_role, login_user, seed_change_request
):
    role = create_role(db, "mid", level=3)
    reviewer_role = create_role(db, "senior", level=5)

    user = create_user(db, role=role, label="creator")
    reviewer = create_user(db, role=reviewer_role, label="reviewer")

    seed_change_request(db, creator_id=user.id, reviewer_id=reviewer.id)
    seed_change_request(db, creator_id=user.id, reviewer_id=reviewer.id)

    login_user(user)

    response = client.get("/users/me/stats")

    assert response.status_code == 200
    assert response.json()["requests_created"] == 2


def test_stats_does_not_expose_other_users_data(
    client, db, create_user, create_role, login_user, seed_change_request
):
    role = create_role(db, "mid", level=3)

    user1 = create_user(db, role=role, label="user1")
    user2 = create_user(db, role=role, label="user2")

    seed_change_request(db, creator_id=user1.id, reviewer_id=user2.id)
    seed_change_request(db, creator_id=user1.id, reviewer_id=user2.id)

    login_user(user2)

    response = client.get("/users/me/stats")

    assert response.status_code == 200
    assert response.json()["requests_created"] == 0


# --- inactive user cannot access account endpoints --------------------

def test_inactive_user_cannot_access_me(client, db, create_user, create_role):
    from backend.core.security import create_access_token
    from backend.main import app
    from database.db import get_db

    role = create_role(db, "mid", level=3)
    user = create_user(db, role=role, label="inactive")
    user.is_active = False
    db.commit()
    db.refresh(user)

    # Issue a real JWT for the inactive user, then call the endpoint
    # without overriding get_current_user so the real dependency runs.
    token = create_access_token({"sub": str(user.id)})

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    response = client.get("/users/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
    assert "inactive" in response.json()["detail"].lower()
