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
            json={"email": "validuser@test.com", "password": "TestPass1!"},
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
            json={"email": "knownuser@test.com", "password": "WrongPassword"},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


def test_unknown_email_is_rejected(client, db):
    response = client.post(
        "/auth/login",
        json={"email": "nobody@test.com", "password": "AnyPassword"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"
