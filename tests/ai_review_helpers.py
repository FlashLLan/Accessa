"""Fake GitHub and OpenAI for AI review tests (httpx.MockTransport, no network)."""
import json
from contextlib import contextmanager
from unittest.mock import patch

import httpx

from backend.services.github_service import GitHubClient
from backend.services.openai_client import OpenAIClient

SHA = "c0ffee" + "0" * 34
OTHER_SHA = "b" * 40
PR_URL = "https://github.com/octo/demo/pull/7"

GOOD_OUTPUT = {
    "summary": "Adds retry logic to the exporter.",
    "suggested_risk_level": "high",
    "recommended_reviewer_role": "senior",
    "impact_area": "Export service",
    "red_flags": ["No rollback plan"],
    "verification_checklist": ["Run the export tests"],
    "improvement_suggestions": ["Add a retry limit"],
}


class FakeGitHub:
    """A public repository `octo/demo` with PR #7 at SHA. `repo` maps path -> bytes
    at SHA; `pr_files` is the PR files API answer."""

    def __init__(self, repo: dict[str, bytes], pr_files: list[dict], *, changed_files_total=None, fail=None,
                 head_sha=SHA, content_ref=None):
        # head_sha: the PR's current head. content_ref: the commit the repository
        # files are served at (default: the head).
        self.head_sha = head_sha
        self.content_ref = content_ref or head_sha
        self.repo = repo
        self.pr_files = pr_files
        self.changed_files_total = len(pr_files) if changed_files_total is None else changed_files_total
        self.fail = fail  # callable(request) -> Response | None
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail and (response := self.fail(request)):
            return response
        path = request.url.path
        base = "/repos/octo/demo"
        if path == f"{base}/pulls/7":
            return httpx.Response(200, json={
                "title": "Exporter retry", "head": {"sha": self.head_sha, "ref": "feature/retry"},
                "base": {"ref": "main"}, "changed_files": self.changed_files_total,
            })
        if path == f"{base}/pulls/7/files":
            return httpx.Response(200, json=self.pr_files)
        if path == f"{base}/git/trees/{self.content_ref}":
            return httpx.Response(200, json={"truncated": False, "tree": [
                {"path": p, "type": "blob", "size": len(c)} for p, c in self.repo.items()
            ]})
        if path.startswith(f"{base}/contents/"):
            name = path[len(f"{base}/contents/"):]
            if request.url.params.get("ref") == self.content_ref and name in self.repo:
                return httpx.Response(200, content=self.repo[name])
        return httpx.Response(404, json={"message": "Not Found"})

    def content_paths(self) -> list[str]:
        prefix = "/repos/octo/demo/contents/"
        return [r.url.path[len(prefix):] for r in self.requests if r.url.path.startswith(prefix)]


class FakeOpenAI:
    def __init__(self, output=None, *, status=200, raw=None, on_call=None):
        self.output = GOOD_OUTPUT if output is None else output
        self.status = status
        self.raw = raw
        self.on_call = on_call
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.on_call:
            self.on_call()
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": "boom"}})
        content = self.raw if self.raw is not None else json.dumps(self.output)
        return httpx.Response(200, json={
            "model": "gpt-test",
            "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
        })

    @property
    def body(self) -> dict:
        return json.loads(self.requests[-1].content)

    @property
    def sent_text(self) -> str:
        """Everything that was sent to the AI, as one string."""
        return self.requests[-1].content.decode()

    @property
    def user_message(self) -> str:
        return self.body["messages"][1]["content"]


@contextmanager
def mocked_services(github: FakeGitHub, ai: FakeOpenAI, *, configured=True):
    key, model = ("test-openai-key", "gpt-test") if configured else ("", "")
    with patch("backend.services.ai_review_service.GitHubClient",
               lambda: GitHubClient(token="", transport=httpx.MockTransport(github))), \
         patch("backend.services.ai_review_service.OpenAIClient",
               lambda: OpenAIClient(api_key=key, model=model, transport=httpx.MockTransport(ai))):
        yield
