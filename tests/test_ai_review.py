"""AI review endpoint (FR-20, FR-21) with GitHub and OpenAI mocked."""
import json
from unittest.mock import patch

import httpx
import pytest
from sqlalchemy import text

from ai_review_helpers import GOOD_OUTPUT, PR_URL, SHA, FakeGitHub, FakeOpenAI, mocked_services
from backend.models.ai_review_result import AIReviewResult
from backend.models.audit_log import AuditLog
from backend.models.enums import AIReviewScope, RequestStatus, RiskLevel
from backend.models.git_context import GitContext
from backend.services import ai_review_service

AWS_KEY = "AKIA" + "Q" * 16
GH_TOKEN = "ghp_" + "t" * 36

REPO = {
    "app/export.py": b"from app import utils\nfrom .retry import backoff\nimport os\n\n"
                     b"API_KEY = os.environ[\"API_KEY\"]\npassword = \"hunter2-prod\"\n",
    "app/utils.py": b"def helper():\n    return 1\n",
    "app/retry.py": b"def backoff():\n    return 2\n",
    "app/cli.py": b"from app.export import run\n",          # imports the changed file
    "app/unrelated.py": b"print('nothing to see')\n",
    "web/src/api.js": b"import { get } from './http';\nexport const x = 1;\n",
    "web/src/http.ts": b"export function get() {}\n",
    "package.json": b'{"name": "demo"}\n',
    "Dockerfile": b"FROM python:3.12\n",
    "README.md": b"# Demo\n",
}

PR_FILES = [
    {"filename": "app/export.py", "status": "modified", "additions": 2, "deletions": 0,
     "patch": "@@ -1,3 +1,5 @@\n+API_KEY = os.environ[\"API_KEY\"]\n+password = \"hunter2-prod\"\n"},
    {"filename": "web/src/api.js", "status": "added", "additions": 2, "deletions": 0,
     "patch": "@@ -0,0 +1,2 @@\n+import { get } from './http';\n+export const x = 1;\n"},
]


@pytest.fixture
def people(db, create_role, create_user):
    roles = {name: create_role(db, name, level=lvl) for name, lvl in
             [("junior", 1), ("mid", 2), ("senior", 3), ("lead", 4), ("admin", 5)]}
    return {
        "roles": roles,
        "creator": create_user(db, role=roles["junior"], label="creator"),
        "reviewer": create_user(db, role=roles["mid"], label="reviewer"),
        "outsider": create_user(db, role=roles["mid"], label="outsider"),
        "lead": create_user(db, role=roles["lead"], label="lead"),
        "admin": create_user(db, role=roles["admin"], label="admin"),
        "admin2": create_user(db, role=roles["admin"], label="admin2"),
    }


@pytest.fixture
def pending(db, people, seed_change_request):
    req = seed_change_request(db, creator_id=people["creator"].id, reviewer_id=people["reviewer"].id,
                              status=RequestStatus.PENDING_REVIEW, risk_level=RiskLevel.LOW, title="Exporter retry")
    db.add(GitContext(change_request_id=req.id, provider="github", pull_request_url=PR_URL))
    db.commit()
    return req


def _github(**kwargs):
    return FakeGitHub(dict(REPO), [dict(f) for f in PR_FILES], **kwargs)


def _generate(client, req, body=None):
    return client.post(f"/change-requests/{req.id}/ai-review", json=body)


def _nothing_saved(db):
    assert db.query(AIReviewResult).count() == 0
    assert db.query(AuditLog).filter(AuditLog.action == "AI_REVIEW_GENERATED").count() == 0


# --- correct files at the PR's SHA ----------------------------------------------------------------

