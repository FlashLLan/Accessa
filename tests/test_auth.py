from unittest.mock import patch
from backend.models.user import User

_FAKE_PREFIX = "TESTHASH:"


def _fake_hash(password):
    return f"{_FAKE_PREFIX}{password}"


def _fake_verify(plain, hashed):
    return hashed == f"{_FAKE_PREFIX}{plain}"


def _make_user_with_password(db, role, label, password="password123"):
    user = User(
        full_name=f"{label.capitalize()} User",
        email=f"{label}@test.com",
        hashed_password=_fake_hash(password),
        role_id=role.id,
        workspace_id=1,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_valid_login_returns_token(client, db, create_role):
    role = create_role(db, "junior", level=1)
    _make_user_with_password(db, role, "validuser", password="TestPass1!")

    with patch("backend.api.auth.verify_password", side_effect=_fake_verify):
        response = client.post(
            "/auth/login",
            json={"workspace_slug": "default-test", "email": "validuser@test.com", "password": "TestPass1!"},
        )

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_invalid_password_is_rejected(client, db, create_role):
    role = create_role(db, "junior", level=1)
    _make_user_with_password(db, role, "knownuser", password="TestPass1!")

    with patch("backend.api.auth.verify_password", side_effect=_fake_verify):
        response = client.post(
            "/auth/login",
            json={"workspace_slug": "default-test", "email": "knownuser@test.com", "password": "WrongPassword"},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


def test_unknown_email_is_rejected(client, db):
    response = client.post(
        "/auth/login",
        json={"workspace_slug": "default-test", "email": "nobody@test.com", "password": "AnyPassword"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


def test_valid_admin_login_returns_token(client, db, create_role):
    role = create_role(db, "admin", level=5)
    _make_user_with_password(db, role, "adminuser", password="AdminPass1!")

    with patch("backend.api.auth.verify_password", side_effect=_fake_verify):
        response = client.post(
            "/auth/login",
            json={"workspace_slug": "default-test", "email": "adminuser@test.com", "password": "AdminPass1!"},
        )

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_valid_lead_login_returns_token(client, db, create_role):
    role = create_role(db, "lead", level=4)
    _make_user_with_password(db, role, "leaduser", password="LeadPass1!")

    with patch("backend.api.auth.verify_password", side_effect=_fake_verify):
        response = client.post(
            "/auth/login",
            json={"workspace_slug": "default-test", "email": "leaduser@test.com", "password": "LeadPass1!"},
        )

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_inactive_user_login_is_rejected(client, db, create_role):
    role = create_role(db, "junior", level=1)
    user = _make_user_with_password(db, role, "inactiveuser", password="TestPass1!")
    user.is_active = False
    db.commit()

    with patch("backend.api.auth.verify_password", side_effect=_fake_verify):
        response = client.post(
            "/auth/login",
            json={"workspace_slug": "default-test", "email": "inactiveuser@test.com", "password": "TestPass1!"},
        )

    # Deliberate change: an inactive account gets the same generic 401 as any other
    # failure, so the login endpoint does not reveal which accounts exist or are disabled.
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


def test_protected_endpoint_without_token_is_rejected(client, db):
    response = client.get("/users/me")

    assert response.status_code == 401


def test_protected_endpoint_with_invalid_token_is_rejected(client, db):
    response = client.get(
        "/users/me",
        headers={"Authorization": "Bearer this.is.not.a.valid.token"},
    )

    assert response.status_code == 401
