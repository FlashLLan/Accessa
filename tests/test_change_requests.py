from datetime import datetime
from itertools import count

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Boolean, DateTime, Enum as SAEnum, Integer, String, Text, create_engine, insert
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.core.dependencies import get_current_user
from backend.models.change_request import ChangeRequest
from backend.models.user import User
from backend.models.role import Role
from backend.models.approval import Approval
from backend.models.enums import (
    RequestStatus,
    RequestType,
    EnvironmentType,
    RiskLevel,
    ApprovalDecision,
)
from database.db import Base, get_db

# ---- test db setup ----

TEST_DB_URL = "sqlite://"

engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ---- generic seed helpers ----

_unique = count(1)


def _guess_required_value(column_name, column_type, *, label="x", role_id=None):
    idx = next(_unique)
    name = column_name.lower()

    if role_id is not None and name == "role_id":
        return role_id

    if isinstance(column_type, Boolean):
        return True

    if isinstance(column_type, DateTime):
        return datetime.utcnow()

    if isinstance(column_type, Integer):
        # fallback for non-null ints that are not PK/autoincrement
        return 1

    if isinstance(column_type, SAEnum):
        enum_class = getattr(column_type, "enum_class", None)
        if enum_class is not None:
            return next(iter(enum_class))
        return column_type.enums[0]

    if "email" in name:
        return f"{label}{idx}@example.com"
    if "username" in name:
        return f"{label}_{idx}"
    if "full_name" in name or name == "name":
        return f"{label.capitalize()} {idx}"
    if "password" in name or "hash" in name:
        return "hashed_password_for_tests"
    if "description" in name:
        return f"{label} description {idx}"
    if isinstance(column_type, (String, Text)):
        return f"{label}_{column_name}_{idx}"

    return f"{label}_{idx}"


def _insert_row(db, model, *, overrides=None, label="x"):
    overrides = overrides or {}
    table = model.__table__

    values = {}
    for column in table.columns:
        if column.name in overrides:
            values[column.name] = overrides[column.name]
            continue

        if column.primary_key and column.autoincrement:
            continue

        if column.default is not None or column.server_default is not None:
            continue

        if column.nullable:
            continue

        values[column.name] = _guess_required_value(
            column.name,
            column.type,
            label=label,
            role_id=overrides.get("role_id"),
        )

    result = db.execute(insert(table).values(**values))
    db.commit()

    pk = result.inserted_primary_key[0]
    return db.get(model, pk)


def create_role(db, name, level=1):
    return _insert_row(db, Role, overrides={"name": name, "level": level}, label=name)


def create_user(db, *, role, label):
    user = _insert_row(
        db,
        User,
        overrides={"role_id": role.id},
        label=label,
    )
    db.refresh(user)
    return user


def login_as(user):
    app.dependency_overrides[get_current_user] = lambda: user


def request_payload(reviewer_id):
    return {
        "title": "Firewall change",
        "description": "Open required port for new service",
        "request_type": next(iter(RequestType)).value,
        "target_system": "fw-router",
        "environment": next(iter(EnvironmentType)).value,
        "risk_level": next(iter(RiskLevel)).value,
        "assigned_reviewer_id": reviewer_id,
    }


