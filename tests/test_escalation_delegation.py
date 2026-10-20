"""
Escalation and delegation workflow tests.
Covers PDF spec sections B, C, D, E, F, G and regressions 1-7.
"""
import pytest
from backend.models.enums import RequestStatus, RiskLevel
from backend.models.review_action import ReviewAction


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _pending(db, seed, *, creator_id, reviewer_id, risk_level=RiskLevel.LOW):
    return seed(
        db,
        creator_id=creator_id,
        reviewer_id=reviewer_id,
        status=RequestStatus.PENDING_REVIEW,
        risk_level=risk_level,
    )


def _escalate(client, request_id, target_id, comment=None):
    return client.post(
        f"/change-requests/{request_id}/escalate",
        json={"target_reviewer_id": target_id, "comment": comment},
    )


def _delegate(client, request_id, target_id, comment=None):
    return client.post(
        f"/change-requests/{request_id}/delegate",
        json={"target_reviewer_id": target_id, "comment": comment},
    )


def _review_actions(db, request_id):
    return (
        db.query(ReviewAction)
        .filter(ReviewAction.change_request_id == request_id)
        .order_by(ReviewAction.created_at.asc())
        .all()
    )


# ===========================================================================
# D. ESCALATION — Allowed cases
# ===========================================================================

def test_escalate_mid_to_senior_junior_low(
    client, db, create_role, create_user, login_user, seed_change_request
):
    junior_role = create_role(db, "junior", level=1)
    mid_role    = create_role(db, "mid",    level=2)
    senior_role = create_role(db, "senior", level=3)

    creator  = create_user(db, role=junior_role,  label="junior")
    reviewer = create_user(db, role=mid_role,     label="mid")
    target   = create_user(db, role=senior_role,  label="senior")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=reviewer.id)
    login_user(reviewer)

    r = _escalate(client, req.id, target.id, "need senior review")
    assert r.status_code == 200, r.text

    db.refresh(req)
    assert req.assigned_reviewer_id == target.id
    assert req.current_reviewer_id  == target.id
    assert req.status == RequestStatus.PENDING_REVIEW


def test_escalate_mid_to_lead_junior_low(
    client, db, create_role, create_user, login_user, seed_change_request
):
    junior_role = create_role(db, "junior", level=1)
    mid_role    = create_role(db, "mid",    level=2)
    lead_role   = create_role(db, "lead",   level=4)

    creator  = create_user(db, role=junior_role, label="junior")
    reviewer = create_user(db, role=mid_role,    label="mid")
    target   = create_user(db, role=lead_role,   label="lead")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=reviewer.id)
    login_user(reviewer)

    r = _escalate(client, req.id, target.id)
    assert r.status_code == 200, r.text

    db.refresh(req)
    assert req.assigned_reviewer_id == target.id


def test_escalate_senior_to_lead(
    client, db, create_role, create_user, login_user, seed_change_request
):
    mid_role    = create_role(db, "mid",    level=2)
    senior_role = create_role(db, "senior", level=3)
    lead_role   = create_role(db, "lead",   level=4)

    creator  = create_user(db, role=mid_role,    label="mid")
    reviewer = create_user(db, role=senior_role, label="senior")
    target   = create_user(db, role=lead_role,   label="lead")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=reviewer.id)
    login_user(reviewer)

    r = _escalate(client, req.id, target.id)
    assert r.status_code == 200, r.text

    db.refresh(req)
    assert req.assigned_reviewer_id == target.id


# ===========================================================================
# D. ESCALATION — Regression 1: same-role escalation must be forbidden
# ===========================================================================

def test_escalate_mid_to_mid_forbidden(
    client, db, create_role, create_user, login_user, seed_change_request
):
    junior_role = create_role(db, "junior", level=1)
    mid_role    = create_role(db, "mid",    level=2)

    creator     = create_user(db, role=junior_role, label="junior")
    reviewer    = create_user(db, role=mid_role,    label="mid_a")
    target      = create_user(db, role=mid_role,    label="mid_b")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=reviewer.id)
    login_user(reviewer)

    r = _escalate(client, req.id, target.id)
    assert r.status_code == 400, r.text
    assert "higher role" in r.json()["detail"].lower() or "delegation" in r.json()["detail"].lower()

    db.refresh(req)
    assert req.assigned_reviewer_id == reviewer.id
    assert len(_review_actions(db, req.id)) == 0


def test_escalate_senior_to_senior_forbidden(
    client, db, create_role, create_user, login_user, seed_change_request
):
    junior_role = create_role(db, "junior", level=1)
    senior_role = create_role(db, "senior", level=3)

    creator  = create_user(db, role=junior_role, label="junior")
    reviewer = create_user(db, role=senior_role, label="senior_a")
    target   = create_user(db, role=senior_role, label="senior_b")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=reviewer.id)
    login_user(reviewer)

    r = _escalate(client, req.id, target.id)
    assert r.status_code == 400, r.text

    db.refresh(req)
    assert req.assigned_reviewer_id == reviewer.id
    assert len(_review_actions(db, req.id)) == 0


