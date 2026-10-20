"""Request lifecycle timestamps, role-level hierarchy, single PR/MR URL, and the
database constraints introduced by revision c5ee582f5a9e."""
import psycopg.errors
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError

from backend.models.enums import RequestStatus, ReviewActionType, RiskLevel
from backend.models.change_request import ChangeRequest
from backend.models.review_action import ReviewAction


@pytest.fixture
def people(db, create_role, create_user):
    roles = {name: create_role(db, name, level=lvl) for name, lvl in
             [("junior", 1), ("mid", 2), ("senior", 3), ("lead", 4), ("admin", 5)]}
    return {
        "roles": roles,
        "creator": create_user(db, role=roles["junior"], label="creator"),
        "mid": create_user(db, role=roles["mid"], label="mid"),
        "mid2": create_user(db, role=roles["mid"], label="mid2"),
        "senior": create_user(db, role=roles["senior"], label="senior"),
    }


# --- submitted_at / closed_at --------------------------------------------------

def test_submit_sets_submitted_at(client, db, people, login_user, seed_change_request):
    req = seed_change_request(db, creator_id=people["creator"].id, reviewer_id=people["mid"].id)
    assert req.submitted_at is None

    login_user(people["creator"])
    assert client.post(f"/change-requests/{req.id}/submit").status_code == 200

    db.refresh(req)
    assert req.submitted_at is not None
    assert req.submitted_at.tzinfo is not None
    assert req.closed_at is None


def test_reject_sets_closed_at(client, db, people, login_user, seed_change_request):
    req = seed_change_request(
        db, creator_id=people["creator"].id, reviewer_id=people["mid"].id, status=RequestStatus.PENDING_REVIEW
    )

    login_user(people["mid"])
    assert client.post(f"/change-requests/{req.id}/reject", json={"decision_comment": "no"}).status_code == 200

    db.refresh(req)
    assert req.status == RequestStatus.REJECTED
    assert req.closed_at is not None


def test_approve_does_not_close_but_apply_sets_closed_at(client, db, people, login_user, seed_change_request):
    req = seed_change_request(
        db, creator_id=people["creator"].id, reviewer_id=people["mid"].id, status=RequestStatus.PENDING_REVIEW
    )

    login_user(people["mid"])
    assert client.post(f"/change-requests/{req.id}/approve", json={"decision_comment": "ok"}).status_code == 200
    db.refresh(req)
    assert req.closed_at is None  # approved is not a final state; it still has to be applied

    login_user(people["creator"])
    assert client.post(f"/change-requests/{req.id}/apply").status_code == 200
    db.refresh(req)
    assert req.status == RequestStatus.APPLIED
    assert req.closed_at is not None


# --- hierarchy comes from roles.level --------------------------------------------

def test_escalate_and_delegate_work_with_seeded_role_levels(client, db, people, login_user, seed_change_request):
    req = seed_change_request(
        db, creator_id=people["creator"].id, reviewer_id=people["mid"].id, status=RequestStatus.PENDING_REVIEW
    )

    login_user(people["mid"])
    delegated = client.post(f"/change-requests/{req.id}/delegate", json={"target_reviewer_id": people["mid2"].id})
    assert delegated.status_code == 200, delegated.text

    login_user(people["mid2"])
    escalated = client.post(f"/change-requests/{req.id}/escalate", json={"target_reviewer_id": people["senior"].id})
    assert escalated.status_code == 200, escalated.text

    types = [a.action_type for a in db.query(ReviewAction).order_by(ReviewAction.id)]
    assert types == [ReviewActionType.DELEGATE, ReviewActionType.ESCALATE]


def test_hierarchy_follows_role_level_not_role_name(
    client, db, create_role, create_user, login_user, seed_change_request
):
    # Levels deliberately contradict the old hard-coded name order
    # (junior < mid < senior): here "senior" ranks *below* "mid".
    junior = create_role(db, "junior", level=1)
    senior = create_role(db, "senior", level=10)
    mid = create_role(db, "mid", level=20)
    creator = create_user(db, role=junior, label="creator")
    mid_reviewer = create_user(db, role=mid, label="mid")
    senior_user = create_user(db, role=senior, label="senior")

    req = seed_change_request(
        db, creator_id=creator.id, reviewer_id=mid_reviewer.id, status=RequestStatus.PENDING_REVIEW,
        risk_level=RiskLevel.LOW,
    )

    login_user(mid_reviewer)
    escalate = client.post(f"/change-requests/{req.id}/escalate", json={"target_reviewer_id": senior_user.id})
    assert escalate.status_code == 400
    assert escalate.json()["detail"].startswith("Escalation must go to a higher role")

    delegate = client.post(f"/change-requests/{req.id}/delegate", json={"target_reviewer_id": senior_user.id})
    assert delegate.status_code == 400
    assert delegate.json()["detail"] == "Delegation to a lower role is not allowed."


# --- single pull/merge request URL ------------------------------------------------

GITLAB_MR = "https://gitlab.com/org/repo/-/merge_requests/7"


