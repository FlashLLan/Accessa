from backend.models.audit_log import AuditLog
from backend.models.enums import RequestStatus

def test_creator_can_add_comment_to_request(client, db, create_user, create_role, login_user, seed_change_request):
    reviewer_role = create_role(db, "reviewer", level=5)
    creator_role = reviewer_role

    creator = create_user(db, role=creator_role, label="creator")
    reviewer = create_user(db, role=reviewer_role, label="reviewer")

    req = seed_change_request(
        db,
        creator_id=creator.id,
        reviewer_id=reviewer.id,
    )

    login_user(creator)

    response = client.post(
        f"/change-requests/{req.id}/comments",
        json={"comment_text": "Please review firewall impact"},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["comment_text"] == "Please review firewall impact"
    assert data["user"]["id"] == creator.id


def test_reviewer_can_list_comments_on_request(client, db, create_user, create_role, login_user, seed_change_request):
    reviewer_role = create_role(db, "reviewer", level=5)
    creator_role = reviewer_role

    creator = create_user(db, role=creator_role, label="creator")
    reviewer = create_user(db, role=reviewer_role, label="reviewer")

    req = seed_change_request(
        db,
        creator_id=creator.id,
        reviewer_id=reviewer.id,
    )

    login_user(creator)
    client.post(
        f"/change-requests/{req.id}/comments",
        json={"comment_text": "Initial note"},
    )

    login_user(reviewer)
    response = client.get(f"/change-requests/{req.id}/comments")

    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data) == 1
    assert data[0]["comment_text"] == "Initial note"


def test_unrelated_user_cannot_view_or_add_comments(client, db, create_user, create_role, login_user, seed_change_request):
    role = create_role(db, "reviewer", level=5)

    creator = create_user(db, role=role, label="creator")
    reviewer = create_user(db, role=role, label="reviewer")
    stranger = create_user(db, role=role, label="stranger")

    req = seed_change_request(
        db,
        creator_id=creator.id,
        reviewer_id=reviewer.id,
    )

    login_user(stranger)

    get_response = client.get(f"/change-requests/{req.id}/comments")
    post_response = client.post(
        f"/change-requests/{req.id}/comments",
        json={"comment_text": "I should not be here"},
    )

    assert get_response.status_code == 403
    assert post_response.status_code == 403


def test_admin_can_view_audit_logs(client, db, create_user, create_role, login_user):
    admin_role = create_role(db, "admin", level=10)
    user_role = create_role(db, "reviewer", level=5)

    admin = create_user(db, role=admin_role, label="admin")
    user = create_user(db, role=user_role, label="user")

    log = AuditLog(
        user_id=user.id,
        action="create_change_request",
        entity_type="change_request",
        entity_id=1,
        details="Created request in test",
    )
    db.add(log)
    db.commit()

    login_user(admin)

    response = client.get("/audit-logs/")

    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data) == 1
    assert data[0]["action"] == "create_change_request"
    assert data[0]["user"]["id"] == user.id


def test_regular_user_cannot_view_audit_logs(client, db, create_user, create_role, login_user):
    role = create_role(db, "reviewer", level=5)
    user = create_user(db, role=role, label="user")

    login_user(user)

    response = client.get("/audit-logs/")

    assert response.status_code == 403
    assert response.json()["detail"] == "Only admin can view audit logs"


def test_high_risk_request_requires_high_level_reviewer_on_create(client, db, create_user, create_role, login_user):
    reviewer_role = create_role(db, "reviewer", level=5)
    creator_role = reviewer_role

    creator = create_user(db, role=creator_role, label="creator")
    low_reviewer = create_user(db, role=reviewer_role, label="lowreviewer")

    login_user(creator)

    response = client.post(
        "/change-requests/",
        json={
            "title": "Critical production firewall change",
            "description": "High-risk network modification",
            "request_type": "configuration_change",
            "target_system": "fw-router",
            "environment": "production",
            "risk_level": "high",
            "assigned_reviewer_id": low_reviewer.id,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "High-risk requests must be assigned to an admin or high-level reviewer"


def test_high_risk_request_allows_admin_reviewer_on_create(client, db, create_user, create_role, login_user):
    creator_role = create_role(db, "reviewer", level=5)
    admin_role = create_role(db, "admin", level=10)

    creator = create_user(db, role=creator_role, label="creator")
    admin = create_user(db, role=admin_role, label="admin")

    login_user(creator)

    response = client.post(
        "/change-requests/",
        json={
            "title": "Critical production firewall change",
            "description": "High-risk network modification",
            "request_type": "configuration_change",
            "target_system": "fw-router",
            "environment": "production",
            "risk_level": "high",
            "assigned_reviewer_id": admin.id,
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["risk_level"] == "high"


def test_update_to_high_risk_fails_with_low_level_reviewer(client, db, create_user, create_role, login_user, seed_change_request):
    reviewer_role = create_role(db, "reviewer", level=5)
    creator_role = reviewer_role

    creator = create_user(db, role=creator_role, label="creator")
    reviewer = create_user(db, role=reviewer_role, label="reviewer")

    req = seed_change_request(
        db,
        creator_id=creator.id,
        reviewer_id=reviewer.id,
        status=RequestStatus.DRAFT,
    )

    login_user(creator)

    response = client.patch(
        f"/change-requests/{req.id}",
        json={"risk_level": "high"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "High-risk requests must be assigned to an admin or high-level reviewer"