def test_escalate_lead_to_lead_forbidden(
    client, db, create_role, create_user, login_user, seed_change_request
):
    mid_role  = create_role(db, "mid",  level=2)
    lead_role = create_role(db, "lead", level=4)

    creator  = create_user(db, role=mid_role,  label="mid")
    reviewer = create_user(db, role=lead_role, label="lead_a")
    target   = create_user(db, role=lead_role, label="lead_b")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=reviewer.id)
    login_user(reviewer)

    r = _escalate(client, req.id, target.id)
    assert r.status_code == 400, r.text

    db.refresh(req)
    assert req.assigned_reviewer_id == reviewer.id
    assert len(_review_actions(db, req.id)) == 0


# ===========================================================================
# D. ESCALATION — Regression 2: lower-role escalation must be forbidden
# ===========================================================================

def test_escalate_lead_to_senior_forbidden(
    client, db, create_role, create_user, login_user, seed_change_request
):
    mid_role    = create_role(db, "mid",    level=2)
    senior_role = create_role(db, "senior", level=3)
    lead_role   = create_role(db, "lead",   level=4)

    creator  = create_user(db, role=mid_role,    label="mid")
    reviewer = create_user(db, role=lead_role,   label="lead")
    target   = create_user(db, role=senior_role, label="senior")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=reviewer.id)
    login_user(reviewer)

    r = _escalate(client, req.id, target.id)
    assert r.status_code == 400, r.text

    db.refresh(req)
    assert req.assigned_reviewer_id == reviewer.id
    assert len(_review_actions(db, req.id)) == 0


def test_escalate_senior_to_mid_forbidden(
    client, db, create_role, create_user, login_user, seed_change_request
):
    junior_role = create_role(db, "junior", level=1)
    mid_role    = create_role(db, "mid",    level=2)
    senior_role = create_role(db, "senior", level=3)

    creator  = create_user(db, role=junior_role, label="junior")
    reviewer = create_user(db, role=senior_role, label="senior")
    target   = create_user(db, role=mid_role,    label="mid")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=reviewer.id)
    login_user(reviewer)

    r = _escalate(client, req.id, target.id)
    assert r.status_code == 400, r.text

    db.refresh(req)
    assert req.assigned_reviewer_id == reviewer.id


def test_escalate_back_to_previous_reviewer_forbidden(
    client, db, create_role, create_user, login_user, seed_change_request
):
    """Regression 2 — after senior->lead, lead cannot escalate back to senior."""
    junior_role = create_role(db, "junior", level=1)
    mid_role    = create_role(db, "mid",    level=2)
    senior_role = create_role(db, "senior", level=3)
    lead_role   = create_role(db, "lead",   level=4)

    creator  = create_user(db, role=junior_role, label="junior")
    mid_user = create_user(db, role=mid_role,    label="mid")
    senior   = create_user(db, role=senior_role, label="senior")
    lead     = create_user(db, role=lead_role,   label="lead")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=mid_user.id)

    login_user(mid_user)
    assert _escalate(client, req.id, senior.id).status_code == 200

    login_user(senior)
    assert _escalate(client, req.id, lead.id).status_code == 200

    db.refresh(req)
    assert req.assigned_reviewer_id == lead.id

    # lead tries to escalate back to senior — must fail
    login_user(lead)
    r = _escalate(client, req.id, senior.id)
    assert r.status_code in (400, 403), r.text

    db.refresh(req)
    assert req.assigned_reviewer_id == lead.id
    assert len(_review_actions(db, req.id)) == 2  # only the two valid escalations


# ===========================================================================
# D. ESCALATION — Forbidden (other reasons)
# ===========================================================================

def test_escalate_to_requester_forbidden(
    client, db, create_role, create_user, login_user, seed_change_request
):
    junior_role = create_role(db, "junior", level=1)
    mid_role    = create_role(db, "mid",    level=2)
    lead_role   = create_role(db, "lead",   level=4)

    # Use lead as creator so they'd otherwise be an eligible escalation target
    lead_creator = create_user(db, role=lead_role,   label="lead_creator")
    reviewer     = create_user(db, role=mid_role,    label="mid")
    # Need a senior or lead as assigned reviewer eligible for junior+low...
    # Actually: creator=lead, reviewer=mid — but mid is NOT eligible for lead+anything (matrix: lead+low=["lead"])
    # Let's use junior creator instead so mid is eligible
    junior_creator = create_user(db, role=junior_role, label="junior")
    lead_target    = create_user(db, role=lead_role,   label="lead_target")

    req = _pending(db, seed_change_request, creator_id=junior_creator.id, reviewer_id=reviewer.id)
    # Make the creator also a lead so escalating to them hits the "creator" guard
    # instead, just escalate mid->lead_target then try to escalate to junior_creator
    login_user(reviewer)
    # Try to escalate to the junior creator — blocked by "creator" guard
    r = _escalate(client, req.id, junior_creator.id)
    assert r.status_code == 400, r.text
    assert "creator" in r.json()["detail"].lower()

    db.refresh(req)
    assert req.assigned_reviewer_id == reviewer.id


