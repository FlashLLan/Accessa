"""Text that users write never ends up in audit_logs; it stays in its own table."""
import pytest

from backend.models.approval import Approval
from backend.models.audit_log import AuditLog
from backend.models.comment import Comment
from backend.models.review_action import ReviewAction

MARK = "ZQX-user-text-7731"


@pytest.fixture
def people(db, create_role, create_user):
    roles = {name: create_role(db, name, level=lvl) for name, lvl in
             [("junior", 1), ("mid", 2), ("senior", 3), ("lead", 4), ("admin", 5)]}
    return {name: create_user(db, role=roles[name], label=name) for name in roles}


def _create(client, people, **extra):
    body = {
        "title": f"Title {MARK}", "description": f"Description {MARK}", "request_type": "code_change",
        "target_system": "api", "environment": "development", "risk_level": "low",
        "assigned_reviewer_id": people["mid"].id, **extra,
    }
    response = client.post("/change-requests/", json=body)
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _audit_text(db):
    rows = db.query(AuditLog).all()
    return rows, [" | ".join(filter(None, [r.details, r.old_value, r.new_value, r.actor_role])) for r in rows]


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_decision_comment_never_appears_in_audit_logs(client, db, people, login_user, decision):
    login_user(people["junior"])
    request_id = _create(client, people)
    assert client.post(f"/change-requests/{request_id}/submit").status_code == 200

    login_user(people["mid"])
    comment = f"Decision comment {MARK}"
    assert client.post(f"/change-requests/{request_id}/{decision}",
                       json={"decision_comment": comment}).status_code == 200

    action = {"approve": "REQUEST_APPROVED", "reject": "REQUEST_REJECTED"}[decision]
    entry = db.query(AuditLog).filter(AuditLog.action == action).one()
    assert "comment=yes" in entry.details
    assert MARK not in entry.details
    # The text itself stays in the approvals table.
    assert db.query(Approval).filter(Approval.change_request_id == request_id).one().decision_comment == comment


@pytest.mark.parametrize("comment", [None, "", "   "])
def test_missing_or_blank_decision_comment_is_recorded_as_no(client, db, people, login_user, comment):
    login_user(people["junior"])
    request_id = _create(client, people)
    client.post(f"/change-requests/{request_id}/submit")
    login_user(people["mid"])
    body = {} if comment is None else {"decision_comment": comment}
    assert client.post(f"/change-requests/{request_id}/approve", json=body).status_code == 200
    assert "comment=no" in db.query(AuditLog).filter(AuditLog.action == "REQUEST_APPROVED").one().details


def test_no_user_written_text_in_any_audit_entry(client, db, people, login_user):
    # Every free-text field a user can fill in carries MARK.
    login_user(people["junior"])
    # Git identifiers (URLs, branches, commit) are logged on purpose; the diff,
    # the file summary and the repository name are free text.
    request_id = _create(client, people, git_context={
        "provider": "github", "repository_name": f"repo-{MARK}", "branch_name": "feature/x",
        "target_branch": "main", "commit_hash": "abc1234",
        "repository_url": "https://github.com/octo/demo",
        "pull_request_url": "https://github.com/octo/demo/pull/1",
        "changed_files_summary": f"files {MARK}", "diff_text": f"+{MARK}",
    })
    assert client.patch(f"/change-requests/{request_id}",
                        json={"title": f"New title {MARK}", "description": f"New description {MARK}"}).status_code == 200
    assert client.post(f"/change-requests/{request_id}/git-context",
                       json={"branch_name": "feature/y", "diff_text": f"-{MARK}"}).status_code == 200
    assert client.post(f"/change-requests/{request_id}/submit").status_code == 200
    assert client.post(f"/change-requests/{request_id}/comments",
                       json={"comment_text": f"Comment {MARK}"}).status_code == 200
    assert client.put("/users/me", json={"full_name": f"Junior {MARK}"}).status_code == 200

    login_user(people["mid"])
    assert client.post(f"/change-requests/{request_id}/escalate",
                       json={"target_reviewer_id": people["senior"].id, "comment": f"Escalation {MARK}"}).status_code == 200
    login_user(people["senior"])
    assert client.post(f"/change-requests/{request_id}/approve",
                       json={"decision_comment": f"Approval {MARK}"}).status_code == 200

    rows, texts = _audit_text(db)
    actions = {r.action for r in rows}
    assert {"REQUEST_CREATED", "GIT_CONTEXT_LINKED", "REQUEST_UPDATED", "GIT_CONTEXT_UPDATED",
            "REQUEST_SUBMITTED", "COMMENT_CREATED", "PROFILE_UPDATED", "REQUEST_ESCALATED",
            "REQUEST_APPROVED"} <= actions, actions
    leaks = [(r.action, t) for r, t in zip(rows, texts) if MARK in t]
    assert leaks == []

    # Git context entries carry the identifiers, never the diff or summary.
    linked = next(t for r, t in zip(rows, texts) if r.action == "GIT_CONTEXT_LINKED")
    assert "branch_name=feature/x" in linked and "repository_url=https://github.com/octo/demo" in linked
    updated = next(r for r in rows if r.action == "GIT_CONTEXT_UPDATED")
    assert (updated.old_value, updated.new_value) == ("branch_name=feature/x", "branch_name=feature/y")
    assert "also sent: diff_text" in updated.details

    # The texts are still stored where they belong.
    assert db.query(Comment).filter(Comment.comment_text == f"Comment {MARK}").count() == 1
    assert db.query(ReviewAction).filter(ReviewAction.comment == f"Escalation {MARK}").count() == 1
    assert db.query(Approval).filter(Approval.decision_comment == f"Approval {MARK}").count() == 1
