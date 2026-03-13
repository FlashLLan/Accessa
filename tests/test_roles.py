def test_admin_can_list_roles(client, db, create_user, create_role, login_user):
    admin_role = create_role(db, "admin", level=10)
    lead_role = create_role(db, "lead", level=7)
    junior_role = create_role(db, "junior", level=1)

    admin = create_user(db, role=admin_role, label="admin")

    login_user(admin)

    response = client.get("/roles/")

    assert response.status_code == 200, response.text
    data = response.json()

    names = [role["name"] for role in data]
    assert "admin" in names
    assert "lead" in names
    assert "junior" in names


def test_regular_user_cannot_list_roles(client, db, create_user, create_role, login_user):
    admin_role = create_role(db, "admin", level=10)
    reviewer_role = create_role(db, "reviewer", level=5)

    create_user(db, role=admin_role, label="admin")
    user = create_user(db, role=reviewer_role, label="user")

    login_user(user)

    response = client.get("/roles/")

    assert response.status_code == 403
    assert response.json()["detail"] == "Only admin can view roles"