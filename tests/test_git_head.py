"""GET /change-requests/{id}/git-context/head: does the PR have commits beyond the
submitted snapshot? (GitHub mocked; the request still covers only the stored commit.)"""
from unittest.mock import patch

import httpx
import pytest

from ai_review_helpers import OTHER_SHA, PR_URL, SHA, FakeGitHub
from backend.models.audit_log import AuditLog
from backend.models.enums import GitContextSource, RequestStatus
from backend.models.git_context import GitContext
from backend.services import pull_request_data
from backend.services.github_service import GitHubClient


@pytest.fixture
def people(db, create_role, create_user):
    roles = {name: create_role(db, name, level=lvl) for name, lvl in [("junior", 1), ("mid", 2), ("admin", 5)]}
    return {"creator": create_user(db, role=roles["junior"], label="creator"),
            "reviewer": create_user(db, role=roles["mid"], label="reviewer"),
            "outsider": create_user(db, role=roles["mid"], label="outsider"),
            "admin": create_user(db, role=roles["admin"], label="admin")}


@pytest.fixture
def submitted(db, people, seed_change_request):
    req = seed_change_request(db, creator_id=people["creator"].id, reviewer_id=people["reviewer"].id,
                              status=RequestStatus.PENDING_REVIEW)
    db.add(GitContext(change_request_id=req.id, pull_request_url=PR_URL, source=GitContextSource.GITHUB,
                      commit_hash=OTHER_SHA, diff_text="+x"))
    db.commit()
    return req


def _github(github):
    return patch.object(pull_request_data, "GitHubClient",
                        lambda: GitHubClient(token="", transport=httpx.MockTransport(github)))


def _head(client, req, github):
    with _github(github):
        return client.get(f"/change-requests/{req.id}/git-context/head")


@pytest.mark.parametrize("reader", ["creator", "reviewer", "admin"])
def test_moved_head_is_reported(client, people, submitted, login_user, reader):
    login_user(people[reader])
    github = FakeGitHub({}, [], head_sha=SHA)
    response = _head(client, submitted, github)
    assert response.status_code == 200
    assert response.json() == {"applicable": True, "stored_commit": OTHER_SHA, "current_head": SHA, "head_moved": True}
    assert [r.url.path for r in github.requests] == ["/repos/octo/demo/pulls/7"]  # one GitHub call


def test_unchanged_head_is_not_reported(client, people, submitted, login_user):
    login_user(people["reviewer"])
    body = _head(client, submitted, FakeGitHub({}, [], head_sha=OTHER_SHA)).json()
    assert body["head_moved"] is False and body["current_head"] == OTHER_SHA


@pytest.mark.parametrize("failure", [httpx.Response(404), httpx.Response(503), "timeout"])
def test_github_failure_is_quiet(client, people, submitted, login_user, failure):
    def fail(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("slow", request=request)
        return failure
    login_user(people["reviewer"])
    response = _head(client, submitted, FakeGitHub({}, [], fail=fail))
    assert response.status_code == 200
    assert response.json() == {"applicable": True, "stored_commit": OTHER_SHA, "current_head": None, "head_moved": False}


def test_manual_git_data_is_not_checked(client, db, people, submitted, login_user):
    git = submitted.git_context
    git.source = GitContextSource.MANUAL
    db.commit()
    login_user(people["reviewer"])
    github = FakeGitHub({}, [])
    assert _head(client, submitted, github).json()["applicable"] is False
    assert github.requests == []


def test_outsider_cannot_check(client, people, submitted, login_user):
    login_user(people["outsider"])
    assert _head(client, submitted, FakeGitHub({}, [])).status_code == 403


@pytest.mark.parametrize("decision, action", [("approve", "REQUEST_APPROVED"), ("reject", "REQUEST_REJECTED")])
def test_decision_audit_contains_the_commit(client, db, people, submitted, login_user, decision, action):
    login_user(people["reviewer"])
    assert client.post(f"/change-requests/{submitted.id}/{decision}", json={"decision_comment": "ok"}).status_code == 200
    details = db.query(AuditLog).filter(AuditLog.action == action).one().details
    assert f"commit={OTHER_SHA} (github)" in details


def test_decision_audit_without_git_data(client, db, people, seed_change_request, login_user):
    req = seed_change_request(db, creator_id=people["creator"].id, reviewer_id=people["reviewer"].id,
                              status=RequestStatus.PENDING_REVIEW)
    login_user(people["reviewer"])
    client.post(f"/change-requests/{req.id}/approve", json={})
    assert "commit=none" in db.query(AuditLog).filter(AuditLog.action == "REQUEST_APPROVED").one().details
