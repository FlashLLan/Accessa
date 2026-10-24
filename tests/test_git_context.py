"""
Tests for Git-linked context on change requests.
Covers: creation with/without git_context, retrieval, validation, access control,
secret masking, and audit logging.
"""
import pytest
from backend.models.git_context import GitContext
from backend.models.enums import RequestStatus


# ── helpers ───────────────────────────────────────────────────────────────────

def _base_payload(reviewer_id):
    return {
        "title": "Deploy auth service",
        "description": "Deploy authentication update to staging.",
        "request_type": "deployment_change",
        "target_system": "Auth Service",
        "environment": "staging",
        "risk_level": "low",
        "assigned_reviewer_id": reviewer_id,
    }


def _add_git_context(db, request_id, **kwargs):
    defaults = {
        "provider": "github",
        "repository_url": "https://github.com/example/project",
        "branch_name": "feature/fix",
        "commit_hash": "abc123",
    }
    defaults.update(kwargs)
    gc = GitContext(change_request_id=request_id, **defaults)
    db.add(gc)
    db.commit()
    db.refresh(gc)
    return gc


# ── 1. Request can be created without Git context ─────────────────────────────

def test_create_request_without_git_context(client, db, create_user, create_role, login_user, seed_change_request):
    junior = create_role(db, "junior", level=1)
    senior = create_role(db, "senior", level=3)
    creator = create_user(db, role=junior, label="creator")
    reviewer = create_user(db, role=senior, label="reviewer")
    login_user(creator)

    payload = _base_payload(reviewer.id)
    response = client.post("/change-requests/", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["git_context"] is None


# ── 2. Request can be created with Git context ────────────────────────────────

def test_create_request_with_git_context(client, db, create_user, create_role, login_user):
    junior = create_role(db, "junior", level=1)
    senior = create_role(db, "senior", level=3)
    creator = create_user(db, role=junior, label="creator")
    reviewer = create_user(db, role=senior, label="reviewer")
    login_user(creator)

    payload = _base_payload(reviewer.id)
    payload["git_context"] = {
        "provider": "github",
        "repository_url": "https://github.com/example/project",
        "repository_name": "project",
        "branch_name": "feature/auth-fix",
        "target_branch": "main",
        "commit_hash": "abc123",
        "pull_request_url": "https://github.com/example/project/pull/12",
        "changed_files_summary": "backend/auth.py",
        "diff_text": "Updated session timeout handling.",
    }

    response = client.post("/change-requests/", json=payload)

    assert response.status_code == 200
    data = response.json()
    gc = data["git_context"]
    assert gc is not None
    assert gc["provider"] == "github"
    assert gc["branch_name"] == "feature/auth-fix"
    assert gc["commit_hash"] == "abc123"
    assert gc["pull_request_url"] == "https://github.com/example/project/pull/12"


# ── 3. Git context stored with correct change_request_id ─────────────────────

def test_git_context_stored_with_correct_change_request_id(client, db, create_user, create_role, login_user):
    junior = create_role(db, "junior", level=1)
    senior = create_role(db, "senior", level=3)
    creator = create_user(db, role=junior, label="creator")
    reviewer = create_user(db, role=senior, label="reviewer")
    login_user(creator)

    payload = _base_payload(reviewer.id)
    payload["git_context"] = {"branch_name": "fix/my-branch"}

    response = client.post("/change-requests/", json=payload)
    assert response.status_code == 200

    request_id = response.json()["id"]
    row = db.query(GitContext).filter(GitContext.change_request_id == request_id).first()
    assert row is not None
    assert row.change_request_id == request_id
    assert row.branch_name == "fix/my-branch"


# ── 4. Request details return git_context when it exists ─────────────────────

def test_request_details_return_git_context(client, db, create_user, create_role, login_user, seed_change_request):
    junior = create_role(db, "junior", level=1)
    senior = create_role(db, "senior", level=3)
    creator = create_user(db, role=junior, label="creator")
    reviewer = create_user(db, role=senior, label="reviewer")

    req = seed_change_request(db, creator_id=creator.id, reviewer_id=reviewer.id)
    _add_git_context(db, req.id, repository_url="https://github.com/example/repo")

    login_user(creator)
    response = client.get(f"/change-requests/{req.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["git_context"] is not None
    assert data["git_context"]["repository_url"] == "https://github.com/example/repo"


# ── 5. Request details work normally when git_context does not exist ──────────

def test_request_details_work_without_git_context(client, db, create_user, create_role, login_user, seed_change_request):
    junior = create_role(db, "junior", level=1)
    senior = create_role(db, "senior", level=3)
    creator = create_user(db, role=junior, label="creator")
    reviewer = create_user(db, role=senior, label="reviewer")

    req = seed_change_request(db, creator_id=creator.id, reviewer_id=reviewer.id)
    login_user(creator)

    response = client.get(f"/change-requests/{req.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["git_context"] is None
    assert data["title"] == req.title


# ── 6. Invalid repository URL is rejected ─────────────────────────────────────

def test_invalid_repository_url_rejected(client, db, create_user, create_role, login_user):
    junior = create_role(db, "junior", level=1)
    senior = create_role(db, "senior", level=3)
    creator = create_user(db, role=junior, label="creator")
    reviewer = create_user(db, role=senior, label="reviewer")
    login_user(creator)

    payload = _base_payload(reviewer.id)
    payload["git_context"] = {"repository_url": "not-a-valid-url"}

    response = client.post("/change-requests/", json=payload)

    assert response.status_code == 422


# ── 7. Invalid pull/merge request URL is rejected ────────────────────────────

def test_invalid_pull_request_url_rejected(client, db, create_user, create_role, login_user):
    junior = create_role(db, "junior", level=1)
    senior = create_role(db, "senior", level=3)
    creator = create_user(db, role=junior, label="creator")
    reviewer = create_user(db, role=senior, label="reviewer")
    login_user(creator)

    payload = _base_payload(reviewer.id)
    payload["git_context"] = {
        "pull_request_url": "ftp://not-allowed.example.com/pr/1",
    }

    response = client.post("/change-requests/", json=payload)

    assert response.status_code == 422


# ── 8. Unauthorized user cannot view git-context endpoint ────────────────────

def test_unauthorized_user_cannot_view_git_context(client, db, create_user, create_role, login_user, seed_change_request):
    junior = create_role(db, "junior", level=1)
    senior = create_role(db, "senior", level=3)
    creator = create_user(db, role=junior, label="creator")
    reviewer = create_user(db, role=senior, label="reviewer")
    unrelated = create_user(db, role=junior, label="unrelated")

    req = seed_change_request(db, creator_id=creator.id, reviewer_id=reviewer.id)
    _add_git_context(db, req.id)

    login_user(unrelated)
    response = client.get(f"/change-requests/{req.id}/git-context")

    assert response.status_code == 403


# ── 9. Assigned reviewer can view git context for assigned request ────────────

def test_assigned_reviewer_can_view_git_context(client, db, create_user, create_role, login_user, seed_change_request):
    junior = create_role(db, "junior", level=1)
    senior = create_role(db, "senior", level=3)
    creator = create_user(db, role=junior, label="creator")
    reviewer = create_user(db, role=senior, label="reviewer")

    req = seed_change_request(db, creator_id=creator.id, reviewer_id=reviewer.id)
    _add_git_context(db, req.id, branch_name="feature/reviewer-test")

    login_user(reviewer)
    response = client.get(f"/change-requests/{req.id}/git-context")

    assert response.status_code == 200
    assert response.json()["branch_name"] == "feature/reviewer-test"


# ── 10. Requester can view git context for own request ───────────────────────

def test_requester_can_view_git_context_for_own_request(client, db, create_user, create_role, login_user, seed_change_request):
    junior = create_role(db, "junior", level=1)
    senior = create_role(db, "senior", level=3)
    creator = create_user(db, role=junior, label="creator")
    reviewer = create_user(db, role=senior, label="reviewer")

    req = seed_change_request(db, creator_id=creator.id, reviewer_id=reviewer.id)
    _add_git_context(db, req.id, commit_hash="deadbeef")

    login_user(creator)
    response = client.get(f"/change-requests/{req.id}/git-context")

    assert response.status_code == 200
    assert response.json()["commit_hash"] == "deadbeef"


# ── 11. Git context is not required for any request type ─────────────────────

def test_git_context_not_required_for_any_request_type(client, db, create_user, create_role, login_user):
    junior = create_role(db, "junior", level=1)
    senior = create_role(db, "senior", level=3)
    creator = create_user(db, role=junior, label="creator")
    reviewer = create_user(db, role=senior, label="reviewer")
    login_user(creator)

    for req_type in ["access_change", "configuration_change", "code_change", "security_change", "administrative_change", "deployment_change", "resource_change"]:
        payload = {
            "title": f"Request {req_type}",
            "description": "No git context needed.",
            "request_type": req_type,
            "target_system": "Some System",
            "environment": "development",
            "risk_level": "low",
            "assigned_reviewer_id": reviewer.id,
        }
        response = client.post("/change-requests/", json=payload)
        assert response.status_code == 200, f"Failed for {req_type}: {response.text}"
        assert response.json()["git_context"] is None


# ── 12. Secret values in diff text / changed files are masked, not rejected ──

def test_secret_content_in_diff_text_masked(client, db, create_user, create_role, login_user):
    junior = create_role(db, "junior", level=1)
    senior = create_role(db, "senior", level=3)
    creator = create_user(db, role=junior, label="creator")
    reviewer = create_user(db, role=senior, label="reviewer")
    login_user(creator)

    payload = _base_payload(reviewer.id)
    payload["git_context"] = {
        "diff_text": "Updated config with token=ghp_" + "a" * 36 + " and API changes.",
    }

    response = client.post("/change-requests/", json=payload)

    assert response.status_code == 200, response.text
    assert response.json()["git_context"]["diff_text"] == "Updated config with token=[REDACTED] and API changes."


def test_secret_content_in_changed_files_masked(client, db, create_user, create_role, login_user):
    junior = create_role(db, "junior", level=1)
    senior = create_role(db, "senior", level=3)
    creator = create_user(db, role=junior, label="creator")
    reviewer = create_user(db, role=senior, label="reviewer")
    login_user(creator)

    payload = _base_payload(reviewer.id)
    payload["git_context"] = {
        "changed_files_summary": "-----BEGIN RSA PRIVATE KEY----- ...",
    }

    response = client.post("/change-requests/", json=payload)

    assert response.status_code == 200, response.text
    assert response.json()["git_context"]["changed_files_summary"] == "-----BEGIN RSA PRIVATE KEY-----\n[REDACTED]"


# ── 13. Audit log is created for git context linking ─────────────────────────

def test_audit_log_created_for_git_context_linking(client, db, create_user, create_role, login_user):
    from backend.models.audit_log import AuditLog

    junior = create_role(db, "junior", level=1)
    senior = create_role(db, "senior", level=3)
    creator = create_user(db, role=junior, label="creator")
    reviewer = create_user(db, role=senior, label="reviewer")
    login_user(creator)

    payload = _base_payload(reviewer.id)
    payload["git_context"] = {
        "branch_name": "feature/audit-test",
        "commit_hash": "cafebabe",
    }

    response = client.post("/change-requests/", json=payload)
    assert response.status_code == 200

    request_id = response.json()["id"]
    log_entry = (
        db.query(AuditLog)
        .filter(
            AuditLog.action == "GIT_CONTEXT_LINKED",
            AuditLog.entity_id == request_id,
        )
        .first()
    )
    assert log_entry is not None
    assert log_entry.user_id == creator.id


# ── 14. Git context is editable only by the creator, only while a draft ──────

from backend.models.audit_log import AuditLog  # noqa: E402

NOT_A_DRAFT = "Git context can only be changed while the request is a draft"


@pytest.fixture
def gc_people(db, create_user, create_role):
    junior = create_role(db, "junior", level=1)
    mid = create_role(db, "mid", level=2)
    admin = create_role(db, "admin", level=5)
    return {
        "creator": create_user(db, role=junior, label="creator"),
        "reviewer": create_user(db, role=mid, label="reviewer"),
        "admin": create_user(db, role=admin, label="admin"),
        "outsider": create_user(db, role=mid, label="outsider"),
    }


@pytest.mark.parametrize("status", [RequestStatus.PENDING_REVIEW, RequestStatus.APPROVED,
                                    RequestStatus.REJECTED, RequestStatus.APPLIED])
@pytest.mark.parametrize("actor", ["creator", "reviewer", "admin"])
def test_git_context_cannot_be_changed_after_submission(client, db, gc_people, login_user,
                                                        seed_change_request, status, actor):
    req = seed_change_request(db, creator_id=gc_people["creator"].id, reviewer_id=gc_people["reviewer"].id,
                              status=status)
    _add_git_context(db, req.id, branch_name="feature/original")

    login_user(gc_people[actor])
    response = client.post(f"/change-requests/{req.id}/git-context", json={"branch_name": "feature/changed"})

    assert (response.status_code, response.json()) == (400, {"detail": NOT_A_DRAFT})
    db.expire_all()
    assert db.query(GitContext).filter(GitContext.change_request_id == req.id).one().branch_name == "feature/original"
    assert db.query(AuditLog).filter(AuditLog.action.like("GIT_CONTEXT_%")).count() == 0


def test_git_context_cannot_be_linked_after_submission(client, db, gc_people, login_user, seed_change_request):
    req = seed_change_request(db, creator_id=gc_people["creator"].id, reviewer_id=gc_people["reviewer"].id,
                              status=RequestStatus.PENDING_REVIEW)
    login_user(gc_people["creator"])
    response = client.post(f"/change-requests/{req.id}/git-context", json={"branch_name": "feature/late"})
    assert (response.status_code, response.json()) == (400, {"detail": NOT_A_DRAFT})
    assert db.query(GitContext).count() == 0


@pytest.mark.parametrize("actor", ["reviewer", "admin"])
def test_non_creator_cannot_change_git_context_on_a_draft(client, db, gc_people, login_user,
                                                         seed_change_request, actor):
    req = seed_change_request(db, creator_id=gc_people["creator"].id, reviewer_id=gc_people["reviewer"].id)
    _add_git_context(db, req.id, branch_name="feature/original")

    login_user(gc_people[actor])
    response = client.post(f"/change-requests/{req.id}/git-context", json={"branch_name": "feature/changed"})

    assert (response.status_code, response.json()) == (403, {"detail": "Only the creator can change the Git context"})
    db.expire_all()
    assert db.query(GitContext).one().branch_name == "feature/original"


def test_outsider_gets_access_denied(client, db, gc_people, login_user, seed_change_request):
    req = seed_change_request(db, creator_id=gc_people["creator"].id, reviewer_id=gc_people["reviewer"].id,
                              status=RequestStatus.PENDING_REVIEW)
    login_user(gc_people["outsider"])
    response = client.post(f"/change-requests/{req.id}/git-context", json={"branch_name": "x"})
    assert (response.status_code, response.json()) == (403, {"detail": "Access denied"})


def test_update_records_old_and_new_identifiers(client, db, gc_people, login_user, seed_change_request):
    req = seed_change_request(db, creator_id=gc_people["creator"].id, reviewer_id=gc_people["reviewer"].id)
    login_user(gc_people["creator"])
    linked = client.post(f"/change-requests/{req.id}/git-context", json={
        "repository_url": "https://github.com/octo/demo", "branch_name": "feature/a",
        "target_branch": "main", "commit_hash": "aaa1111",
        "pull_request_url": "https://github.com/octo/demo/pull/1",
        "diff_text": "+secret-looking diff line", "changed_files_summary": "app/x.py",
    })
    assert linked.status_code == 200, linked.text

    updated = client.post(f"/change-requests/{req.id}/git-context", json={
        "branch_name": "feature/b", "commit_hash": "bbb2222", "diff_text": "+another line",
    })
    assert updated.status_code == 200, updated.text

    link_entry = db.query(AuditLog).filter(AuditLog.action == "GIT_CONTEXT_LINKED").one()
    assert link_entry.details == (
        "Git context linked: repository_url=https://github.com/octo/demo; branch_name=feature/a; "
        "target_branch=main; commit_hash=aaa1111; pull_request_url=https://github.com/octo/demo/pull/1"
    )
    update_entry = db.query(AuditLog).filter(AuditLog.action == "GIT_CONTEXT_UPDATED").one()
    assert update_entry.old_value == "branch_name=feature/a; commit_hash=aaa1111"
    assert update_entry.new_value == "branch_name=feature/b; commit_hash=bbb2222"
    assert update_entry.details == (
        "Git context updated: identifiers changed=branch_name,commit_hash; also sent: diff_text"
    )

    # Neither the diff nor the file summary is ever logged.
    for entry in db.query(AuditLog).all():
        stored = " ".join(filter(None, [entry.details, entry.old_value, entry.new_value]))
        assert "diff line" not in stored and "another line" not in stored and "app/x.py" not in stored


def test_creator_can_still_change_git_context_on_a_draft(client, db, gc_people, login_user, seed_change_request):
    req = seed_change_request(db, creator_id=gc_people["creator"].id, reviewer_id=gc_people["reviewer"].id)
    login_user(gc_people["creator"])
    assert client.post(f"/change-requests/{req.id}/git-context", json={"branch_name": "a"}).status_code == 200
    assert client.post(f"/change-requests/{req.id}/git-context", json={"branch_name": "b"}).status_code == 200
    assert client.post(f"/change-requests/{req.id}/submit").status_code == 200
    assert client.post(f"/change-requests/{req.id}/git-context", json={"branch_name": "c"}).status_code == 400