def test_changed_files_scope_reads_the_changed_files_at_the_prs_head_sha(client, db, people, pending, login_user):
    github, ai = _github(), FakeOpenAI()
    login_user(people["reviewer"])
    with mocked_services(github, ai):
        response = _generate(client, pending)  # no body: scope defaults to changed_files

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reviewed_commit"] == SHA
    assert body["review_scope"] == "changed_files"
    assert body["files_reviewed"] == [{"path": "app/export.py", "source": "changed"},
                                      {"path": "web/src/api.js", "source": "changed"}]
    assert body["files_skipped"] == []
    assert body["changed_files_total"] == 2
    assert body["input_truncated"] is False

    # Exactly the changed files, each read at the head SHA; no tree listing, no related files.
    assert sorted(github.content_paths()) == ["app/export.py", "web/src/api.js"]
    assert all(r.url.params["ref"] == SHA for r in github.requests if "/contents/" in r.url.path)
    assert not any("/git/trees/" in r.url.path for r in github.requests)

    sent = ai.user_message
    assert "<<<DIFF app/export.py [modified]>>>" in sent
    assert "<<<FILE app/export.py>>>" in sent and "from .retry import backoff" in sent
    assert f"Reviewed commit: {SHA}" in sent
    assert "app/utils.py" not in sent and "package.json" not in sent

    saved = db.query(AIReviewResult).one()
    assert saved.review_scope is AIReviewScope.CHANGED_FILES
    assert saved.model_name == "gpt-test" and saved.prompt_version == ai_review_service.PROMPT_VERSION
    assert json.loads(saved.verification_checklist) == GOOD_OUTPUT["verification_checklist"]


def test_request_uses_structured_output_schema(client, db, people, pending, login_user):
    ai = FakeOpenAI()
    login_user(people["reviewer"])
    with mocked_services(_github(), ai):
        _generate(client, pending)

    body = ai.body
    assert body["model"] == "gpt-test"
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert set(body["response_format"]["json_schema"]["schema"]["required"]) == set(GOOD_OUTPUT)
    assert ai.requests[-1].headers["authorization"] == "Bearer test-openai-key"
    assert ai.requests[-1].url == "https://api.openai.com/v1/chat/completions"


def test_request_metadata_contains_no_names_or_emails(client, db, people, pending, login_user):
    ai = FakeOpenAI()
    login_user(people["reviewer"])
    with mocked_services(_github(), ai):
        _generate(client, pending)
    for user in (people["creator"], people["reviewer"]):
        assert user.email not in ai.sent_text and user.full_name not in ai.sent_text
    assert "Author's role: junior" in ai.user_message


# --- extended scope ------------------------------------------------------------------------------------

def test_extended_scope_adds_imports_importers_and_config_files(client, db, people, pending, login_user):
    github, ai = _github(), FakeOpenAI()
    login_user(people["reviewer"])
    with mocked_services(github, ai):
        response = _generate(client, pending, {"scope": "extended"})

    assert response.status_code == 200, response.text
    reviewed = {f["path"]: f["source"] for f in response.json()["files_reviewed"]}
    assert reviewed == {
        "app/export.py": "changed",
        "web/src/api.js": "changed",
        "app/utils.py": "related",      # from app import utils
        "app/retry.py": "related",      # from .retry import backoff
        "web/src/http.ts": "related",   # import './http'
        "app/cli.py": "related",        # imports app.export
        "package.json": "config",
        "Dockerfile": "config",
    }
    assert response.json()["review_scope"] == "extended"
    assert "app/unrelated.py" not in reviewed and "README.md" not in reviewed

    sent = ai.user_message
    assert "<<<FILE app/utils.py [related]>>>" in sent
    assert "<<<FILE Dockerfile [config]>>>" in sent
    assert all(r.url.params.get("ref") == SHA for r in github.requests if "/contents/" in r.url.path)
    assert any(r.url.path == f"/repos/octo/demo/git/trees/{SHA}" for r in github.requests)
    assert db.query(AIReviewResult).one().review_scope is AIReviewScope.EXTENDED


def test_invalid_scope_is_rejected(client, db, people, pending, login_user):
    login_user(people["reviewer"])
    with mocked_services(_github(), FakeOpenAI()):
        assert _generate(client, pending, {"scope": "everything"}).status_code == 422
    _nothing_saved(db)


