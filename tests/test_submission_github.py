"""Git data fetched from GitHub at submission (FR-21), and the AI review on that commit."""
import json
from unittest.mock import patch

import httpx
import pytest
from sqlalchemy import text

from ai_review_helpers import OTHER_SHA, PR_URL, SHA, FakeGitHub, FakeOpenAI, mocked_services
from backend.models.audit_log import AuditLog
from backend.models.enums import GitContextSource, RequestStatus
from backend.models.git_context import GitContext
from backend.services import pull_request_data
from backend.services.ai_review_service import HEAD_MOVED_FLAG
from backend.services.github_service import GitHubClient, PullRequestSnapshot
from backend.services.pull_request_data import build_git_data, stored_files

AWS_KEY = "AKIA" + "Z" * 16

PR_FILES = [
    {"filename": "app/export.py", "status": "modified", "additions": 2, "deletions": 1,
     "patch": "@@ -1,2 +1,3 @@\n import os\n-RETRIES = 1\n+RETRIES = 3\n+TIMEOUT = 10"},
    {"filename": "app/new.py", "status": "added", "additions": 1, "deletions": 0,
     "patch": "@@ -0,0 +1 @@\n+print('new')"},
    {"filename": "app/old.py", "status": "removed", "additions": 0, "deletions": 1,
     "patch": "@@ -1 +0,0 @@\n-print('old')"},
    {"filename": "app/renamed.py", "previous_filename": "app/before.py", "status": "renamed",
     "additions": 0, "deletions": 0, "patch": None},
    {"filename": "static/logo.png", "status": "added", "additions": 0, "deletions": 0},
]
REPO = {"app/export.py": b"import os\nRETRIES = 3\nTIMEOUT = 10\n", "app/new.py": b"print('new')\n",
        "app/renamed.py": b"x = 1\n", "static/logo.png": b"\x89PNG\x00"}


@pytest.fixture
def people(db, create_role, create_user):
    roles = {name: create_role(db, name, level=lvl) for name, lvl in [("junior", 1), ("mid", 2)]}
    return {"creator": create_user(db, role=roles["junior"], label="creator"),
            "reviewer": create_user(db, role=roles["mid"], label="reviewer")}


PASTED = {"commit_hash": "pasted0", "changed_files_summary": "pasted files", "diff_text": "+pasted diff"}


@pytest.fixture
def draft(db, people, seed_change_request):
    req = seed_change_request(db, creator_id=people["creator"].id, reviewer_id=people["reviewer"].id)
    db.add(GitContext(change_request_id=req.id, provider="github", pull_request_url=PR_URL,
                      branch_name="feature/retry", **PASTED))
    db.commit()
    return req


def _github_for_submission(github):
    return patch.object(pull_request_data, "GitHubClient",
                        lambda: GitHubClient(token="", transport=httpx.MockTransport(github)))


def _submit(client, login_user, people, req, github):
    login_user(people["creator"])
    with _github_for_submission(github):
        return client.post(f"/change-requests/{req.id}/submit")


def _git(db, req):
    db.expire_all()
    return db.query(GitContext).filter(GitContext.change_request_id == req.id).one()


# --- submission ----------------------------------------------------------------------------

def test_submission_stores_github_data_and_overwrites_pasted_values(client, db, people, login_user, draft):
    github = FakeGitHub(dict(REPO), [dict(f) for f in PR_FILES])
    response = _submit(client, login_user, people, draft, github)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "pending_review"

    git = _git(db, draft)
    assert git.source is GitContextSource.GITHUB and git.fetched_at is not None
    assert git.commit_hash == SHA
    assert "pasted" not in (git.diff_text + git.changed_files_summary + git.commit_hash)
    assert git.branch_name == "feature/retry"  # other fields untouched

    assert "diff --git a/app/export.py b/app/export.py\n--- a/app/export.py\n+++ b/app/export.py\n@@" in git.diff_text
    assert "+RETRIES = 3" in git.diff_text
    assert "diff --git a/app/new.py b/app/new.py\nnew file mode 100644\n--- /dev/null" in git.diff_text
    assert "diff --git a/app/old.py b/app/old.py\ndeleted file mode 100644\n--- a/app/old.py\n+++ /dev/null" in git.diff_text
    assert "rename from app/before.py\nrename to app/renamed.py" in git.diff_text
    assert "Binary files a/static/logo.png and b/static/logo.png differ" in git.diff_text

    summary = git.changed_files_summary.splitlines()
    assert summary[0] == f"5 changed files (+3 -2) at {SHA}"
    assert "modified app/export.py (+2 -1)" in summary
    assert "deleted  app/old.py (+0 -1)" in summary
    assert "renamed  app/renamed.py (from app/before.py) (+0 -0)" in summary

    # Only the PR and its file list were read; no file contents at submission.
    assert github.content_paths() == []
    entry = db.query(AuditLog).filter(AuditLog.action == "REQUEST_SUBMITTED").one()
    assert entry.details == f"Submitted for review; Git data fetched from GitHub at commit {SHA}"

    fetched = client.get(f"/change-requests/{draft.id}/git-context").json()
    assert fetched["source"] == "github" and fetched["fetched_at"] and fetched["commit_hash"] == SHA