def test_escalate_to_inactive_user_forbidden(
    client, db, create_role, create_user, login_user, seed_change_request
):
    junior_role = create_role(db, "junior", level=1)
    mid_role    = create_role(db, "mid",    level=2)
    senior_role = create_role(db, "senior", level=3)

    creator  = create_user(db, role=junior_role, label="junior")
    reviewer = create_user(db, role=mid_role,    label="mid")
    target   = create_user(db, role=senior_role, label="senior")
    target.is_active = False
    db.commit()

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=reviewer.id)
    login_user(reviewer)

    r = _escalate(client, req.id, target.id)
    assert r.status_code == 404, r.text

    db.refresh(req)
    assert req.assigned_reviewer_id == reviewer.id
    assert len(_review_actions(db, req.id)) == 0


def test_escalate_to_self_forbidden(
    client, db, create_role, create_user, login_user, seed_change_request
):
    junior_role = create_role(db, "junior", level=1)
    mid_role    = create_role(db, "mid",    level=2)

    creator  = create_user(db, role=junior_role, label="junior")
    reviewer = create_user(db, role=mid_role,    label="mid")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=reviewer.id)
    login_user(reviewer)

    r = _escalate(client, req.id, reviewer.id)
    assert r.status_code == 400, r.text
    assert "yourself" in r.json()["detail"].lower()


def test_escalate_non_pending_request_forbidden(
    client, db, create_role, create_user, login_user, seed_change_request
):
    junior_role = create_role(db, "junior", level=1)
    mid_role    = create_role(db, "mid",    level=2)
    senior_role = create_role(db, "senior", level=3)

    creator  = create_user(db, role=junior_role, label="junior")
    reviewer = create_user(db, role=mid_role,    label="mid")
    target   = create_user(db, role=senior_role, label="senior")

    req = seed_change_request(
        db,
        creator_id=creator.id,
        reviewer_id=reviewer.id,
        status=RequestStatus.APPROVED,
    )
    login_user(reviewer)

    r = _escalate(client, req.id, target.id)
    assert r.status_code == 400, r.text
    assert len(_review_actions(db, req.id)) == 0


def test_escalate_by_non_assigned_reviewer_forbidden(
    client, db, create_role, create_user, login_user, seed_change_request
):
    junior_role = create_role(db, "junior", level=1)
    mid_role    = create_role(db, "mid",    level=2)
    senior_role = create_role(db, "senior", level=3)
    lead_role   = create_role(db, "lead",   level=4)

    creator  = create_user(db, role=junior_role, label="junior")
    reviewer = create_user(db, role=mid_role,    label="mid_assigned")
    outsider = create_user(db, role=senior_role, label="senior_outsider")
    target   = create_user(db, role=lead_role,   label="lead")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=reviewer.id)
    login_user(outsider)  # not the assigned reviewer

    r = _escalate(client, req.id, target.id)
    assert r.status_code == 403, r.text
    assert len(_review_actions(db, req.id)) == 0


def test_escalate_target_not_in_matrix_forbidden(
    client, db, create_role, create_user, login_user, seed_change_request
):
    """Escalating to admin for a non-admin request is blocked by the matrix."""
    junior_role = create_role(db, "junior", level=1)
    mid_role    = create_role(db, "mid",    level=2)
    admin_role  = create_role(db, "admin",  level=10)

    creator  = create_user(db, role=junior_role, label="junior")
    reviewer = create_user(db, role=mid_role,    label="mid")
    target   = create_user(db, role=admin_role,  label="admin")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=reviewer.id)
    login_user(reviewer)

    r = _escalate(client, req.id, target.id)
    assert r.status_code == 400, r.text
    assert "matrix" in r.json()["detail"].lower() or "eligible" in r.json()["detail"].lower()


# ===========================================================================
# D. ESCALATION — Post-success state assertions
# ===========================================================================

def test_escalate_creates_review_action_record(
    client, db, create_role, create_user, login_user, seed_change_request
):
    junior_role = create_role(db, "junior", level=1)
    mid_role    = create_role(db, "mid",    level=2)
    senior_role = create_role(db, "senior", level=3)

    creator  = create_user(db, role=junior_role, label="junior")
    reviewer = create_user(db, role=mid_role,    label="mid")
    target   = create_user(db, role=senior_role, label="senior")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=reviewer.id)
    login_user(reviewer)
    r = _escalate(client, req.id, target.id, "complexity reason")
    assert r.status_code == 200

    actions = _review_actions(db, req.id)
    assert len(actions) == 1
    a = actions[0]
    assert a.action_type.value == "escalate"
    assert a.actor_id == reviewer.id
    assert a.target_reviewer_id == target.id
    assert a.comment == "complexity reason"
    assert a.to_status == RequestStatus.PENDING_REVIEW.value


# ===========================================================================
# Regression 4: Previous reviewer locked out after escalation
# ===========================================================================

