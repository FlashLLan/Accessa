from datetime import datetime
from itertools import count

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Boolean, DateTime, Enum as SAEnum, Integer, String, Text, create_engine, insert
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models.enums import RequestStatus
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
    risk_level=RiskLevel.LOW,
):
    req = ChangeRequest(
        title=title,
        description="Seeded description",
        request_type=next(iter(RequestType)),
        target_system="server-1",
        environment=next(iter(EnvironmentType)),
        risk_level=risk_level,
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
    junior_role = create_role(db, "junior", level=1)
    reviewer_role = create_role(db, "senior", level=5)

    creator = create_user(db, role=junior_role, label="junior")
    reviewer = create_user(db, role=reviewer_role, label="senior")

    login_as(creator)

    response = client.post("/change-requests/", json=request_payload(reviewer.id))

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["title"] == "Firewall change"
    assert data["assigned_reviewer"]["id"] == reviewer.id
    assert data["creator"]["id"] == creator.id
    assert data["status"] == RequestStatus.DRAFT.value


def test_create_change_request_rejects_self_reviewer(client, db):
    junior_role = create_role(db, "junior", level=1)
    creator = create_user(db, role=junior_role, label="junior")

    login_as(creator)

    payload = request_payload(creator.id)
    response = client.post("/change-requests/", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"] == "You cannot assign yourself as reviewer"


def test_list_change_requests_admin_sees_all(client, db):
    admin_role = create_role(db, "admin")
    reviewer_role = create_role(db, "senior")

    admin = create_user(db, role=admin_role, label="admin")
    creator1 = create_user(db, role=admin_role, label="creator1")
    creator2 = create_user(db, role=admin_role, label="creator2")
    reviewer = create_user(db, role=reviewer_role, label="senior")

    seed_change_request(db, creator_id=creator1.id, reviewer_id=reviewer.id, title="Req 1")
    seed_change_request(db, creator_id=creator2.id, reviewer_id=reviewer.id, title="Req 2")

    login_as(admin)

    response = client.get("/change-requests/")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2


def test_list_change_requests_regular_user_sees_only_related(client, db):
    junior_role = create_role(db, "junior", level=1)
    mid_role = create_role(db, "mid", level=3)
    senior_role = create_role(db, "senior", level=5)

    creator = create_user(db, role=junior_role, label="junior")
    reviewer = create_user(db, role=senior_role, label="senior")
    stranger = create_user(db, role=mid_role, label="mid")
    other_creator = create_user(db, role=junior_role, label="othercreator")

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
    junior_role = create_role(db, "junior", level=1)
    mid_role = create_role(db, "mid", level=3)
    senior_role = create_role(db, "senior", level=5)

    creator = create_user(db, role=junior_role, label="junior")
    reviewer = create_user(db, role=senior_role, label="senior")
    stranger = create_user(db, role=mid_role, label="mid")

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
    junior_role = create_role(db, "junior", level=1)
    senior_role = create_role(db, "senior", level=5)

    creator = create_user(db, role=junior_role, label="junior")
    reviewer = create_user(db, role=senior_role, label="senior")

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
    junior_role = create_role(db, "junior", level=1)
    senior_role = create_role(db, "senior", level=5)

    creator = create_user(db, role=junior_role, label="junior")
    reviewer = create_user(db, role=senior_role, label="senior")

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
    junior_role = create_role(db, "junior", level=1)
    senior_role = create_role(db, "senior", level=5)

    creator = create_user(db, role=junior_role, label="junior")
    reviewer = create_user(db, role=senior_role, label="senior")

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
    junior_role = create_role(db, "junior", level=1)
    senior_role = create_role(db, "senior", level=5)

    creator = create_user(db, role=junior_role, label="junior")
    reviewer = create_user(db, role=senior_role, label="senior")

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
    junior_role = create_role(db, "junior", level=1)
    senior_role = create_role(db, "senior", level=5)

    creator = create_user(db, role=junior_role, label="junior")
    reviewer = create_user(db, role=senior_role, label="senior")

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
    junior_role = create_role(db, "junior", level=1)
    senior_role = create_role(db, "senior", level=5)

    creator = create_user(db, role=junior_role, label="junior")
    reviewer = create_user(db, role=senior_role, label="senior")

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
    assert data[0]["reviewer"]["id"] == reviewer.id
    assert data[0]["reviewer"]["role"]["name"] == reviewer.role.name
    assert data[0]["decision"] == ApprovalDecision.APPROVED.value


def test_creator_can_mark_approved_request_as_applied(
    client, db, create_user, create_role, login_user, seed_change_request
):
    creator_role = create_role(db, "junior", level=1)
    admin_role = create_role(db, "admin", level=10)

    creator = create_user(db, role=creator_role, label="junior")
    reviewer = create_user(db, role=admin_role, label="admin")

    req = seed_change_request(
        db,
        creator_id=creator.id,
        reviewer_id=reviewer.id,
        status=RequestStatus.APPROVED,
    )

    login_user(creator)

    response = client.post(f"/change-requests/{req.id}/apply")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["id"] == req.id
    assert data["status"] == RequestStatus.APPLIED.value


def test_cannot_apply_request_unless_approved(
    client, db, create_user, create_role, login_user, seed_change_request
):
    creator_role = create_role(db, "junior", level=1)
    admin_role = create_role(db, "admin", level=10)

    creator = create_user(db, role=creator_role, label="junior")
    reviewer = create_user(db, role=admin_role, label="admin")

    req = seed_change_request(
        db,
        creator_id=creator.id,
        reviewer_id=reviewer.id,
        status=RequestStatus.PENDING_REVIEW,
    )

    login_user(creator)

    response = client.post(f"/change-requests/{req.id}/apply")

    assert response.status_code == 400
    assert response.json()["detail"] == "Only approved requests can be marked as applied"


def test_unrelated_user_cannot_mark_request_as_applied(
    client, db, create_user, create_role, login_user, seed_change_request
):
    junior_role = create_role(db, "junior", level=1)
    mid_role = create_role(db, "mid", level=3)
    admin_role = create_role(db, "admin", level=10)

    creator = create_user(db, role=junior_role, label="junior")
    reviewer = create_user(db, role=admin_role, label="admin")
    stranger = create_user(db, role=mid_role, label="mid")

    req = seed_change_request(
        db,
        creator_id=creator.id,
        reviewer_id=reviewer.id,
        status=RequestStatus.APPROVED,
    )

    login_user(stranger)

    response = client.post(f"/change-requests/{req.id}/apply")

    assert response.status_code == 403
    assert response.json()["detail"] == "Only the creator or admin can mark this request as applied"

def test_cannot_approve_request_unless_pending_review(
    client, db, create_user, create_role, login_user, seed_change_request
):
    junior_role = create_role(db, "junior", level=1)
    senior_role = create_role(db, "senior", level=5)

    creator = create_user(db, role=junior_role, label="junior")
    reviewer = create_user(db, role=senior_role, label="senior")

    # approved request cannot be approved again
    approved_req = seed_change_request(
        db,
        creator_id=creator.id,
        reviewer_id=reviewer.id,
        status=RequestStatus.APPROVED,
    )

    login_user(reviewer)
    response = client.post(
        f"/change-requests/{approved_req.id}/approve",
        json={"decision_comment": "Approving again"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Only pending requests can be approved"

    # draft request cannot be approved
    draft_req = seed_change_request(
        db,
        creator_id=creator.id,
        reviewer_id=reviewer.id,
        status=RequestStatus.DRAFT,
    )

    response = client.post(
        f"/change-requests/{draft_req.id}/approve",
        json={"decision_comment": "Approving draft"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Only pending requests can be approved"


def test_cannot_reject_request_unless_pending_review(
    client, db, create_user, create_role, login_user, seed_change_request
):
    junior_role = create_role(db, "junior", level=1)
    senior_role = create_role(db, "senior", level=5)

    creator = create_user(db, role=junior_role, label="junior")
    reviewer = create_user(db, role=senior_role, label="senior")

    # rejected request cannot be rejected again
    rejected_req = seed_change_request(
        db,
        creator_id=creator.id,
        reviewer_id=reviewer.id,
        status=RequestStatus.REJECTED,
    )

    login_user(reviewer)
    response = client.post(
        f"/change-requests/{rejected_req.id}/reject",
        json={"decision_comment": "Rejecting again"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Only pending requests can be rejected"

    # draft request cannot be rejected
    draft_req = seed_change_request(
        db,
        creator_id=creator.id,
        reviewer_id=reviewer.id,
        status=RequestStatus.DRAFT,
    )

    response = client.post(
        f"/change-requests/{draft_req.id}/reject",
        json={"decision_comment": "Rejecting draft"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Only pending requests can be rejected"


def test_creator_cannot_approve_own_request_even_if_assigned_as_reviewer(
    client, db, create_user, create_role, login_user, seed_change_request
):
    senior_role = create_role(db, "senior", level=5)

    creator = create_user(db, role=senior_role, label="senior")

    req = seed_change_request(
        db,
        creator_id=creator.id,
        reviewer_id=creator.id,
        status=RequestStatus.PENDING_REVIEW,
    )

    login_user(creator)

    response = client.post(
        f"/change-requests/{req.id}/approve",
        json={"decision_comment": "Self-approve"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "You cannot approve your own request"


def test_role_eligible_non_assigned_reviewer_can_approve_request(
    client, db, create_user, create_role, login_user, seed_change_request
):
    # Approval is now matrix-based: any eligible role may approve, not just the assigned reviewer.
    # junior + low allows: mid, senior, lead — so a lead who is not the assigned reviewer may approve.
    junior_role = create_role(db, "junior", level=1)
    senior_role = create_role(db, "senior", level=5)
    lead_role = create_role(db, "lead", level=8)

    creator = create_user(db, role=junior_role, label="junior")
    assigned_reviewer = create_user(db, role=senior_role, label="senior")
    other_lead = create_user(db, role=lead_role, label="lead")

    req = seed_change_request(
        db,
        creator_id=creator.id,
        reviewer_id=assigned_reviewer.id,
        status=RequestStatus.PENDING_REVIEW,
        risk_level=RiskLevel.LOW,
    )

    login_user(other_lead)

    response = client.post(
        f"/change-requests/{req.id}/approve",
        json={"decision_comment": "Approved by eligible lead"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == RequestStatus.APPROVED.value


def test_role_eligible_non_assigned_reviewer_can_reject_request(
    client, db, create_user, create_role, login_user, seed_change_request
):
    # Same as above but for rejection.
    junior_role = create_role(db, "junior", level=1)
    senior_role = create_role(db, "senior", level=5)
    lead_role = create_role(db, "lead", level=8)

    creator = create_user(db, role=junior_role, label="junior")
    assigned_reviewer = create_user(db, role=senior_role, label="senior")
    other_lead = create_user(db, role=lead_role, label="lead")

    req = seed_change_request(
        db,
        creator_id=creator.id,
        reviewer_id=assigned_reviewer.id,
        status=RequestStatus.PENDING_REVIEW,
        risk_level=RiskLevel.LOW,
    )

    login_user(other_lead)

    response = client.post(
        f"/change-requests/{req.id}/reject",
        json={"decision_comment": "Rejected by eligible lead"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == RequestStatus.REJECTED.value


def test_rejected_request_can_be_updated_and_resubmitted(
    client, db, create_user, create_role, login_user, seed_change_request
):
    junior_role = create_role(db, "junior", level=1)
    senior_role = create_role(db, "senior", level=5)

    creator = create_user(db, role=junior_role, label="junior")
    reviewer = create_user(db, role=senior_role, label="senior")

    req = seed_change_request(
        db,
        creator_id=creator.id,
        reviewer_id=reviewer.id,
        status=RequestStatus.REJECTED,
        title="Old title",
    )

    login_user(creator)

    patch_response = client.patch(
        f"/change-requests/{req.id}",
        json={
            "title": "Updated after rejection",
            "description": "Fixed issues and resubmitting",
            "request_type": req.request_type.value,
            "target_system": req.target_system,
            "environment": req.environment.value,
            "risk_level": req.risk_level.value,
            "assigned_reviewer_id": reviewer.id,
        },
    )

    assert patch_response.status_code == 200, patch_response.text
    patch_data = patch_response.json()
    assert patch_data["title"] == "Updated after rejection"
    assert patch_data["status"] == RequestStatus.REJECTED.value

    submit_response = client.post(f"/change-requests/{req.id}/submit")

    assert submit_response.status_code == 200, submit_response.text
    submit_data = submit_response.json()
    assert submit_data["status"] == RequestStatus.PENDING_REVIEW.value


# ---------------------------------------------------------------------------
# Approval matrix tests — spec cases 1-35
# ---------------------------------------------------------------------------
#
# Helpers shared across matrix tests
# ---------------------------------------------------------------------------

from backend.services.approval_service import get_allowed_approver_roles, can_user_decide_request


def _make_pending_request(db, *, creator, reviewer, risk_level=RiskLevel.LOW):
    """Seed a PENDING_REVIEW request directly into the DB."""
    return seed_change_request(
        db,
        creator_id=creator.id,
        reviewer_id=reviewer.id,
        status=RequestStatus.PENDING_REVIEW,
        risk_level=risk_level,
    )


# ---------------------------------------------------------------------------
# Allowed cases (1-18)
# ---------------------------------------------------------------------------

def test_matrix_case_01_mid_can_approve_junior_low(
    client, db, create_user, create_role, login_user
):
    junior_role = create_role(db, "junior", level=1)
    mid_role = create_role(db, "mid", level=2)
    lead_role = create_role(db, "lead", level=4)

    creator = create_user(db, role=junior_role, label="junior")
    dummy_reviewer = create_user(db, role=lead_role, label="lead")
    approver = create_user(db, role=mid_role, label="mid")

    req = _make_pending_request(db, creator=creator, reviewer=dummy_reviewer, risk_level=RiskLevel.LOW)
    login_user(approver)

    r = client.post(f"/change-requests/{req.id}/approve", json={})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == RequestStatus.APPROVED.value


def test_matrix_case_02_senior_can_approve_junior_low(
    client, db, create_user, create_role, login_user
):
    junior_role = create_role(db, "junior", level=1)
    senior_role = create_role(db, "senior", level=3)

    creator = create_user(db, role=junior_role, label="junior")
    approver = create_user(db, role=senior_role, label="senior")

    req = _make_pending_request(db, creator=creator, reviewer=approver, risk_level=RiskLevel.LOW)
    login_user(approver)

    r = client.post(f"/change-requests/{req.id}/approve", json={})
    assert r.status_code == 200, r.text


def test_matrix_case_03_senior_can_approve_junior_medium(
    client, db, create_user, create_role, login_user
):
    junior_role = create_role(db, "junior", level=1)
    senior_role = create_role(db, "senior", level=3)
    lead_role = create_role(db, "lead", level=4)

    creator = create_user(db, role=junior_role, label="junior")
    dummy_reviewer = create_user(db, role=lead_role, label="lead")
    approver = create_user(db, role=senior_role, label="senior")

    req = _make_pending_request(db, creator=creator, reviewer=dummy_reviewer, risk_level=RiskLevel.MEDIUM)
    login_user(approver)

    r = client.post(f"/change-requests/{req.id}/approve", json={})
    assert r.status_code == 200, r.text


def test_matrix_case_04_senior_can_approve_junior_high(
    client, db, create_user, create_role, login_user
):
    junior_role = create_role(db, "junior", level=1)
    senior_role = create_role(db, "senior", level=3)
    lead_role = create_role(db, "lead", level=4)

    creator = create_user(db, role=junior_role, label="junior")
    dummy_reviewer = create_user(db, role=lead_role, label="lead")
    approver = create_user(db, role=senior_role, label="senior")

    req = _make_pending_request(db, creator=creator, reviewer=dummy_reviewer, risk_level=RiskLevel.HIGH)
    login_user(approver)

    r = client.post(f"/change-requests/{req.id}/approve", json={})
    assert r.status_code == 200, r.text


def test_matrix_case_05_lead_can_approve_junior_high(
    client, db, create_user, create_role, login_user
):
    junior_role = create_role(db, "junior", level=1)
    lead_role = create_role(db, "lead", level=4)

    creator = create_user(db, role=junior_role, label="junior")
    approver = create_user(db, role=lead_role, label="lead")

    req = _make_pending_request(db, creator=creator, reviewer=approver, risk_level=RiskLevel.HIGH)
    login_user(approver)

    r = client.post(f"/change-requests/{req.id}/approve", json={})
    assert r.status_code == 200, r.text


def test_matrix_case_06_senior_can_approve_mid_low(
    client, db, create_user, create_role, login_user
):
    mid_role = create_role(db, "mid", level=2)
    senior_role = create_role(db, "senior", level=3)

    creator = create_user(db, role=mid_role, label="mid")
    approver = create_user(db, role=senior_role, label="senior")

    req = _make_pending_request(db, creator=creator, reviewer=approver, risk_level=RiskLevel.LOW)
    login_user(approver)

    r = client.post(f"/change-requests/{req.id}/approve", json={})
    assert r.status_code == 200, r.text


def test_matrix_case_07_senior_can_approve_mid_medium(
    client, db, create_user, create_role, login_user
):
    mid_role = create_role(db, "mid", level=2)
    senior_role = create_role(db, "senior", level=3)
    lead_role = create_role(db, "lead", level=4)

    creator = create_user(db, role=mid_role, label="mid")
    dummy_reviewer = create_user(db, role=lead_role, label="lead")
    approver = create_user(db, role=senior_role, label="senior")

    req = _make_pending_request(db, creator=creator, reviewer=dummy_reviewer, risk_level=RiskLevel.MEDIUM)
    login_user(approver)

    r = client.post(f"/change-requests/{req.id}/approve", json={})
    assert r.status_code == 200, r.text


def test_matrix_case_08_senior_can_approve_mid_high(
    client, db, create_user, create_role, login_user
):
    mid_role = create_role(db, "mid", level=2)
    senior_role = create_role(db, "senior", level=3)
    lead_role = create_role(db, "lead", level=4)

    creator = create_user(db, role=mid_role, label="mid")
    dummy_reviewer = create_user(db, role=lead_role, label="lead")
    approver = create_user(db, role=senior_role, label="senior")

    req = _make_pending_request(db, creator=creator, reviewer=dummy_reviewer, risk_level=RiskLevel.HIGH)
    login_user(approver)

    r = client.post(f"/change-requests/{req.id}/approve", json={})
    assert r.status_code == 200, r.text


def test_matrix_case_09_lead_can_approve_mid_high(
    client, db, create_user, create_role, login_user
):
    mid_role = create_role(db, "mid", level=2)
    lead_role = create_role(db, "lead", level=4)

    creator = create_user(db, role=mid_role, label="mid")
    approver = create_user(db, role=lead_role, label="lead")

    req = _make_pending_request(db, creator=creator, reviewer=approver, risk_level=RiskLevel.HIGH)
    login_user(approver)

    r = client.post(f"/change-requests/{req.id}/approve", json={})
    assert r.status_code == 200, r.text


def test_matrix_case_10_senior_can_approve_another_senior_low(
    client, db, create_user, create_role, login_user
):
    senior_role = create_role(db, "senior", level=3)

    creator = create_user(db, role=senior_role, label="senior_creator")
    approver = create_user(db, role=senior_role, label="senior_approver")

    req = _make_pending_request(db, creator=creator, reviewer=approver, risk_level=RiskLevel.LOW)
    login_user(approver)

    r = client.post(f"/change-requests/{req.id}/approve", json={})
    assert r.status_code == 200, r.text


def test_matrix_case_11_senior_can_approve_another_senior_medium(
    client, db, create_user, create_role, login_user
):
    senior_role = create_role(db, "senior", level=3)

    creator = create_user(db, role=senior_role, label="senior_creator")
    approver = create_user(db, role=senior_role, label="senior_approver")

    req = _make_pending_request(db, creator=creator, reviewer=approver, risk_level=RiskLevel.MEDIUM)
    login_user(approver)

    r = client.post(f"/change-requests/{req.id}/approve", json={})
    assert r.status_code == 200, r.text


def test_matrix_case_12_lead_can_approve_senior_high(
    client, db, create_user, create_role, login_user
):
    senior_role = create_role(db, "senior", level=3)
    lead_role = create_role(db, "lead", level=4)

    creator = create_user(db, role=senior_role, label="senior")
    approver = create_user(db, role=lead_role, label="lead")

    req = _make_pending_request(db, creator=creator, reviewer=approver, risk_level=RiskLevel.HIGH)
    login_user(approver)

    r = client.post(f"/change-requests/{req.id}/approve", json={})
    assert r.status_code == 200, r.text


def test_matrix_case_13_lead_can_approve_another_lead_low(
    client, db, create_user, create_role, login_user
):
    lead_role = create_role(db, "lead", level=4)

    creator = create_user(db, role=lead_role, label="lead_creator")
    approver = create_user(db, role=lead_role, label="lead_approver")

    req = _make_pending_request(db, creator=creator, reviewer=approver, risk_level=RiskLevel.LOW)
    login_user(approver)

    r = client.post(f"/change-requests/{req.id}/approve", json={})
    assert r.status_code == 200, r.text


def test_matrix_case_14_lead_can_approve_another_lead_medium(
    client, db, create_user, create_role, login_user
):
    lead_role = create_role(db, "lead", level=4)

    creator = create_user(db, role=lead_role, label="lead_creator")
    approver = create_user(db, role=lead_role, label="lead_approver")

    req = _make_pending_request(db, creator=creator, reviewer=approver, risk_level=RiskLevel.MEDIUM)
    login_user(approver)

    r = client.post(f"/change-requests/{req.id}/approve", json={})
    assert r.status_code == 200, r.text


def test_matrix_case_15_lead_can_approve_another_lead_high(
    client, db, create_user, create_role, login_user
):
    lead_role = create_role(db, "lead", level=4)

    creator = create_user(db, role=lead_role, label="lead_creator")
    approver = create_user(db, role=lead_role, label="lead_approver")

    req = _make_pending_request(db, creator=creator, reviewer=approver, risk_level=RiskLevel.HIGH)
    login_user(approver)

    r = client.post(f"/change-requests/{req.id}/approve", json={})
    assert r.status_code == 200, r.text


def test_matrix_case_16_admin_can_approve_another_admin_low_with_two_admins(
    client, db, create_user, create_role, login_user
):
    admin_role = create_role(db, "admin", level=5)
    lead_role = create_role(db, "lead", level=4)

    creator = create_user(db, role=admin_role, label="admin_creator")
    approver = create_user(db, role=admin_role, label="admin_approver")
    dummy_reviewer = create_user(db, role=lead_role, label="lead")

    req = _make_pending_request(db, creator=creator, reviewer=dummy_reviewer, risk_level=RiskLevel.LOW)
    login_user(approver)

    r = client.post(f"/change-requests/{req.id}/approve", json={})
    assert r.status_code == 200, r.text


def test_matrix_case_17_admin_can_approve_another_admin_medium_with_two_admins(
    client, db, create_user, create_role, login_user
):
    admin_role = create_role(db, "admin", level=5)
    lead_role = create_role(db, "lead", level=4)

    creator = create_user(db, role=admin_role, label="admin_creator")
    approver = create_user(db, role=admin_role, label="admin_approver")
    dummy_reviewer = create_user(db, role=lead_role, label="lead")

    req = _make_pending_request(db, creator=creator, reviewer=dummy_reviewer, risk_level=RiskLevel.MEDIUM)
    login_user(approver)

    r = client.post(f"/change-requests/{req.id}/approve", json={})
    assert r.status_code == 200, r.text


def test_matrix_case_18_admin_can_approve_another_admin_high_with_two_admins(
    client, db, create_user, create_role, login_user
):
    admin_role = create_role(db, "admin", level=5)
    lead_role = create_role(db, "lead", level=4)

    creator = create_user(db, role=admin_role, label="admin_creator")
    approver = create_user(db, role=admin_role, label="admin_approver")
    dummy_reviewer = create_user(db, role=lead_role, label="lead")

    req = _make_pending_request(db, creator=creator, reviewer=dummy_reviewer, risk_level=RiskLevel.HIGH)
    login_user(approver)

    r = client.post(f"/change-requests/{req.id}/approve", json={})
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# Forbidden cases (19-30)
# ---------------------------------------------------------------------------

def test_matrix_case_19_mid_cannot_approve_junior_medium(
    client, db, create_user, create_role, login_user
):
    junior_role = create_role(db, "junior", level=1)
    mid_role = create_role(db, "mid", level=2)
    lead_role = create_role(db, "lead", level=4)

    creator = create_user(db, role=junior_role, label="junior")
    dummy_reviewer = create_user(db, role=lead_role, label="lead")
    approver = create_user(db, role=mid_role, label="mid")

    req = _make_pending_request(db, creator=creator, reviewer=dummy_reviewer, risk_level=RiskLevel.MEDIUM)
    login_user(approver)

    r = client.post(f"/change-requests/{req.id}/approve", json={})
    assert r.status_code == 403
    assert r.json()["detail"] == "You are not allowed to approve this request."


def test_matrix_case_20_mid_cannot_approve_junior_high(
    client, db, create_user, create_role, login_user
):
    junior_role = create_role(db, "junior", level=1)
    mid_role = create_role(db, "mid", level=2)
    lead_role = create_role(db, "lead", level=4)

    creator = create_user(db, role=junior_role, label="junior")
    dummy_reviewer = create_user(db, role=lead_role, label="lead")
    approver = create_user(db, role=mid_role, label="mid")

    req = _make_pending_request(db, creator=creator, reviewer=dummy_reviewer, risk_level=RiskLevel.HIGH)
    login_user(approver)

    r = client.post(f"/change-requests/{req.id}/approve", json={})
    assert r.status_code == 403
    assert r.json()["detail"] == "You are not allowed to approve this request."


def test_matrix_case_21_mid_cannot_approve_mid_requests(
    client, db, create_user, create_role, login_user
):
    mid_role = create_role(db, "mid", level=2)
    lead_role = create_role(db, "lead", level=4)

    creator = create_user(db, role=mid_role, label="mid_creator")
    dummy_reviewer = create_user(db, role=lead_role, label="lead")
    approver = create_user(db, role=mid_role, label="mid_approver")

    req = _make_pending_request(db, creator=creator, reviewer=dummy_reviewer, risk_level=RiskLevel.LOW)
    login_user(approver)

    r = client.post(f"/change-requests/{req.id}/approve", json={})
    assert r.status_code == 403
    assert r.json()["detail"] == "You are not allowed to approve this request."


def test_matrix_case_22_senior_cannot_approve_own_request(
    client, db, create_user, create_role, login_user
):
    senior_role = create_role(db, "senior", level=3)
    lead_role = create_role(db, "lead", level=4)

    creator = create_user(db, role=senior_role, label="senior")
    dummy_reviewer = create_user(db, role=lead_role, label="lead")

    req = _make_pending_request(db, creator=creator, reviewer=dummy_reviewer, risk_level=RiskLevel.LOW)
    login_user(creator)

    r = client.post(f"/change-requests/{req.id}/approve", json={})
    assert r.status_code == 403
    assert r.json()["detail"] == "You cannot approve your own request"


def test_matrix_case_23_senior_cannot_approve_another_senior_high(
    client, db, create_user, create_role, login_user
):
    senior_role = create_role(db, "senior", level=3)
    lead_role = create_role(db, "lead", level=4)

    creator = create_user(db, role=senior_role, label="senior_creator")
    dummy_reviewer = create_user(db, role=lead_role, label="lead")
    approver = create_user(db, role=senior_role, label="senior_approver")

    req = _make_pending_request(db, creator=creator, reviewer=dummy_reviewer, risk_level=RiskLevel.HIGH)
    login_user(approver)

    r = client.post(f"/change-requests/{req.id}/approve", json={})
    assert r.status_code == 403
    assert r.json()["detail"] == "You are not allowed to approve this request."


def test_matrix_case_24_lead_cannot_approve_own_request(
    client, db, create_user, create_role, login_user
):
    lead_role = create_role(db, "lead", level=4)

    creator = create_user(db, role=lead_role, label="lead_creator")
    dummy_reviewer = create_user(db, role=lead_role, label="lead_reviewer")

    req = _make_pending_request(db, creator=creator, reviewer=dummy_reviewer, risk_level=RiskLevel.LOW)
    login_user(creator)

    r = client.post(f"/change-requests/{req.id}/approve", json={})
    assert r.status_code == 403
    assert r.json()["detail"] == "You cannot approve your own request"


def test_matrix_case_25_admin_cannot_approve_non_admin_requests(
    client, db, create_user, create_role, login_user
):
    junior_role = create_role(db, "junior", level=1)
    admin_role = create_role(db, "admin", level=5)
    lead_role = create_role(db, "lead", level=4)

    creator = create_user(db, role=junior_role, label="junior")
    dummy_reviewer = create_user(db, role=lead_role, label="lead")
    approver = create_user(db, role=admin_role, label="admin")

    req = _make_pending_request(db, creator=creator, reviewer=dummy_reviewer, risk_level=RiskLevel.LOW)
    login_user(approver)

    r = client.post(f"/change-requests/{req.id}/approve", json={})
    assert r.status_code == 403
    assert r.json()["detail"] == "You are not allowed to approve this request."


def test_matrix_case_26_non_admin_cannot_approve_admin_requests(
    client, db, create_user, create_role, login_user
):
    admin_role = create_role(db, "admin", level=5)
    senior_role = create_role(db, "senior", level=3)
    lead_role = create_role(db, "lead", level=4)

    creator = create_user(db, role=admin_role, label="admin_creator")
    dummy_reviewer = create_user(db, role=lead_role, label="lead")
    approver = create_user(db, role=senior_role, label="senior")
    # Second admin needed so the admin count check doesn't fire first
    create_user(db, role=admin_role, label="admin2")

    req = _make_pending_request(db, creator=creator, reviewer=dummy_reviewer, risk_level=RiskLevel.LOW)
    login_user(approver)

    r = client.post(f"/change-requests/{req.id}/approve", json={})
    assert r.status_code == 403
    assert r.json()["detail"] == "You are not allowed to approve this request."


def test_matrix_case_27_admin_cannot_approve_own_admin_request(
    client, db, create_user, create_role, login_user
):
    admin_role = create_role(db, "admin", level=5)
    lead_role = create_role(db, "lead", level=4)

    creator = create_user(db, role=admin_role, label="admin_creator")
    dummy_reviewer = create_user(db, role=lead_role, label="lead")
    # Second admin so count >= 2
    create_user(db, role=admin_role, label="admin2")

    req = _make_pending_request(db, creator=creator, reviewer=dummy_reviewer, risk_level=RiskLevel.LOW)
    login_user(creator)

    r = client.post(f"/change-requests/{req.id}/approve", json={})
    assert r.status_code == 403
    assert r.json()["detail"] == "You cannot approve your own request"


def test_matrix_case_28_junior_cannot_approve_anything(
    client, db, create_user, create_role, login_user
):
    junior_role = create_role(db, "junior", level=1)
    lead_role = create_role(db, "lead", level=4)

    creator = create_user(db, role=junior_role, label="junior_creator")
    dummy_reviewer = create_user(db, role=lead_role, label="lead")
    approver = create_user(db, role=junior_role, label="junior_approver")

    req = _make_pending_request(db, creator=creator, reviewer=dummy_reviewer, risk_level=RiskLevel.LOW)
    login_user(approver)

    r = client.post(f"/change-requests/{req.id}/approve", json={})
    assert r.status_code == 403
    assert r.json()["detail"] == "You are not allowed to approve this request."


def test_matrix_case_29_cannot_approve_already_approved_request(
    client, db, create_user, create_role, login_user
):
    junior_role = create_role(db, "junior", level=1)
    senior_role = create_role(db, "senior", level=3)

    creator = create_user(db, role=junior_role, label="junior")
    approver = create_user(db, role=senior_role, label="senior")

    req = seed_change_request(
        db,
        creator_id=creator.id,
        reviewer_id=approver.id,
        status=RequestStatus.APPROVED,
        risk_level=RiskLevel.LOW,
    )
    login_user(approver)

    r = client.post(f"/change-requests/{req.id}/approve", json={})
    assert r.status_code == 400
    assert r.json()["detail"] == "Only pending requests can be approved"


def test_matrix_case_30_cannot_reject_already_rejected_request(
    client, db, create_user, create_role, login_user
):
    junior_role = create_role(db, "junior", level=1)
    senior_role = create_role(db, "senior", level=3)

    creator = create_user(db, role=junior_role, label="junior")
    approver = create_user(db, role=senior_role, label="senior")

    req = seed_change_request(
        db,
        creator_id=creator.id,
        reviewer_id=approver.id,
        status=RequestStatus.REJECTED,
        risk_level=RiskLevel.LOW,
    )
    login_user(approver)

    r = client.post(f"/change-requests/{req.id}/reject", json={})
    assert r.status_code == 400
    assert r.json()["detail"] == "Only pending requests can be rejected"


# ---------------------------------------------------------------------------
# Workflow edge cases (31-35)
# ---------------------------------------------------------------------------

def test_matrix_case_31_admin_workflow_fails_when_fewer_than_two_active_admins(
    client, db, create_user, create_role, login_user
):
    admin_role = create_role(db, "admin", level=5)
    lead_role = create_role(db, "lead", level=4)

    creator = create_user(db, role=admin_role, label="admin_creator")
    approver = create_user(db, role=admin_role, label="admin_approver")
    dummy_reviewer = create_user(db, role=lead_role, label="lead")

    # Deactivate approver so only 1 active admin remains
    approver.is_active = False
    db.commit()

    req = _make_pending_request(db, creator=creator, reviewer=dummy_reviewer, risk_level=RiskLevel.LOW)
    login_user(approver)  # auth override bypasses is_active check

    r = client.post(f"/change-requests/{req.id}/approve", json={})
    assert r.status_code == 400
    assert "at least two active admins" in r.json()["detail"]


def test_matrix_case_32_unsupported_requester_role_rejected_safely():
    # Unit test for the helper — no DB needed.
    result = get_allowed_approver_roles("contractor", "low")
    assert result == []


def test_matrix_case_33_invalid_severity_rejected_safely():
    result = get_allowed_approver_roles("junior", "extreme")
    assert result == []


def test_matrix_case_34_missing_severity_rejected_safely():
    result = get_allowed_approver_roles("junior", "")
    assert result == []


def test_matrix_case_35_missing_requester_role_rejected_safely():
    result = get_allowed_approver_roles("", "low")
    assert result == []