# --- secrets ----------------------------------------------------------------------------------------------

def test_secret_values_are_masked_before_sending_and_counted(client, db, people, pending, login_user):
    pending.description = f"Deploy with AWS key {AWS_KEY} and token {GH_TOKEN}"
    db.commit()
    ai = FakeOpenAI()
    login_user(people["reviewer"])
    with mocked_services(_github(), ai):
        response = _generate(client, pending)

    sent = ai.sent_text
    for secret in ("hunter2-prod", AWS_KEY, GH_TOKEN):
        assert secret not in sent
    assert 'password = \\"[REDACTED]\\"' in sent
    assert 'os.environ[\\"API_KEY\\"]' in sent  # references are kept

    body = response.json()
    # hunter2-prod appears in the diff and in the file: counted once. Plus the two in the description.
    assert body["secrets_masked"] == 3
    assert json.loads(body["red_flags"])[0] == "3 hard-coded secret(s) detected and masked"
    assert json.loads(body["red_flags"])[1:] == GOOD_OUTPUT["red_flags"]
    assert db.query(AIReviewResult).one().secrets_masked == 3


def test_no_secret_red_flag_without_secrets(client, db, people, pending, login_user):
    github = FakeGitHub({"a.py": b"x = 1\n"}, [{"filename": "a.py", "status": "added", "patch": "+x = 1"}])
    login_user(people["reviewer"])
    with mocked_services(github, FakeOpenAI()):
        body = _generate(client, pending).json()
    assert body["secrets_masked"] == 0
    assert json.loads(body["red_flags"]) == GOOD_OUTPUT["red_flags"]


# --- size limit and skipped files ---------------------------------------------------------------------------

def test_size_limit_is_enforced_and_reported(client, db, people, pending, login_user, monkeypatch):
    monkeypatch.setattr(ai_review_service, "MAX_INPUT_CHARS", 1500)
    ai = FakeOpenAI()
    login_user(people["reviewer"])
    with mocked_services(_github(), ai):
        body = _generate(client, pending, {"scope": "extended"}).json()

    assert len(ai.user_message) <= 1500
    assert body["input_truncated"] is True
    skipped = {f["path"]: f["reason"] for f in body["files_skipped"]}
    assert "size_limit" in skipped.values()
    reviewed = {f["path"] for f in body["files_reviewed"]}
    assert not reviewed & set(skipped)
    assert "app/export.py" in reviewed  # the diff comes first


def test_skipped_and_truncated_pr_files_are_recorded(client, db, people, pending, login_user):
    github = FakeGitHub(
        {"app/a.py": b"x = 1\n", "logo.png": b"\x89PNG\x00\x00"},
        [{"filename": "app/a.py", "status": "modified", "patch": "+x = 1"},
         {"filename": "logo.png", "status": "added"},
         {"filename": "old.py", "status": "removed", "patch": "-gone"}],
        changed_files_total=250,
    )
    ai = FakeOpenAI()
    login_user(people["reviewer"])
    with mocked_services(github, ai):
        body = _generate(client, pending).json()

    assert body["changed_files_total"] == 250
    assert {(f["path"], f["reason"]) for f in body["files_skipped"]} == {("logo.png", "binary"), ("old.py", "removed")}
    assert {f["path"] for f in body["files_reviewed"]} == {"app/a.py", "old.py"}  # old.py: its diff was sent
    assert "only the first 3 are included" in ai.user_message


# --- failures save nothing -------------------------------------------------------------------------------------