def test_previous_reviewer_locked_out_after_escalation(
    client, db, create_role, create_user, login_user, seed_change_request
):
    """Regression 4 — mid is fully blocked after escalating to senior."""
    junior_role = create_role(db, "junior", level=1)
    mid_role    = create_role(db, "mid",    level=2)
    senior_role = create_role(db, "senior", level=3)
    lead_role   = create_role(db, "lead",   level=4)

    creator  = create_user(db, role=junior_role, label="junior")
    mid_user = create_user(db, role=mid_role,    label="mid")
    senior   = create_user(db, role=senior_role, label="senior")
    lead     = create_user(db, role=lead_role,   label="lead")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=mid_user.id)

    login_user(mid_user)
    assert _escalate(client, req.id, senior.id).status_code == 200

    # mid can no longer approve
    login_user(mid_user)
    assert client.post(f"/change-requests/{req.id}/approve", json={}).status_code == 403

    # mid can no longer reject
    assert client.post(f"/change-requests/{req.id}/reject", json={}).status_code == 403

    # mid can no longer escalate
    assert _escalate(client, req.id, lead.id).status_code == 403

    # mid can no longer delegate
    assert _delegate(client, req.id, lead.id).status_code == 403

    # senior (new assigned reviewer) can approve
    login_user(senior)
    assert client.post(f"/change-requests/{req.id}/approve", json={}).status_code == 200


# ===========================================================================
# Regression 7: Escalation chain — current reviewer can continue escalating
# ===========================================================================

def test_escalation_chain_mid_to_senior_to_lead(
    client, db, create_role, create_user, login_user, seed_change_request
):
    """Regression 7 — senior must not receive 'Only the assigned reviewer...' after being escalated to."""
    junior_role = create_role(db, "junior", level=1)
    mid_role    = create_role(db, "mid",    level=2)
    senior_role = create_role(db, "senior", level=3)
    lead_role   = create_role(db, "lead",   level=4)

    creator  = create_user(db, role=junior_role, label="junior")
    mid_user = create_user(db, role=mid_role,    label="mid")
    senior   = create_user(db, role=senior_role, label="senior")
    lead     = create_user(db, role=lead_role,   label="lead")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=mid_user.id)

    login_user(mid_user)
    r = _escalate(client, req.id, senior.id)
    assert r.status_code == 200, r.text

    db.refresh(req)
    assert req.assigned_reviewer_id == senior.id

    login_user(senior)
    r = _escalate(client, req.id, lead.id)
    assert r.status_code == 200, r.text

    db.refresh(req)
    assert req.assigned_reviewer_id == lead.id
    assert req.status == RequestStatus.PENDING_REVIEW

    actions = _review_actions(db, req.id)
    assert len(actions) == 2
    assert actions[0].actor_id == mid_user.id
    assert actions[0].target_reviewer_id == senior.id
    assert actions[1].actor_id == senior.id
    assert actions[1].target_reviewer_id == lead.id


# ===========================================================================
# C. DELEGATION — Allowed cases
# ===========================================================================

def test_delegate_senior_to_another_senior(
    client, db, create_role, create_user, login_user, seed_change_request
):
    mid_role    = create_role(db, "mid",    level=2)
    senior_role = create_role(db, "senior", level=3)

    creator  = create_user(db, role=mid_role,    label="mid")
    reviewer = create_user(db, role=senior_role, label="senior_a")
    target   = create_user(db, role=senior_role, label="senior_b")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=reviewer.id)
    login_user(reviewer)

    r = _delegate(client, req.id, target.id)
    assert r.status_code == 200, r.text

    db.refresh(req)
    assert req.assigned_reviewer_id == target.id
    assert req.current_reviewer_id  == target.id
    assert req.status == RequestStatus.PENDING_REVIEW


def test_delegate_lead_to_another_lead(
    client, db, create_role, create_user, login_user, seed_change_request
):
    mid_role  = create_role(db, "mid",  level=2)
    lead_role = create_role(db, "lead", level=4)

    creator  = create_user(db, role=mid_role,  label="mid")
    reviewer = create_user(db, role=lead_role, label="lead_a")
    target   = create_user(db, role=lead_role, label="lead_b")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=reviewer.id)
    login_user(reviewer)

    r = _delegate(client, req.id, target.id)
    assert r.status_code == 200, r.text

    db.refresh(req)
    assert req.assigned_reviewer_id == target.id


def test_delegate_mid_to_mid_for_junior_low(
    client, db, create_role, create_user, login_user, seed_change_request
):
    """Mid is eligible for junior+low, so mid->mid delegation is allowed."""
    junior_role = create_role(db, "junior", level=1)
    mid_role    = create_role(db, "mid",    level=2)

    creator  = create_user(db, role=junior_role, label="junior")
    reviewer = create_user(db, role=mid_role,    label="mid_a")
    target   = create_user(db, role=mid_role,    label="mid_b")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=reviewer.id, risk_level=RiskLevel.LOW)
    login_user(reviewer)

    r = _delegate(client, req.id, target.id)
    assert r.status_code == 200, r.text

    db.refresh(req)
    assert req.assigned_reviewer_id == target.id


# ===========================================================================
# C. DELEGATION — Regression 6: higher reviewer must not delegate down
# ===========================================================================

def test_delegate_senior_to_mid_forbidden(
    client, db, create_role, create_user, login_user, seed_change_request
):
    """Regression 6 — senior cannot delegate down to mid."""
    junior_role = create_role(db, "junior", level=1)
    mid_role    = create_role(db, "mid",    level=2)
    senior_role = create_role(db, "senior", level=3)

    creator  = create_user(db, role=junior_role, label="junior")
    reviewer = create_user(db, role=senior_role, label="senior")
    target   = create_user(db, role=mid_role,    label="mid")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=reviewer.id)
    login_user(reviewer)

    r = _delegate(client, req.id, target.id)
    assert r.status_code == 400, r.text
    assert "lower" in r.json()["detail"].lower()

    db.refresh(req)
    assert req.assigned_reviewer_id == reviewer.id
    assert len(_review_actions(db, req.id)) == 0


