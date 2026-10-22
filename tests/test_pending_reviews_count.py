"""GET /users/me reports how many requests wait for the user's review (drives the Review nav item)."""
import pytest

from backend.models.enums import RequestStatus


@pytest.fixture
def people(db, create_role, create_user):
    roles = {name: create_role(db, name, level=lvl) for name, lvl in
             [("junior", 1), ("mid", 2), ("senior", 3), ("lead", 4), ("admin", 5)]}
    return {name: create_user(db, role=roles[name], label=name) for name in roles} | {"roles": roles}


def _count(client, login_user, user):
    login_user(user)
    response = client.get("/users/me")
    assert response.status_code == 200
    return response.json()["pending_reviews_count"]


def test_counts_only_pending_requests_assigned_to_me(client, db, people, login_user, seed_change_request):
    junior, mid = people["junior"], people["mid"]
    assert _count(client, login_user, mid) == 0

    # A mid reviewer (junior, low risk) with two pending requests ...
    for _ in range(2):
        seed_change_request(db, creator_id=junior.id, reviewer_id=mid.id, status=RequestStatus.PENDING_REVIEW)
    # ... and others that do not wait for a decision.
    for status in (RequestStatus.DRAFT, RequestStatus.APPROVED, RequestStatus.REJECTED, RequestStatus.APPLIED):
        seed_change_request(db, creator_id=junior.id, reviewer_id=mid.id, status=status)
    seed_change_request(db, creator_id=junior.id, reviewer_id=people["senior"].id, status=RequestStatus.PENDING_REVIEW)

    assert _count(client, login_user, mid) == 2
    assert _count(client, login_user, people["senior"]) == 1
    assert _count(client, login_user, junior) == 0  # the creator, not the reviewer


def test_count_follows_escalation(client, db, people, login_user, seed_change_request):
    req = seed_change_request(db, creator_id=people["junior"].id, reviewer_id=people["mid"].id,
                              status=RequestStatus.PENDING_REVIEW)
    login_user(people["mid"])
    assert client.post(f"/change-requests/{req.id}/escalate",
                       json={"target_reviewer_id": people["senior"].id}).status_code == 200
    assert _count(client, login_user, people["mid"]) == 0
    assert _count(client, login_user, people["senior"]) == 1


def test_count_is_workspace_scoped(client, db, people, login_user, seed_change_request,
                                   create_workspace, create_user):
    other = create_workspace(db, "Other", "other-ws")
    creator = create_user(db, role=people["roles"]["junior"], label="other-junior", workspace=other)
    reviewer = create_user(db, role=people["roles"]["mid"], label="other-mid", workspace=other)
    seed_change_request(db, creator_id=creator.id, reviewer_id=reviewer.id, status=RequestStatus.PENDING_REVIEW)
    assert _count(client, login_user, people["mid"]) == 0
    assert _count(client, login_user, reviewer) == 1