def seed_change_request(
    db,
    *,
    creator_id,
    reviewer_id,
    status=RequestStatus.DRAFT,
    title="Seeded request",
):
    req = ChangeRequest(
        title=title,
        description="Seeded description",
        request_type=next(iter(RequestType)),
        target_system="server-1",
        environment=next(iter(EnvironmentType)),
        risk_level=next(iter(RiskLevel)),
        status=status,
        created_by=creator_id,
        assigned_reviewer_id=reviewer_id,
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return req


# ---- tests ----

def test_create_change_request_success(client, db):
    admin_role = create_role(db, "admin")
    reviewer_role = create_role(db, "reviewer")
    creator = create_user(db, role=admin_role, label="creator")
    reviewer = create_user(db, role=reviewer_role, label="reviewer")

    login_as(creator)

    response = client.post("/change-requests/", json=request_payload(reviewer.id))

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["title"] == "Firewall change"
    assert data["assigned_reviewer"]["id"] == reviewer.id
    assert data["creator"]["id"] == creator.id
    assert data["status"] == RequestStatus.DRAFT.value


def test_create_change_request_rejects_self_reviewer(client, db):
    admin_role = create_role(db, "admin")
    creator = create_user(db, role=admin_role, label="sameuser")

    login_as(creator)

    payload = request_payload(creator.id)
    response = client.post("/change-requests/", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"] == "You cannot assign yourself as reviewer"


def test_list_change_requests_admin_sees_all(client, db):
    admin_role = create_role(db, "admin")
    reviewer_role = create_role(db, "reviewer")

    admin = create_user(db, role=admin_role, label="admin")
    creator1 = create_user(db, role=admin_role, label="creator1")
    creator2 = create_user(db, role=admin_role, label="creator2")
    reviewer = create_user(db, role=reviewer_role, label="reviewer")

    seed_change_request(db, creator_id=creator1.id, reviewer_id=reviewer.id, title="Req 1")
    seed_change_request(db, creator_id=creator2.id, reviewer_id=reviewer.id, title="Req 2")

    login_as(admin)

    response = client.get("/change-requests/")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2


def test_list_change_requests_regular_user_sees_only_related(client, db):
    admin_role = create_role(db, "admin", level=10)
    reviewer_role = create_role(db, "reviewer", level=5)

    creator = create_user(db, role=reviewer_role, label="creator")
    reviewer = create_user(db, role=reviewer_role, label="reviewer")
    stranger = create_user(db, role=reviewer_role, label="stranger")
    other_creator = create_user(db, role=reviewer_role, label="othercreator")

    related = seed_change_request(
        db,
        creator_id=creator.id,
        reviewer_id=reviewer.id,
        title="Visible request",
    )
    seed_change_request(
        db,
        creator_id=other_creator.id,
        reviewer_id=stranger.id,
        title="Hidden request",
    )

    login_as(creator)

    response = client.get("/change-requests/")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == related.id


def test_get_change_request_denies_unrelated_user(client, db):
    admin_role = create_role(db, "admin")
    reviewer_role = create_role(db, "reviewer")

    creator = create_user(db, role=admin_role, label="creator")
    reviewer = create_user(db, role=reviewer_role, label="reviewer")
    stranger = create_user(db, role=reviewer_role, label="stranger")

    req = seed_change_request(
        db,
        creator_id=creator.id,
        reviewer_id=reviewer.id,
        title="Restricted request",
    )

    login_as(stranger)

    response = client.get(f"/change-requests/{req.id}")

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"


def test_submit_change_request_moves_draft_to_pending_review(client, db):
    admin_role = create_role(db, "admin")
    reviewer_role = create_role(db, "reviewer")

    creator = create_user(db, role=admin_role, label="creator")
    reviewer = create_user(db, role=reviewer_role, label="reviewer")

    req = seed_change_request(
        db,
        creator_id=creator.id,
        reviewer_id=reviewer.id,
        status=RequestStatus.DRAFT,
    )

    login_as(creator)

    response = client.post(f"/change-requests/{req.id}/submit")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == RequestStatus.PENDING_REVIEW.value


def test_update_change_request_allows_creator_to_edit_draft(client, db):
    admin_role = create_role(db, "admin")
    reviewer_role = create_role(db, "reviewer")

    creator = create_user(db, role=admin_role, label="creator")
    reviewer = create_user(db, role=reviewer_role, label="reviewer")

    req = seed_change_request(
        db,
        creator_id=creator.id,
        reviewer_id=reviewer.id,
        status=RequestStatus.DRAFT,
        title="Old title",
    )

    login_as(creator)

    response = client.patch(
        f"/change-requests/{req.id}",
        json={"title": "Updated title"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["title"] == "Updated title"


def test_update_change_request_blocks_edit_when_pending_review(client, db):
    admin_role = create_role(db, "admin")
    reviewer_role = create_role(db, "reviewer")

    creator = create_user(db, role=admin_role, label="creator")
    reviewer = create_user(db, role=reviewer_role, label="reviewer")

    req = seed_change_request(
        db,
        creator_id=creator.id,
        reviewer_id=reviewer.id,
        status=RequestStatus.PENDING_REVIEW,
    )

    login_as(creator)

    response = client.patch(
        f"/change-requests/{req.id}",
        json={"title": "Should fail"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Only draft or rejected requests can be edited"


def test_approve_change_request_by_assigned_reviewer(client, db):
    admin_role = create_role(db, "admin")
    reviewer_role = create_role(db, "reviewer")

    creator = create_user(db, role=admin_role, label="creator")
    reviewer = create_user(db, role=reviewer_role, label="reviewer")

    req = seed_change_request(
        db,
        creator_id=creator.id,
        reviewer_id=reviewer.id,
        status=RequestStatus.PENDING_REVIEW,
    )

    login_as(reviewer)

    response = client.post(
        f"/change-requests/{req.id}/approve",
        json={"decision_comment": "Looks good"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == RequestStatus.APPROVED.value

    approval = db.query(Approval).filter(Approval.change_request_id == req.id).first()
    assert approval is not None
    assert approval.reviewer_id == reviewer.id
    assert approval.decision == ApprovalDecision.APPROVED


def test_reject_change_request_by_assigned_reviewer(client, db):
    admin_role = create_role(db, "admin")
    reviewer_role = create_role(db, "reviewer")

    creator = create_user(db, role=admin_role, label="creator")
    reviewer = create_user(db, role=reviewer_role, label="reviewer")

    req = seed_change_request(
        db,
        creator_id=creator.id,
        reviewer_id=reviewer.id,
        status=RequestStatus.PENDING_REVIEW,
    )

    login_as(reviewer)

    response = client.post(
        f"/change-requests/{req.id}/reject",
        json={"decision_comment": "Too risky"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == RequestStatus.REJECTED.value

    approval = db.query(Approval).filter(Approval.change_request_id == req.id).first()
    assert approval is not None
    assert approval.reviewer_id == reviewer.id
    assert approval.decision == ApprovalDecision.REJECTED


def test_get_approval_history_returns_entries(client, db):
    admin_role = create_role(db, "admin")
    reviewer_role = create_role(db, "reviewer")

    creator = create_user(db, role=admin_role, label="creator")
    reviewer = create_user(db, role=reviewer_role, label="reviewer")

    req = seed_change_request(
        db,
        creator_id=creator.id,
        reviewer_id=reviewer.id,
        status=RequestStatus.PENDING_REVIEW,
    )

    approval = Approval(
        change_request_id=req.id,
        reviewer_id=reviewer.id,
        decision=ApprovalDecision.APPROVED,
        decision_comment="Approved in test",
    )
    db.add(approval)
    db.commit()

    login_as(creator)

    response = client.get(f"/change-requests/{req.id}/approvals")

    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data) == 1
    assert data[0]["reviewer_id"] == reviewer.id
    assert data[0]["decision"] == ApprovalDecision.APPROVED.value