@pytest.mark.parametrize("ai, status, message", [
    (FakeOpenAI(status=500), 502, "The AI service returned an error (500)."),
    (FakeOpenAI(status=429), 429, "The AI service is rate limited or out of quota. Try again later."),
    (FakeOpenAI(status=401), 502, "The AI service rejected the configured API key."),
    (FakeOpenAI(raw="not json"), 502, "The AI service returned an invalid review."),
    (FakeOpenAI(output={**GOOD_OUTPUT, "suggested_risk_level": "extreme"}), 502, "The AI service returned an invalid review."),
    (FakeOpenAI(output={"summary": "only this"}), 502, "The AI service returned an invalid review."),
])
def test_ai_failure_returns_error_and_saves_nothing(client, db, people, pending, login_user, ai, status, message):
    login_user(people["reviewer"])
    with mocked_services(_github(), ai):
        response = _generate(client, pending)
    assert response.status_code == status
    assert response.json() == {"detail": message}
    _nothing_saved(db)


def test_ai_timeout_returns_error_and_saves_nothing(client, db, people, pending, login_user):
    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)
    login_user(people["reviewer"])
    with mocked_services(_github(), timeout):
        response = _generate(client, pending)
    assert response.status_code == 504
    _nothing_saved(db)


@pytest.mark.parametrize("github_response, status, fragment", [
    (httpx.Response(404, json={"message": "Not Found"}), 404, "private"),
    (httpx.Response(403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1767225600"}), 429, "rate limit"),
    (httpx.Response(403, headers={"x-ratelimit-remaining": "10"}), 502, "refused the request (403)"),
])
def test_github_failure_returns_error_and_saves_nothing(client, db, people, pending, login_user,
                                                        github_response, status, fragment):
    github = _github(fail=lambda r: github_response if r.url.path.endswith("/pulls/7") else None)
    ai = FakeOpenAI()
    login_user(people["reviewer"])
    with mocked_services(github, ai):
        response = _generate(client, pending)
    assert response.status_code == status
    assert fragment in response.json()["detail"]
    assert ai.requests == []
    _nothing_saved(db)


def test_not_configured_fails_before_contacting_github(client, db, people, pending, login_user):
    github, ai = _github(), FakeOpenAI()
    login_user(people["reviewer"])
    with mocked_services(github, ai, configured=False):
        response = _generate(client, pending)
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]
    assert github.requests == [] and ai.requests == []
    _nothing_saved(db)


def test_failed_audit_write_saves_no_result(client, db, app_db_engine, people, pending, login_user):
    login_user(people["reviewer"])
    with mocked_services(_github(), FakeOpenAI()), \
         patch("backend.api.ai_review.log_action", side_effect=RuntimeError("audit store down")):
        with pytest.raises(RuntimeError):
            _generate(client, pending)
    with app_db_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM ai_review_results")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM audit_logs")).scalar() == 0


def test_request_changed_during_review_saves_nothing(client, db, app_db_engine, people, pending, login_user):
    def approve_meanwhile():
        with app_db_engine.begin() as conn:
            conn.execute(text("UPDATE change_requests SET status = 'APPROVED' WHERE id = :id"), {"id": pending.id})

    login_user(people["reviewer"])
    with mocked_services(_github(), FakeOpenAI(on_call=approve_meanwhile)):
        response = _generate(client, pending)
    assert response.status_code == 409
    _nothing_saved(db)


# --- never changes the request -----------------------------------------------------------------------------

def test_review_never_changes_risk_level_or_status(client, db, people, pending, login_user):
    login_user(people["reviewer"])
    with mocked_services(_github(), FakeOpenAI()):  # suggests "high"; the request is "low"
        body = _generate(client, pending).json()
    assert body["suggested_risk_level"] == "high"
    db.refresh(pending)
    assert (pending.risk_level, pending.status) == (RiskLevel.LOW, RequestStatus.PENDING_REVIEW)
    assert pending.assigned_reviewer_id == people["reviewer"].id


# --- who may generate ------------------------------------------------------------------------------------

@pytest.mark.parametrize("actor", ["creator", "outsider", "lead", "admin"])
def test_only_the_assigned_reviewer_can_generate(client, db, people, pending, login_user, actor):
    github, ai = _github(), FakeOpenAI()
    login_user(people[actor])
    with mocked_services(github, ai):
        response = _generate(client, pending)
    assert response.status_code == 403
    assert response.json() == {"detail": "Only the assigned reviewer can generate an AI review"}
    assert github.requests == [] and ai.requests == []
    _nothing_saved(db)


