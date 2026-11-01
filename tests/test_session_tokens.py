"""Real access tokens (no get_current_user override):

- an expired access token is rejected;
- a role change by an admin takes effect on the next request with the token the
  user already holds: permissions come from the database, not from the token.
"""
from datetime import timedelta

import jwt
import pytest

from backend.core.security import ALGORITHM, SECRET_KEY, TOKEN_TYPE_ACCESS, create_access_token
from backend.core.timeutils import utc_now
from backend.models.approval import Approval
from backend.models.change_request import ChangeRequest
from backend.models.enums import RequestStatus, RiskLevel


def _token(user):
    return create_access_token({"sub": str(user.id), "workspace": str(user.workspace.public_id)})


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def people(db, create_role, create_user):
    roles = {name: create_role(db, name, level=lvl) for name, lvl in
             [("junior", 1), ("mid", 2), ("senior", 3), ("lead", 4), ("admin", 5)]}
    users = {
        "admin": create_user(db, role=roles["admin"], label="admin"),
        "junior": create_user(db, role=roles["junior"], label="junior"),
        "senior": create_user(db, role=roles["senior"], label="senior"),
        "other_senior": create_user(db, role=roles["senior"], label="other_senior"),
    }
    for user in users.values():
        user.is_active = True
        user.must_change_password = False
        user.mfa_enabled = True
    db.commit()
    return {"roles": roles, **users}


def _change_role(client, people, user, role_name):
    response = client.patch(
        f"/users/{user.id}/role",
        json={"role_id": people["roles"][role_name].id},
        headers=_auth(_token(people["admin"])),
    )
    assert response.status_code == 200, response.text


def test_expired_access_token_is_rejected(client, people):
    user = people["senior"]
    expired = jwt.encode(
        {
            "sub": str(user.id),
            "workspace": str(user.workspace.public_id),
            "type": TOKEN_TYPE_ACCESS,
            "exp": utc_now() - timedelta(minutes=1),
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )
    # The same user with a valid token gets through, so the 401 is the expiry alone.
    assert client.get("/users/me", headers=_auth(_token(user))).status_code == 200
    assert client.get("/users/me", headers=_auth(expired)).status_code == 401


def test_demotion_applies_to_a_token_issued_before_it(client, db, people, seed_change_request):
    senior = people["senior"]
    token = _token(senior)
    # Junior, low risk: a senior may approve it.
    req = seed_change_request(db, creator_id=people["junior"].id, reviewer_id=senior.id,
                              status=RequestStatus.PENDING_REVIEW, risk_level=RiskLevel.LOW)

    _change_role(client, people, senior, "junior")

    response = client.post(f"/change-requests/{req.id}/approve", json={}, headers=_auth(token))
    assert response.status_code == 403, response.text
    db.expire_all()
    unchanged = db.get(ChangeRequest, req.id)
    assert unchanged.status == RequestStatus.PENDING_REVIEW
    assert unchanged.closed_at is None
    assert db.query(Approval).filter(Approval.change_request_id == req.id).count() == 0


def test_promotion_applies_to_a_token_issued_before_it(client, db, people, seed_change_request):
    senior = people["senior"]
    token = _token(senior)
    # Senior, high risk: only a lead may approve it.
    req = seed_change_request(db, creator_id=people["other_senior"].id, reviewer_id=senior.id,
                              status=RequestStatus.PENDING_REVIEW, risk_level=RiskLevel.HIGH)
    assert client.post(f"/change-requests/{req.id}/approve", json={}, headers=_auth(token)).status_code == 403

    _change_role(client, people, senior, "lead")

    response = client.post(f"/change-requests/{req.id}/approve", json={}, headers=_auth(token))
    assert response.status_code == 200, response.text
    db.expire_all()
    assert db.get(ChangeRequest, req.id).status == RequestStatus.APPROVED
