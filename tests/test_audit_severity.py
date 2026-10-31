"""Critical audit severity: events where an admin should act now.

- MFA locked (10 wrong codes in a row: likely code guessing on a known password),
  covered in test_mfa.py;
- an admin account deactivated, or admin rights granted/taken away;
- MFA reset of an admin account;
- approval of a high-risk request.
The same actions on non-admin accounts / lower-risk requests stay high.
"""
import pytest

from backend.models.audit_log import AuditLog
from backend.models.enums import RequestStatus, RiskLevel


@pytest.fixture
def people(db, create_role, create_user):
    roles = {name: create_role(db, name, level=lvl) for name, lvl in
             [("junior", 1), ("mid", 2), ("senior", 3), ("lead", 4), ("admin", 5)]}
    return {
        "roles": roles,
        "admin": create_user(db, role=roles["admin"], label="admin"),
        "admin2": create_user(db, role=roles["admin"], label="admin2"),
        "junior": create_user(db, role=roles["junior"], label="junior"),
        "senior": create_user(db, role=roles["senior"], label="senior"),
    }


def _severity(db, action):
    return db.query(AuditLog).filter(AuditLog.action == action).order_by(AuditLog.id.desc()).first().severity


@pytest.mark.parametrize("target, expected", [("admin2", "critical"), ("junior", "high")])
def test_deactivation(client, db, people, login_user, target, expected):
    login_user(people["admin"])
    assert client.patch(f"/users/{people[target].id}/deactivate").status_code == 200
    assert _severity(db, "USER_DEACTIVATED") == expected


@pytest.mark.parametrize("target, new_role, expected", [
    ("junior", "admin", "critical"),   # admin rights granted
    ("admin2", "lead", "critical"),    # admin rights taken away
    ("junior", "senior", "high"),
])
def test_role_change(client, db, people, login_user, target, new_role, expected):
    login_user(people["admin"])
    response = client.patch(f"/users/{people[target].id}/role", json={"role_id": people["roles"][new_role].id})
    assert response.status_code == 200, response.text
    assert _severity(db, "ROLE_CHANGED") == expected


@pytest.mark.parametrize("target, expected", [("admin2", "critical"), ("junior", "high")])
def test_mfa_reset(client, db, people, login_user, target, expected):
    login_user(people["admin"])
    assert client.patch(f"/users/{people[target].id}/mfa-reset").status_code == 200
    assert _severity(db, "MFA_RESET") == expected


@pytest.mark.parametrize("risk, expected", [(RiskLevel.HIGH, "critical"), (RiskLevel.MEDIUM, "high"), (RiskLevel.LOW, "high")])
def test_approval(client, db, people, login_user, seed_change_request, risk, expected):
    req = seed_change_request(db, creator_id=people["junior"].id, reviewer_id=people["senior"].id,
                              status=RequestStatus.PENDING_REVIEW, risk_level=risk)
    login_user(people["senior"])
    response = client.post(f"/change-requests/{req.id}/approve", json={})
    assert response.status_code == 200, response.text
    assert _severity(db, "REQUEST_APPROVED") == expected


def test_rejection_of_a_high_risk_request_stays_high(client, db, people, login_user, seed_change_request):
    req = seed_change_request(db, creator_id=people["junior"].id, reviewer_id=people["senior"].id,
                              status=RequestStatus.PENDING_REVIEW, risk_level=RiskLevel.HIGH)
    login_user(people["senior"])
    assert client.post(f"/change-requests/{req.id}/reject", json={}).status_code == 200
    assert _severity(db, "REQUEST_REJECTED") == "high"