def test_delegate_lead_to_senior_forbidden(
    client, db, create_role, create_user, login_user, seed_change_request
):
    mid_role    = create_role(db, "mid",    level=2)
    senior_role = create_role(db, "senior", level=3)
    lead_role   = create_role(db, "lead",   level=4)

    creator  = create_user(db, role=mid_role,    label="mid")
    reviewer = create_user(db, role=lead_role,   label="lead")
    target   = create_user(db, role=senior_role, label="senior")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=reviewer.id)
    login_user(reviewer)

    r = _delegate(client, req.id, target.id)
    assert r.status_code == 400, r.text

    db.refresh(req)
    assert req.assigned_reviewer_id == reviewer.id
    assert len(_review_actions(db, req.id)) == 0


def test_delegate_mid_to_junior_forbidden(
    client, db, create_role, create_user, login_user, seed_change_request
):
    junior_role = create_role(db, "junior", level=1)
    mid_role    = create_role(db, "mid",    level=2)

    creator  = create_user(db, role=junior_role, label="junior_creator")
    reviewer = create_user(db, role=mid_role,    label="mid")
    target   = create_user(db, role=junior_role, label="junior_target")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=reviewer.id)
    login_user(reviewer)

    r = _delegate(client, req.id, target.id)
    assert r.status_code == 400, r.text

    db.refresh(req)
    assert req.assigned_reviewer_id == reviewer.id
    assert len(_review_actions(db, req.id)) == 0


def test_delegate_higher_role_forbidden_use_escalation(
    client, db, create_role, create_user, login_user, seed_change_request
):
    """Delegation to a higher role must be blocked; escalation should be used instead."""
    junior_role = create_role(db, "junior", level=1)
    mid_role    = create_role(db, "mid",    level=2)
    lead_role   = create_role(db, "lead",   level=4)

    creator  = create_user(db, role=junior_role, label="junior")
    reviewer = create_user(db, role=mid_role,    label="mid")
    target   = create_user(db, role=lead_role,   label="lead")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=reviewer.id)
    login_user(reviewer)

    r = _delegate(client, req.id, target.id)
    assert r.status_code == 400, r.text
    assert "higher" in r.json()["detail"].lower() or "escalation" in r.json()["detail"].lower()


# ===========================================================================
# C. DELEGATION — Forbidden (other reasons)
# ===========================================================================

def test_delegate_to_requester_forbidden(
    client, db, create_role, create_user, login_user, seed_change_request
):
    mid_role    = create_role(db, "mid",    level=2)
    senior_role = create_role(db, "senior", level=3)

    creator  = create_user(db, role=mid_role,    label="mid_creator")
    reviewer = create_user(db, role=senior_role, label="senior")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=reviewer.id)
    login_user(reviewer)

    r = _delegate(client, req.id, creator.id)
    assert r.status_code == 400, r.text
    assert "creator" in r.json()["detail"].lower()

    db.refresh(req)
    assert req.assigned_reviewer_id == reviewer.id


def test_delegate_to_inactive_user_forbidden(
    client, db, create_role, create_user, login_user, seed_change_request
):
    mid_role    = create_role(db, "mid",    level=2)
    senior_role = create_role(db, "senior", level=3)

    creator  = create_user(db, role=mid_role,    label="mid")
    reviewer = create_user(db, role=senior_role, label="senior_a")
    target   = create_user(db, role=senior_role, label="senior_inactive")
    target.is_active = False
    db.commit()

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=reviewer.id)
    login_user(reviewer)

    r = _delegate(client, req.id, target.id)
    assert r.status_code == 404, r.text

    db.refresh(req)
    assert req.assigned_reviewer_id == reviewer.id


def test_delegate_to_self_forbidden(
    client, db, create_role, create_user, login_user, seed_change_request
):
    mid_role    = create_role(db, "mid",    level=2)
    senior_role = create_role(db, "senior", level=3)

    creator  = create_user(db, role=mid_role,    label="mid")
    reviewer = create_user(db, role=senior_role, label="senior")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=reviewer.id)
    login_user(reviewer)

    r = _delegate(client, req.id, reviewer.id)
    assert r.status_code == 400, r.text
    assert "yourself" in r.json()["detail"].lower()


def test_delegate_non_pending_request_forbidden(
    client, db, create_role, create_user, login_user, seed_change_request
):
    mid_role    = create_role(db, "mid",    level=2)
    senior_role = create_role(db, "senior", level=3)

    creator  = create_user(db, role=mid_role,    label="mid")
    reviewer = create_user(db, role=senior_role, label="senior_a")
    target   = create_user(db, role=senior_role, label="senior_b")

    req = seed_change_request(
        db,
        creator_id=creator.id,
        reviewer_id=reviewer.id,
        status=RequestStatus.APPROVED,
    )
    login_user(reviewer)

    r = _delegate(client, req.id, target.id)
    assert r.status_code == 400, r.text
    assert len(_review_actions(db, req.id)) == 0