def test_stored_diff_reads_back_as_the_same_files(client, db, people, login_user, draft):
    _submit(client, login_user, people, draft, FakeGitHub(dict(REPO), [dict(f) for f in PR_FILES]))
    files = {f.path: f for f in stored_files(_git(db, draft).diff_text)}
    assert {p: f.status for p, f in files.items()} == {
        "app/export.py": "modified", "app/new.py": "added", "app/old.py": "removed",
        "app/renamed.py": "renamed", "static/logo.png": "added",
    }
    assert files["app/export.py"].patch == PR_FILES[0]["patch"]
    assert files["app/renamed.py"].previous_path == "app/before.py"
    assert files["static/logo.png"].patch is None


@pytest.mark.parametrize("failure, status, fragment", [
    (httpx.Response(404, json={"message": "Not Found"}), 404, "private"),
    (httpx.Response(403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1767225600"}), 429, "rate limit"),
    (httpx.Response(502), 502, "GitHub returned an error (502)"),
    ("timeout", 502, "did not respond in time"),
])
def test_fetch_failure_blocks_submission_without_changes(client, db, people, login_user, draft,
                                                         failure, status, fragment):
    def fail(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("slow", request=request)
        return failure
    response = _submit(client, login_user, people, draft, FakeGitHub(dict(REPO), PR_FILES, fail=fail))

    assert response.status_code == status
    assert fragment in response.json()["detail"]
    db.expire_all()
    assert db.get(type(draft), draft.id).status is RequestStatus.DRAFT
    git = _git(db, draft)
    assert (git.commit_hash, git.changed_files_summary, git.diff_text) == tuple(PASTED.values())
    assert git.source is GitContextSource.MANUAL and git.fetched_at is None
    assert db.query(AuditLog).filter(AuditLog.action == "REQUEST_SUBMITTED").count() == 0


@pytest.mark.parametrize("pr_url", [None, "https://gitlab.com/org/repo/-/merge_requests/7"])
def test_without_a_github_pull_request_link_the_manual_diff_stays(client, db, people, login_user, draft, pr_url):
    git = _git(db, draft)
    git.pull_request_url = pr_url
    db.commit()
    github = FakeGitHub(dict(REPO), PR_FILES)

    assert _submit(client, login_user, people, draft, github).status_code == 200
    git = _git(db, draft)
    assert (git.commit_hash, git.changed_files_summary, git.diff_text) == tuple(PASTED.values())
    assert git.source is GitContextSource.MANUAL and git.fetched_at is None
    assert github.requests == []
    entry = db.query(AuditLog).filter(AuditLog.action == "REQUEST_SUBMITTED").one()
    assert entry.details == "Submitted for review; Git data entered manually (not verified)"


def test_request_without_git_context_submits_as_before(client, db, people, login_user, seed_change_request):
    req = seed_change_request(db, creator_id=people["creator"].id, reviewer_id=people["reviewer"].id)
    login_user(people["creator"])
    assert client.post(f"/change-requests/{req.id}/submit").status_code == 200
    assert db.query(AuditLog).filter(AuditLog.action == "REQUEST_SUBMITTED").one().details == "Submitted for review"


def test_secrets_in_the_fetched_diff_are_masked(client, db, people, login_user, draft):
    files = [{"filename": "config/settings.py", "status": "modified", "additions": 2, "deletions": 0,
              "patch": f'@@ -1 +1,3 @@\n+password = "hunter2-prod"\n+aws = "{AWS_KEY}"\n+key = os.environ["API_KEY"]'}]
    assert _submit(client, login_user, people, draft, FakeGitHub({}, files)).status_code == 200

    git = _git(db, draft)
    assert "hunter2-prod" not in git.diff_text and AWS_KEY not in git.diff_text
    assert '+password = "[REDACTED]"' in git.diff_text and '+aws = "[REDACTED]"' in git.diff_text
    assert 'os.environ["API_KEY"]' in git.diff_text
    assert "[2 secret value(s) masked in the diff]" in git.changed_files_summary
    entry = db.query(AuditLog).filter(AuditLog.action == "REQUEST_SUBMITTED").one()
    assert "2 secret(s) masked" in entry.details and "hunter2" not in entry.details


def test_size_limit_is_applied_and_noted(client, db, people, login_user, draft, monkeypatch):
    monkeypatch.setattr(pull_request_data, "MAX_DIFF_CHARS", 300)
    assert _submit(client, login_user, people, draft, FakeGitHub(dict(REPO), [dict(f) for f in PR_FILES])).status_code == 200
    git = _git(db, draft)
    assert len(git.diff_text) <= 300
    assert "[diff truncated at 300 characters:" in git.changed_files_summary
    assert "app/export.py" in git.diff_text  # whole files, in order, until the limit


def test_more_files_than_github_lists_are_noted(client, db, people, login_user, draft):
    github = FakeGitHub(dict(REPO), [dict(f) for f in PR_FILES], changed_files_total=250)
    _submit(client, login_user, people, draft, github)
    summary = _git(db, draft).changed_files_summary
    assert summary.startswith(f"250 changed files")
    assert "[245 more changed file(s) not listed" in summary


def test_pull_request_link_changed_during_fetch_gives_409(client, db, people, login_user, draft, app_db_engine):
    def change_link(request):
        with app_db_engine.begin() as conn:
            conn.execute(text("UPDATE git_context SET pull_request_url = 'https://github.com/octo/other/pull/1' "
                              "WHERE change_request_id = :id"), {"id": draft.id})
        return None
    response = _submit(client, login_user, people, draft, FakeGitHub(dict(REPO), PR_FILES, fail=change_link))
    assert response.status_code == 409
    db.expire_all()
    assert db.get(type(draft), draft.id).status is RequestStatus.DRAFT
    assert _git(db, draft).source is GitContextSource.MANUAL


# --- AI review on the submitted commit --------------------------------------------------------------

def _submitted(db, people, seed_change_request, files, commit):
    """A pending request whose Git data was fetched from GitHub at `commit`."""
    req = seed_change_request(db, creator_id=people["creator"].id, reviewer_id=people["reviewer"].id,
                              status=RequestStatus.PENDING_REVIEW)
    data = build_git_data(PullRequestSnapshot(owner="octo", repo="demo", number=7, title="t", head_sha=commit,
                                              base_ref="main", head_ref="feature/retry",
                                              files=stored_files_from(files), changed_files_total=len(files)))
    db.add(GitContext(change_request_id=req.id, pull_request_url=PR_URL, source=GitContextSource.GITHUB,
                      commit_hash=data.commit_hash, diff_text=data.diff_text,
                      changed_files_summary=data.changed_files_summary))
    db.commit()
    return req


def stored_files_from(files):
    from backend.services.github_service import ChangedFile
    return [ChangedFile(path=f["filename"], status=f["status"], additions=f.get("additions", 0),
                        deletions=f.get("deletions", 0), patch=f.get("patch"),
                        previous_path=f.get("previous_filename")) for f in files]


SUBMITTED_FILES = [
    {"filename": "app/export.py", "status": "modified", "patch": "@@ -1 +1 @@\n-RETRIES = 1\n+RETRIES = 3"},
    {"filename": "app/old.py", "status": "removed", "patch": "@@ -1 +0,0 @@\n-print('old')"},
]


def test_ai_review_reads_files_at_the_stored_commit_and_flags_a_moved_head(
    client, db, people, login_user, seed_change_request
):
    req = _submitted(db, people, seed_change_request, SUBMITTED_FILES, OTHER_SHA)
    # The PR has moved on: head is SHA now, with a different file list.
    github = FakeGitHub({"app/export.py": b"RETRIES = 3\n"},
                        [{"filename": "app/later.py", "status": "added", "patch": "+later"}],
                        head_sha=SHA, content_ref=OTHER_SHA)
    ai = FakeOpenAI()
    login_user(people["reviewer"])
    with mocked_services(github, ai):
        response = client.post(f"/change-requests/{req.id}/ai-review")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reviewed_commit"] == OTHER_SHA
    assert json.loads(body["red_flags"])[0] == HEAD_MOVED_FLAG
    assert {f["path"] for f in body["files_reviewed"]} == {"app/export.py", "app/old.py"}
    assert "app/later.py" not in ai.user_message
    assert f"now at {SHA}" in ai.user_message

    contents = [r for r in github.requests if "/contents/" in r.url.path]
    assert contents and all(r.url.params["ref"] == OTHER_SHA for r in contents)
    assert not any(r.url.path.endswith("/pulls/7/files") for r in github.requests)


def test_ai_review_without_new_commits_has_no_moved_flag(client, db, people, login_user, seed_change_request):
    req = _submitted(db, people, seed_change_request, SUBMITTED_FILES, SHA)
    github = FakeGitHub({"app/export.py": b"RETRIES = 3\n"}, [], head_sha=SHA)
    login_user(people["reviewer"])
    with mocked_services(github, FakeOpenAI()):
        body = client.post(f"/change-requests/{req.id}/ai-review").json()
    assert body["reviewed_commit"] == SHA
    assert HEAD_MOVED_FLAG not in json.loads(body["red_flags"])


def test_ai_review_extended_scope_uses_the_stored_commit_too(client, db, people, login_user, seed_change_request):
    req = _submitted(db, people, seed_change_request, SUBMITTED_FILES, OTHER_SHA)
    github = FakeGitHub({"app/export.py": b"from app import utils\n", "app/utils.py": b"x = 1\n"}, [],
                        head_sha=SHA, content_ref=OTHER_SHA)
    login_user(people["reviewer"])
    with mocked_services(github, FakeOpenAI()):
        body = client.post(f"/change-requests/{req.id}/ai-review", json={"scope": "extended"}).json()
    assert {"path": "app/utils.py", "source": "related"} in body["files_reviewed"]
    assert any(r.url.path.endswith(f"/git/trees/{OTHER_SHA}") for r in github.requests)
