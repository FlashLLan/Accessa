"""Concurrent state changes on one request are serialised by SELECT ... FOR UPDATE.

Unlike the other tests, every request here gets its own database session (and
connection), so the two requests really run as two concurrent transactions.
log_action, which runs after the status check while the row lock is held, is
slowed down so the second request is guaranteed to arrive in the meantime.
"""
import threading
import time
from unittest.mock import patch

import pytest
from fastapi import Depends, Request
from fastapi.testclient import TestClient

from backend.api import change_requests, review_actions
from backend.core.dependencies import get_current_user
from backend.main import app
from backend.models.approval import Approval
from backend.models.audit_log import AuditLog
from backend.models.change_request import ChangeRequest
from backend.models.enums import RequestStatus
from backend.models.review_action import ReviewAction
from backend.models.user import User
from conftest import TestingSessionLocal
from database.db import get_db

HOLD_SECONDS = 0.5


@pytest.fixture
def concurrent_app(db):
    def own_session():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    def user_from_header(request: Request, session=Depends(get_db)):
        return session.get(User, int(request.headers["X-Test-User"]))

    app.dependency_overrides[get_db] = own_session
    app.dependency_overrides[get_current_user] = user_from_header
    app.state.limiter.enabled = False
    yield
    app.dependency_overrides.clear()
    app.state.limiter.enabled = True


@pytest.fixture
def people(db, create_role, create_user):
    roles = {name: create_role(db, name, level=lvl) for name, lvl in
             [("junior", 1), ("mid", 2), ("senior", 3), ("lead", 4), ("admin", 5)]}
    return {
        "junior": create_user(db, role=roles["junior"], label="junior"),
        "mid": create_user(db, role=roles["mid"], label="mid"),
        "mid2": create_user(db, role=roles["mid"], label="mid2"),
        "senior": create_user(db, role=roles["senior"], label="senior"),
    }


def _slow(real):
    def slowed(*args, **kwargs):
        time.sleep(HOLD_SECONDS)
        return real(*args, **kwargs)
    return slowed


def _run_concurrently(calls):
    """Start all (user, method, path, body) calls at the same moment; return status codes."""
    barrier = threading.Barrier(len(calls))
    results = [None] * len(calls)

    def worker(i, user, method, path, body):
        with TestClient(app) as client:
            barrier.wait()
            response = client.request(method, path, json=body, headers={"X-Test-User": str(user.id)})
            results[i] = (response.status_code, response.json())

    threads = [threading.Thread(target=worker, args=(i, *call)) for i, call in enumerate(calls)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert all(r is not None for r in results), "a request did not finish"
    return results


@pytest.fixture
def slow_audit():
    with patch.object(change_requests, "log_action", _slow(change_requests.log_action)), \
         patch.object(review_actions, "log_action", _slow(review_actions.log_action)):
        yield


def _fresh(db, request_id):
    db.expire_all()
    return db.get(ChangeRequest, request_id)


@pytest.mark.parametrize("first, second", [
    ("approve", "approve"),
    ("approve", "reject"),
    ("reject", "reject"),
])
def test_two_concurrent_decisions_give_exactly_one_success(
    db, people, seed_change_request, concurrent_app, slow_audit, first, second
):
    req = seed_change_request(db, creator_id=people["junior"].id, reviewer_id=people["mid"].id,
                              status=RequestStatus.PENDING_REVIEW)
    path = f"/change-requests/{req.id}/"
    results = _run_concurrently([
        (people["mid"], "POST", path + first, {"decision_comment": first}),
        (people["mid"], "POST", path + second, {"decision_comment": second}),
    ])

    statuses = sorted(code for code, _ in results)
    assert statuses == [200, 400], results
    loser = next(body for code, body in results if code == 400)
    assert loser["detail"].startswith("Only pending requests can be")

    winner = next(body for code, body in results if code == 200)
    assert _fresh(db, req.id).status.value == winner["status"]
    assert db.query(Approval).filter(Approval.change_request_id == req.id).count() == 1
    decided = db.query(AuditLog).filter(AuditLog.action.in_(["REQUEST_APPROVED", "REQUEST_REJECTED"])).count()
    assert decided == 1


def test_decision_and_escalation_at_once_give_exactly_one_success(
    db, people, seed_change_request, concurrent_app, slow_audit
):
    req = seed_change_request(db, creator_id=people["junior"].id, reviewer_id=people["mid"].id,
                              status=RequestStatus.PENDING_REVIEW)
    results = _run_concurrently([
        (people["mid"], "POST", f"/change-requests/{req.id}/approve", {"decision_comment": "ok"}),
        (people["mid"], "POST", f"/change-requests/{req.id}/escalate", {"target_reviewer_id": people["senior"].id}),
    ])

    (approve_code, approve_body), (escalate_code, escalate_body) = results
    # Whichever ran second re-checked under the lock and was refused: an approval
    # after the escalation is no longer by the assigned reviewer (403); an
    # escalation after the approval finds the request no longer pending (400).
    assert sorted([approve_code, escalate_code]) in ([200, 400], [200, 403]), results
    if escalate_code == 200:
        assert approve_code == 403
    final = _fresh(db, req.id)
    approved = db.query(Approval).filter(Approval.change_request_id == req.id).count()
    escalated = db.query(ReviewAction).filter(ReviewAction.change_request_id == req.id).count()
    # Either approved by mid (no escalation recorded) or escalated to senior (no approval).
    assert (approved, escalated) in [(1, 0), (0, 1)]
    if approved:
        assert final.status is RequestStatus.APPROVED and final.assigned_reviewer_id == people["mid"].id
    else:
        assert final.status is RequestStatus.PENDING_REVIEW and final.assigned_reviewer_id == people["senior"].id


def test_two_concurrent_delegations_give_exactly_one_success(
    db, people, seed_change_request, concurrent_app, slow_audit
):
    req = seed_change_request(db, creator_id=people["junior"].id, reviewer_id=people["mid"].id,
                              status=RequestStatus.PENDING_REVIEW)
    body = {"target_reviewer_id": people["mid2"].id}
    results = _run_concurrently([
        (people["mid"], "POST", f"/change-requests/{req.id}/delegate", body),
        (people["mid"], "POST", f"/change-requests/{req.id}/delegate", body),
    ])
    # The second one re-checks under the lock: mid is no longer the assigned reviewer.
    assert sorted(code for code, _ in results) in ([200, 400], [200, 403]), results
    assert db.query(ReviewAction).filter(ReviewAction.change_request_id == req.id).count() == 1
    assert _fresh(db, req.id).assigned_reviewer_id == people["mid2"].id


def test_two_concurrent_submits_and_applies_give_exactly_one_success(
    db, people, seed_change_request, concurrent_app, slow_audit
):
    draft = seed_change_request(db, creator_id=people["junior"].id, reviewer_id=people["mid"].id)
    approved = seed_change_request(db, creator_id=people["junior"].id, reviewer_id=people["mid"].id,
                                   status=RequestStatus.APPROVED)

    submits = _run_concurrently([(people["junior"], "POST", f"/change-requests/{draft.id}/submit", None)] * 2)
    applies = _run_concurrently([(people["junior"], "POST", f"/change-requests/{approved.id}/apply", None)] * 2)

    assert sorted(code for code, _ in submits) == [200, 400], submits
    assert sorted(code for code, _ in applies) == [200, 400], applies
    assert db.query(AuditLog).filter(AuditLog.action == "REQUEST_SUBMITTED").count() == 1
    assert db.query(AuditLog).filter(AuditLog.action == "REQUEST_APPLIED").count() == 1