def test_delegate_by_non_assigned_reviewer_forbidden(
    client, db, create_role, create_user, login_user, seed_change_request
):
    mid_role    = create_role(db, "mid",    level=2)
    senior_role = create_role(db, "senior", level=3)

    creator  = create_user(db, role=mid_role,    label="mid")
    reviewer = create_user(db, role=senior_role, label="senior_assigned")
    outsider = create_user(db, role=senior_role, label="senior_outsider")
    target   = create_user(db, role=senior_role, label="senior_target")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=reviewer.id)
    login_user(outsider)

    r = _delegate(client, req.id, target.id)
    assert r.status_code == 403, r.text
    assert len(_review_actions(db, req.id)) == 0


# ===========================================================================
# C. DELEGATION — Post-success: creates review action, locks previous reviewer
# ===========================================================================

def test_delegate_creates_review_action_record(
    client, db, create_role, create_user, login_user, seed_change_request
):
    mid_role    = create_role(db, "mid",    level=2)
    senior_role = create_role(db, "senior", level=3)

    creator  = create_user(db, role=mid_role,    label="mid")
    reviewer = create_user(db, role=senior_role, label="senior_a")
    target   = create_user(db, role=senior_role, label="senior_b")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=reviewer.id)
    login_user(reviewer)
    r = _delegate(client, req.id, target.id, "vacation cover")
    assert r.status_code == 200

    actions = _review_actions(db, req.id)
    assert len(actions) == 1
    a = actions[0]
    assert a.action_type.value == "delegate"
    assert a.actor_id == reviewer.id
    assert a.target_reviewer_id == target.id
    assert a.comment == "vacation cover"


def test_previous_reviewer_locked_out_after_delegation(
    client, db, create_role, create_user, login_user, seed_change_request
):
    """Regression 4 (delegation) — previous reviewer cannot act after delegating."""
    mid_role    = create_role(db, "mid",    level=2)
    senior_role = create_role(db, "senior", level=3)

    creator  = create_user(db, role=mid_role,    label="mid")
    reviewer = create_user(db, role=senior_role, label="senior_a")
    target   = create_user(db, role=senior_role, label="senior_b")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=reviewer.id)

    login_user(reviewer)
    assert _delegate(client, req.id, target.id).status_code == 200

    # reviewer_a can no longer approve
    login_user(reviewer)
    assert client.post(f"/change-requests/{req.id}/approve", json={}).status_code == 403

    # reviewer_a can no longer reject
    assert client.post(f"/change-requests/{req.id}/reject", json={}).status_code == 403

    # reviewer_b (new) can approve
    login_user(target)
    assert client.post(f"/change-requests/{req.id}/approve", json={}).status_code == 200


# ===========================================================================
# F. Atomicity — failed operations must not mutate DB (Regression 3)
# ===========================================================================

def test_failed_escalate_does_not_mutate_request(
    client, db, create_role, create_user, login_user, seed_change_request
):
    """Regression 3 — same-role escalation failure leaves request unchanged."""
    junior_role = create_role(db, "junior", level=1)
    mid_role    = create_role(db, "mid",    level=2)

    creator  = create_user(db, role=junior_role, label="junior")
    reviewer = create_user(db, role=mid_role,    label="mid_a")
    target   = create_user(db, role=mid_role,    label="mid_b")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=reviewer.id)

    login_user(reviewer)
    r = _escalate(client, req.id, target.id)
    assert r.status_code == 400

    db.refresh(req)
    assert req.assigned_reviewer_id == reviewer.id
    assert req.status == RequestStatus.PENDING_REVIEW
    assert len(_review_actions(db, req.id)) == 0


def test_failed_delegate_does_not_mutate_request(
    client, db, create_role, create_user, login_user, seed_change_request
):
    """Regression 3 — lower-role delegation failure leaves request unchanged."""
    junior_role = create_role(db, "junior", level=1)
    mid_role    = create_role(db, "mid",    level=2)
    senior_role = create_role(db, "senior", level=3)

    creator  = create_user(db, role=junior_role, label="junior")
    reviewer = create_user(db, role=senior_role, label="senior")
    target   = create_user(db, role=mid_role,    label="mid")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=reviewer.id)

    login_user(reviewer)
    r = _delegate(client, req.id, target.id)
    assert r.status_code == 400

    db.refresh(req)
    assert req.assigned_reviewer_id == reviewer.id
    assert req.status == RequestStatus.PENDING_REVIEW
    assert len(_review_actions(db, req.id)) == 0


def test_failed_approve_does_not_mutate_request(
    client, db, create_role, create_user, login_user, seed_change_request
):
    """Regression 3 — ineligible approval leaves status unchanged."""
    junior_role = create_role(db, "junior", level=1)
    mid_role    = create_role(db, "mid",    level=2)
    lead_role   = create_role(db, "lead",   level=4)

    creator  = create_user(db, role=junior_role, label="junior")
    reviewer = create_user(db, role=lead_role,   label="lead")
    intruder = create_user(db, role=mid_role,    label="mid")

    # junior+high: eligible = ["senior","lead"] — mid is not eligible
    req = _pending(
        db, seed_change_request,
        creator_id=creator.id,
        reviewer_id=reviewer.id,
        risk_level=RiskLevel.HIGH,
    )
    login_user(intruder)

    r = client.post(f"/change-requests/{req.id}/approve", json={})
    assert r.status_code == 403

    db.refresh(req)
    assert req.status == RequestStatus.PENDING_REVIEW
    assert req.assigned_reviewer_id == reviewer.id