def test_git_context_pull_request_url_round_trips(client, db, people, login_user, seed_change_request):
    req = seed_change_request(db, creator_id=people["creator"].id, reviewer_id=people["mid"].id)

    login_user(people["creator"])
    saved = client.post(f"/change-requests/{req.id}/git-context", json={
        "provider": "gitlab", "branch_name": "feature/x", "pull_request_url": GITLAB_MR,
    })
    assert saved.status_code == 200, saved.text
    assert saved.json()["pull_request_url"] == GITLAB_MR
    assert "merge_request_url" not in saved.json()

    fetched = client.get(f"/change-requests/{req.id}/git-context")
    assert fetched.status_code == 200
    assert fetched.json()["pull_request_url"] == GITLAB_MR
    assert "merge_request_url" not in fetched.json()


def test_git_context_ignores_removed_merge_request_url_field(client, db, people, login_user, seed_change_request):
    req = seed_change_request(db, creator_id=people["creator"].id, reviewer_id=people["mid"].id)

    login_user(people["creator"])
    saved = client.post(f"/change-requests/{req.id}/git-context", json={
        "branch_name": "feature/y", "merge_request_url": GITLAB_MR,
    })

    assert saved.status_code == 200, saved.text
    assert saved.json()["pull_request_url"] is None


# --- database constraints ---------------------------------------------------------

def _raw_request(conn, people, status):
    conn.execute(text(
        "INSERT INTO change_requests (workspace_id, title, description, request_type, target_system, "
        "environment, risk_level, status, created_by, assigned_reviewer_id) "
        "VALUES (1, 'x', 'x', 'ACCESS_CHANGE', 'srv', 'DEV', 'LOW', :status, :c, :r)"
    ), {"status": status, "c": people["creator"].id, "r": people["mid"].id})


@pytest.mark.parametrize("status", ["ESCALATED", "DELEGATED", "CLOSED", "CANCELLED"])
def test_database_rejects_removed_request_status(app_db_engine, people, status):
    with pytest.raises(IntegrityError) as exc, app_db_engine.begin() as conn:
        _raw_request(conn, people, status)
    assert isinstance(exc.value.orig, psycopg.errors.CheckViolation)
    assert "ck_change_requests_request_status" in str(exc.value.orig)


@pytest.mark.parametrize("status", ["DRAFT", "PENDING_REVIEW", "APPROVED", "REJECTED", "APPLIED"])
def test_database_accepts_remaining_request_status(app_db_engine, people, status):
    with app_db_engine.begin() as conn:
        _raw_request(conn, people, status)


@pytest.fixture
def raw_request_id(db, people, seed_change_request):
    return seed_change_request(db, creator_id=people["creator"].id, reviewer_id=people["mid"].id).id


@pytest.mark.parametrize("action_type", ["APPROVE", "COMMENT", "RETURN_FOR_CHANGES", "START_REVIEW"])
def test_database_rejects_removed_review_action_type(app_db_engine, people, raw_request_id, action_type):
    # Values longer than VARCHAR(8) fail on length (DataError), shorter ones on the CHECK.
    with pytest.raises((IntegrityError, DataError)) as exc, app_db_engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO review_actions (change_request_id, actor_id, action_type, target_reviewer_id) "
            "VALUES (:cr, :a, :t, :target)"
        ), {"cr": raw_request_id, "a": people["mid"].id, "t": action_type, "target": people["senior"].id})
    assert isinstance(exc.value.orig, (psycopg.errors.CheckViolation, psycopg.errors.StringDataRightTruncation))


def test_database_rejects_review_action_without_target(app_db_engine, people, raw_request_id):
    with pytest.raises(IntegrityError) as exc, app_db_engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO review_actions (change_request_id, actor_id, action_type, target_reviewer_id) "
            "VALUES (:cr, :a, 'ESCALATE', NULL)"
        ), {"cr": raw_request_id, "a": people["mid"].id})
    assert isinstance(exc.value.orig, psycopg.errors.NotNullViolation)


@pytest.mark.parametrize("column", ["is_active", "created_at", "updated_at"])
def test_database_rejects_null_user_status_and_timestamps(app_db_engine, people, column):
    with pytest.raises(IntegrityError) as exc, app_db_engine.begin() as conn:
        conn.execute(text(
            f"INSERT INTO users (workspace_id, full_name, email, hashed_password, role_id, {column}) "
            "VALUES (1, 'x', 'null-check@example.com', 'x', :role, NULL)"
        ), {"role": people["roles"]["junior"].id})
    assert isinstance(exc.value.orig, psycopg.errors.NotNullViolation)


def test_database_fills_user_defaults_when_columns_are_omitted(app_db_engine, people):
    with app_db_engine.begin() as conn:
        row = conn.execute(text(
            "INSERT INTO users (workspace_id, full_name, email, hashed_password, role_id) "
            "VALUES (1, 'x', 'defaults@example.com', 'x', :role) RETURNING is_active, created_at, updated_at"
        ), {"role": people["roles"]["junior"].id}).one()
    assert row.is_active is True
    assert row.created_at is not None and row.updated_at is not None


def test_review_action_model_has_no_status_columns():
    assert "from_status" not in ReviewAction.__table__.c
    assert "to_status" not in ReviewAction.__table__.c
    assert ReviewAction.__table__.c.target_reviewer_id.nullable is False
    assert {s.name for s in RequestStatus} == {"DRAFT", "PENDING_REVIEW", "APPROVED", "REJECTED", "APPLIED"}
    assert {t.name for t in ReviewActionType} == {"ESCALATE", "DELEGATE"}
    assert "submitted_at" in ChangeRequest.__table__.c and "closed_at" in ChangeRequest.__table__.c