def test_admin_request_is_reviewed_by_the_assigned_second_admin(client, db, people, seed_change_request, login_user):
    req = seed_change_request(db, creator_id=people["admin"].id, reviewer_id=people["admin2"].id,
                              status=RequestStatus.PENDING_REVIEW)
    db.add(GitContext(change_request_id=req.id, pull_request_url=PR_URL))
    db.commit()

    with mocked_services(_github(), FakeOpenAI()):
        login_user(people["admin"])  # the creator, also an admin
        assert _generate(client, req).status_code == 403
        login_user(people["admin2"])
        assert _generate(client, req).status_code == 200


@pytest.mark.parametrize("status", [RequestStatus.DRAFT, RequestStatus.APPROVED, RequestStatus.REJECTED,
                                    RequestStatus.APPLIED])
def test_only_pending_requests_can_be_reviewed(client, db, people, pending, login_user, status):
    pending.status = status
    db.commit()
    login_user(people["reviewer"])
    with mocked_services(_github(), FakeOpenAI()):
        response = _generate(client, pending)
    assert response.status_code == 409
    _nothing_saved(db)


def test_pull_request_url_is_required(client, db, people, pending, login_user):
    pending.git_context.pull_request_url = None
    db.commit()
    login_user(people["reviewer"])
    with mocked_services(_github(), FakeOpenAI()):
        response = _generate(client, pending)
    assert response.status_code == 400
    _nothing_saved(db)


def test_non_github_pull_request_url_is_rejected(client, db, people, pending, login_user):
    pending.git_context.pull_request_url = "https://gitlab.com/octo/demo/-/merge_requests/7"
    db.commit()
    github = _github()
    login_user(people["reviewer"])
    with mocked_services(github, FakeOpenAI()):
        response = _generate(client, pending)
    assert response.status_code == 400
    assert "github.com" in response.json()["detail"]
    assert github.requests == []
    _nothing_saved(db)


# --- audit and reading -------------------------------------------------------------------------------------

def test_generation_is_audited_with_commit_and_scope(client, db, people, pending, login_user):
    login_user(people["reviewer"])
    with mocked_services(_github(), FakeOpenAI()):
        _generate(client, pending, {"scope": "extended"})

    entry = db.query(AuditLog).filter(AuditLog.action == "AI_REVIEW_GENERATED").one()
    assert entry.user_id == people["reviewer"].id and entry.actor_role == "mid"
    assert (entry.entity_type, entry.entity_id, entry.request_id) == ("change_request", pending.id, pending.id)
    assert f"commit {SHA}" in entry.details and "scope extended" in entry.details
    assert entry.new_value == "extended"


@pytest.mark.parametrize("reader", ["creator", "reviewer", "admin"])
def test_result_is_readable_by_anyone_who_can_open_the_request(client, db, people, pending, login_user, reader):
    login_user(people["reviewer"])
    with mocked_services(_github(), FakeOpenAI()):
        _generate(client, pending)

    login_user(people[reader])
    response = client.get(f"/change-requests/{pending.id}/ai-review")
    assert response.status_code == 200
    [result] = response.json()
    assert result["reviewed_commit"] == SHA and result["review_scope"] == "changed_files"

    login_user(people["outsider"])
    assert client.get(f"/change-requests/{pending.id}/ai-review").status_code == 403


def test_latest_result_comes_first(client, db, people, pending, login_user):
    login_user(people["reviewer"])
    with mocked_services(_github(), FakeOpenAI()):
        first = _generate(client, pending).json()["id"]
        second = _generate(client, pending, {"scope": "extended"}).json()["id"]
    results = client.get(f"/change-requests/{pending.id}/ai-review").json()
    assert [r["id"] for r in results] == [second, first]