# ===========================================================================
# E. Review history visible — Regression 5
# ===========================================================================

def test_new_reviewer_sees_review_history_after_escalation(
    client, db, create_role, create_user, login_user, seed_change_request
):
    """Regression 5 — new reviewer must not receive empty review history."""
    junior_role = create_role(db, "junior", level=1)
    mid_role    = create_role(db, "mid",    level=2)
    senior_role = create_role(db, "senior", level=3)

    creator  = create_user(db, role=junior_role, label="junior")
    mid_user = create_user(db, role=mid_role,    label="mid")
    senior   = create_user(db, role=senior_role, label="senior")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=mid_user.id)

    login_user(mid_user)
    r = _escalate(client, req.id, senior.id, "needs senior input")
    assert r.status_code == 200

    login_user(senior)
    r = client.get(f"/change-requests/{req.id}/review-actions")
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data) == 1
    assert data[0]["action_type"] == "escalate"
    assert data[0]["actor"]["id"] == mid_user.id
    assert data[0]["target_reviewer"]["id"] == senior.id
    assert data[0]["comment"] == "needs senior input"


def test_review_history_contains_both_escalations_in_chain(
    client, db, create_role, create_user, login_user, seed_change_request
):
    """Regression 5 — after mid->senior->lead chain, lead sees both records in order."""
    junior_role = create_role(db, "junior", level=1)
    mid_role    = create_role(db, "mid",    level=2)
    senior_role = create_role(db, "senior", level=3)
    lead_role   = create_role(db, "lead",   level=4)

    creator  = create_user(db, role=junior_role, label="junior")
    mid_user = create_user(db, role=mid_role,    label="mid")
    senior   = create_user(db, role=senior_role, label="senior")
    lead     = create_user(db, role=lead_role,   label="lead")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=mid_user.id)

    login_user(mid_user)
    _escalate(client, req.id, senior.id, "step 1")

    login_user(senior)
    _escalate(client, req.id, lead.id, "step 2")

    login_user(lead)
    r = client.get(f"/change-requests/{req.id}/review-actions")
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data) == 2
    assert data[0]["actor"]["id"] == mid_user.id
    assert data[0]["target_reviewer"]["id"] == senior.id
    assert data[1]["actor"]["id"] == senior.id
    assert data[1]["target_reviewer"]["id"] == lead.id


# ===========================================================================
# B. Assigned reviewer lock — non-current reviewer cannot act when locked
# ===========================================================================

def test_eligible_non_current_reviewer_cannot_approve_when_locked(
    client, db, create_role, create_user, login_user, seed_change_request
):
    """After escalation, only the current reviewer may approve — other eligibles are blocked."""
    junior_role = create_role(db, "junior", level=1)
    mid_role    = create_role(db, "mid",    level=2)
    senior_role = create_role(db, "senior", level=3)

    creator       = create_user(db, role=junior_role, label="junior")
    mid_user      = create_user(db, role=mid_role,    label="mid")
    senior_locked = create_user(db, role=senior_role, label="senior_locked")
    senior_other  = create_user(db, role=senior_role, label="senior_other")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=mid_user.id)

    login_user(mid_user)
    _escalate(client, req.id, senior_locked.id)

    # senior_other is eligible by role but not current reviewer
    login_user(senior_other)
    assert client.post(f"/change-requests/{req.id}/approve", json={}).status_code == 403


def test_eligible_non_current_reviewer_cannot_reject_when_locked(
    client, db, create_role, create_user, login_user, seed_change_request
):
    junior_role = create_role(db, "junior", level=1)
    mid_role    = create_role(db, "mid",    level=2)
    senior_role = create_role(db, "senior", level=3)

    creator       = create_user(db, role=junior_role, label="junior")
    mid_user      = create_user(db, role=mid_role,    label="mid")
    senior_locked = create_user(db, role=senior_role, label="senior_locked")
    senior_other  = create_user(db, role=senior_role, label="senior_other")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=mid_user.id)

    login_user(mid_user)
    _escalate(client, req.id, senior_locked.id)

    login_user(senior_other)
    assert client.post(f"/change-requests/{req.id}/reject", json={}).status_code == 403


def test_eligible_non_current_reviewer_cannot_delegate_when_locked(
    client, db, create_role, create_user, login_user, seed_change_request
):
    junior_role = create_role(db, "junior", level=1)
    mid_role    = create_role(db, "mid",    level=2)
    senior_role = create_role(db, "senior", level=3)

    creator       = create_user(db, role=junior_role, label="junior")
    mid_user      = create_user(db, role=mid_role,    label="mid")
    senior_locked = create_user(db, role=senior_role, label="senior_locked")
    senior_other  = create_user(db, role=senior_role, label="senior_other")
    senior_target = create_user(db, role=senior_role, label="senior_target")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=mid_user.id)

    login_user(mid_user)
    _escalate(client, req.id, senior_locked.id)

    login_user(senior_other)
    assert _delegate(client, req.id, senior_target.id).status_code == 403


