from backend.main import app
from backend.core.dependencies import get_current_user


def test_admin_can_list_users(client, db, create_user, create_role, login_user):
    admin_role = create_role(db, "admin", level=10)
    user_role = create_role(db, "mid", level=5)

    admin = create_user(db, role=admin_role, label="admin")
    create_user(db, role=user_role, label="user1")
    create_user(db, role=user_role, label="user2")

    login_user(admin)

    response = client.get("/users/")

    assert response.status_code == 200
    assert len(response.json()) >= 3


def test_regular_user_cannot_list_users(client, db, create_user, create_role, login_user):
    role = create_role(db, "mid", level=5)
    user = create_user(db, role=role, label="user")

    login_user(user)

    response = client.get("/users/")

    assert response.status_code == 403


def test_user_can_access_me_endpoint(client, db, create_user, create_role, login_user):
    role = create_role(db, "mid", level=5)
    user = create_user(db, role=role, label="user")

    login_user(user)

    response = client.get("/users/me")

    assert response.status_code == 200
    assert response.json()["id"] == user.id


def test_user_can_access_own_profile(client, db, create_user, create_role, login_user):
    role = create_role(db, "mid", level=5)
    user = create_user(db, role=role, label="user")

    login_user(user)

    response = client.get(f"/users/{user.id}")

    assert response.status_code == 200
    assert response.json()["id"] == user.id


def test_user_cannot_access_other_user_profile(client, db, create_user, create_role, login_user):
    role = create_role(db, "mid", level=5)

    user1 = create_user(db, role=role, label="user1")
    user2 = create_user(db, role=role, label="user2")

    login_user(user1)

    response = client.get(f"/users/{user2.id}")

    assert response.status_code == 403


def test_reviewer_list_endpoint(client, db, create_user, create_role, login_user):
    admin_role = create_role(db, "admin", level=10)
    senior_role = create_role(db, "senior", level=5)

    admin = create_user(db, role=admin_role, label="admin")
    reviewer = create_user(db, role=senior_role, label="reviewer")

    login_user(admin)

    response = client.get("/users/reviewers")

    assert response.status_code == 200

    data = response.json()
    ids = [u["id"] for u in data]

    assert admin.id in ids
    assert reviewer.id in ids


def test_admin_can_deactivate_another_user(client, db, create_user, create_role, login_user):
    admin_role = create_role(db, "admin", level=10)
    user_role = create_role(db, "senior", level=5)

    admin = create_user(db, role=admin_role, label="admin")
    target_user = create_user(db, role=user_role, label="target")

    login_user(admin)

    response = client.patch(f"/users/{target_user.id}/deactivate")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["id"] == target_user.id
    assert data["is_active"] is False


def test_admin_can_reactivate_inactive_user(client, db, create_user, create_role, login_user):
    admin_role = create_role(db, "admin", level=10)
    user_role = create_role(db, "senior", level=5)

    admin = create_user(db, role=admin_role, label="admin")
    target_user = create_user(db, role=user_role, label="target")
    target_user.is_active = False
    db.commit()
    db.refresh(target_user)

    login_user(admin)

    response = client.patch(f"/users/{target_user.id}/reactivate")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["id"] == target_user.id
    assert data["is_active"] is True


def test_regular_user_cannot_deactivate_user(client, db, create_user, create_role, login_user):
    role = create_role(db, "mid", level=3)

    user1 = create_user(db, role=role, label="user1")
    user2 = create_user(db, role=role, label="user2")

    login_user(user1)

    response = client.patch(f"/users/{user2.id}/deactivate")

    assert response.status_code == 403
    assert response.json()["detail"] == "Only admin can deactivate users"


def test_admin_cannot_deactivate_self(client, db, create_user, create_role, login_user):
    admin_role = create_role(db, "admin", level=10)
    admin = create_user(db, role=admin_role, label="admin")

    login_user(admin)

    response = client.patch(f"/users/{admin.id}/deactivate")

    assert response.status_code == 400
    assert response.json()["detail"] == "You cannot deactivate your own account"


def test_cannot_deactivate_already_inactive_user(client, db, create_user, create_role, login_user):
    admin_role = create_role(db, "admin", level=10)
    user_role = create_role(db, "senior", level=5)

    admin = create_user(db, role=admin_role, label="admin")
    target_user = create_user(db, role=user_role, label="target")
    target_user.is_active = False
    db.commit()
    db.refresh(target_user)

    login_user(admin)

    response = client.patch(f"/users/{target_user.id}/deactivate")

    assert response.status_code == 400
    assert response.json()["detail"] == "User is already inactive"


def test_cannot_reactivate_already_active_user(client, db, create_user, create_role, login_user):
    admin_role = create_role(db, "admin", level=10)
    user_role = create_role(db, "senior", level=5)

    admin = create_user(db, role=admin_role, label="admin")
    target_user = create_user(db, role=user_role, label="target")

    login_user(admin)

    response = client.patch(f"/users/{target_user.id}/reactivate")

    assert response.status_code == 400
    assert response.json()["detail"] == "User is already active"