# ===========================================================================
# Only the current reviewer (or an admin) may escalate or delegate
# ===========================================================================

@pytest.fixture
def escalated_request(db, create_role, create_user, login_user, seed_change_request, client):
    """Pending junior request, escalated by its assigned reviewer A (mid) to B (senior)."""
    roles = {name: create_role(db, name, level=lvl) for name, lvl in
             [("junior", 1), ("mid", 2), ("senior", 3), ("lead", 4), ("admin", 5)]}
    people = {
        "creator": create_user(db, role=roles["junior"], label="creator"),
        "a": create_user(db, role=roles["mid"], label="reviewer_a"),
        "b": create_user(db, role=roles["senior"], label="reviewer_b"),
        "other_mid": create_user(db, role=roles["mid"], label="other_mid"),
        "other_senior": create_user(db, role=roles["senior"], label="other_senior"),
        "lead": create_user(db, role=roles["lead"], label="lead"),
        "admin": create_user(db, role=roles["admin"], label="admin"),
    }
    req = _pending(db, seed_change_request, creator_id=people["creator"].id, reviewer_id=people["a"].id)

    login_user(people["a"])
    assert _escalate(client, req.id, people["b"].id).status_code == 200
    db.refresh(req)
    assert req.current_reviewer_id == people["b"].id
    return {"req": req, "roles": roles, **people}


@pytest.mark.parametrize("action,target", [("escalate", "lead"), ("delegate", "other_mid")])
def test_original_reviewer_cannot_escalate_or_delegate_after_escalation(
    client, db, login_user, escalated_request, action, target
):
    ctx = escalated_request
    actions_before = len(_review_actions(db, ctx["req"].id))

    login_user(ctx["a"])
    transfer = _escalate if action == "escalate" else _delegate
    response = transfer(client, ctx["req"].id, ctx[target].id)

    assert response.status_code == 403
    assert response.json()["detail"] == f"Only the current reviewer or admin can {action}"
    db.refresh(ctx["req"])
    assert ctx["req"].current_reviewer_id == ctx["b"].id
    assert len(_review_actions(db, ctx["req"].id)) == actions_before


@pytest.mark.parametrize("action,target", [("escalate", "lead"), ("delegate", "other_mid")])
def test_assigned_reviewer_loses_transfer_right_once_current_reviewer_is_set(
    client, db, login_user, escalated_request, action, target
):
    # The rule must hold even if assigned_reviewer_id still names A while
    # current_reviewer_id names B (the API sets both, but the check may not rely on it).
    ctx = escalated_request
    ctx["req"].assigned_reviewer_id = ctx["a"].id
    db.commit()

    login_user(ctx["a"])
    transfer = _escalate if action == "escalate" else _delegate
    response = transfer(client, ctx["req"].id, ctx[target].id)

    assert response.status_code == 403
    db.refresh(ctx["req"])
    assert (ctx["req"].assigned_reviewer_id, ctx["req"].current_reviewer_id) == (ctx["a"].id, ctx["b"].id)


@pytest.mark.parametrize("action,target", [("escalate", "lead"), ("delegate", "other_senior")])
def test_current_reviewer_can_still_escalate_or_delegate_after_escalation(
    client, db, login_user, escalated_request, action, target
):
    ctx = escalated_request

    login_user(ctx["b"])
    transfer = _escalate if action == "escalate" else _delegate
    response = transfer(client, ctx["req"].id, ctx[target].id)

    assert response.status_code == 200, response.text
    db.refresh(ctx["req"])
    assert ctx["req"].current_reviewer_id == ctx[target].id


@pytest.mark.parametrize("action", ["escalate", "delegate"])
def test_admin_is_not_blocked_by_current_reviewer_rule(client, login_user, escalated_request, action):
    # The admin is neither assigned nor current reviewer, yet passes the permission
    # check. On a junior's request the hierarchy/matrix rules then refuse the
    # transfer itself (400), which is not a permission denial.
    ctx = escalated_request

    login_user(ctx["admin"])
    transfer = _escalate if action == "escalate" else _delegate
    response = transfer(client, ctx["req"].id, ctx["lead"].id)

    assert response.status_code == 400, response.text


def test_admin_can_delegate_request_held_by_another_admin(
    client, db, create_role, create_user, login_user, seed_change_request
):
    admin_role = create_role(db, "admin", level=5)
    creator = create_user(db, role=admin_role, label="admin_creator")
    holder = create_user(db, role=admin_role, label="admin_holder")
    acting = create_user(db, role=admin_role, label="admin_acting")
    target = create_user(db, role=admin_role, label="admin_target")

    req = _pending(db, seed_change_request, creator_id=creator.id, reviewer_id=holder.id)
    req.current_reviewer_id = holder.id
    db.commit()

    login_user(acting)
    response = _delegate(client, req.id, target.id)

    assert response.status_code == 200, response.text
    db.refresh(req)
    assert req.current_reviewer_id == target.id
