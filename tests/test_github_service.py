"""GitHub pull request fetch (FR-21), with the GitHub API mocked by httpx.MockTransport."""
import httpx
import pytest

from backend.services import github_service
from backend.services.github_service import (
    GitHubClient,
    GitHubNotFound,
    GitHubRateLimited,
    GitHubUnavailable,
    InvalidPullRequestUrl,
    parse_pull_request_url,
)

SHA = "a" * 40
PR_URL = "https://github.com/octo/demo/pull/7"


def _pr(**overrides):
    body = {
        "title": "Add retry to exporter",
        "head": {"sha": SHA, "ref": "feature/retry"},
        "base": {"ref": "main"},
        "changed_files": 4,
    }
    body.update(overrides)
    return body


FILES = [
    {"filename": "app/export.py", "status": "modified", "additions": 3, "deletions": 1,
     "patch": "@@ -1,2 +1,4 @@\n-import os\n+import os\n+import time\n"},
    {"filename": "docs/old name.md", "status": "removed", "additions": 0, "deletions": 5, "patch": "@@ -1 +0,0 @@\n-x\n"},
    {"filename": "static/logo.png", "status": "added", "additions": 0, "deletions": 0},
    {"filename": "app/new.py", "status": "renamed", "previous_filename": "app/old.py",
     "additions": 0, "deletions": 0, "patch": None},
]

CONTENTS = {
    "app/export.py": b"import os\nimport time\n",
    "static/logo.png": b"\x89PNG\r\n\x1a\n\x00\x00",
    "app/new.py": b"print('renamed')\n",
}


class FakeGitHub:
    """Records every request and answers like the GitHub REST API."""

    def __init__(self, *, pr=None, files=None, contents=None, error=None):
        self.pr = pr or _pr()
        self.files = FILES if files is None else files
        self.contents = CONTENTS if contents is None else contents
        self.error = error  # callable(request) -> Response | None
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.error and (response := self.error(request)):
            return response
        path = request.url.path
        if path == "/repos/octo/demo/pulls/7":
            return httpx.Response(200, json=self.pr)
        if path == "/repos/octo/demo/pulls/7/files":
            return httpx.Response(200, json=self.files)
        prefix = "/repos/octo/demo/contents/"
        if path.startswith(prefix):
            name = path[len(prefix):]
            if name in self.contents and request.url.params.get("ref") == SHA:
                return httpx.Response(200, content=self.contents[name])
            return httpx.Response(404, json={"message": "Not Found"})
        return httpx.Response(404, json={"message": "Not Found"})

    def content_requests(self):
        return [r for r in self.requests if "/contents/" in r.url.path]


def _client(fake, token=""):
    return GitHubClient(token=token, transport=httpx.MockTransport(fake))


# --- URL parsing -------------------------------------------------------------------------

@pytest.mark.parametrize("url, expected", [
    ("https://github.com/octo/demo/pull/7", ("octo", "demo", 7)),
    ("https://github.com/octo/demo/pull/7/files", ("octo", "demo", 7)),
    ("https://www.github.com/octo-org/my.repo_x/pull/123/", ("octo-org", "my.repo_x", 123)),
    ("https://github.com/octo/demo.git/pull/7", ("octo", "demo", 7)),
    ("  https://github.com/octo/demo/pull/7#discussion  ", ("octo", "demo", 7)),
])
def test_parse_valid_pull_request_urls(url, expected):
    ref = parse_pull_request_url(url)
    assert (ref.owner, ref.repo, ref.number) == expected


@pytest.mark.parametrize("url", [
    None,
    "",
    "http://github.com/octo/demo/pull/7",             # not https
    "https://gitlab.com/octo/demo/-/merge_requests/7",  # not GitHub
    "https://github.com.evil.example/octo/demo/pull/7",
    "https://evil.example/github.com/octo/demo/pull/7",
    "https://api.github.com/repos/octo/demo/pulls/7",
    "https://github.com/octo/demo/issues/7",
    "https://github.com/octo/demo/pull/0",
    "https://github.com/octo/../pull/7",
    "https://github.com/../demo/pull/7",
    "https://github.com/octo/demo/pull/7abc",
    "https://user:pass@github.com/octo/demo/pull/7",
])
def test_parse_rejects_everything_else(url):
    with pytest.raises(InvalidPullRequestUrl):
        parse_pull_request_url(url)


def test_invalid_url_makes_no_request():
    fake = FakeGitHub()
    with pytest.raises(InvalidPullRequestUrl):
        _client(fake).fetch_pull_request("https://gitlab.com/octo/demo/-/merge_requests/7")
    assert fake.requests == []


# --- fetching at the head SHA -------------------------------------------------------------

def test_fetches_head_sha_files_and_patches():
    fake = FakeGitHub()
    snapshot = _client(fake).fetch_pull_request(PR_URL)

    assert (snapshot.owner, snapshot.repo, snapshot.number) == ("octo", "demo", 7)
    assert snapshot.head_sha == SHA
    assert (snapshot.base_ref, snapshot.head_ref) == ("main", "feature/retry")
    assert snapshot.files_truncated is False

    by_path = {f.path: f for f in snapshot.files}
    assert list(by_path) == ["app/export.py", "docs/old name.md", "static/logo.png", "app/new.py"]
    assert by_path["app/export.py"].patch == FILES[0]["patch"]
    assert by_path["app/export.py"].content == "import os\nimport time\n"
    assert by_path["app/new.py"].previous_path == "app/old.py"
    assert by_path["app/new.py"].content == "print('renamed')\n"


def test_every_file_is_read_at_the_pull_requests_head_sha():
    fake = FakeGitHub()
    _client(fake).fetch_pull_request(PR_URL)

    content_requests = fake.content_requests()
    assert content_requests, "file contents were fetched"
    assert all(r.url.params["ref"] == SHA for r in content_requests)
    assert all(r.headers["accept"] == "application/vnd.github.raw+json" for r in content_requests)


def test_removed_files_are_not_fetched():
    fake = FakeGitHub()
    snapshot = _client(fake).fetch_pull_request(PR_URL)

    removed = next(f for f in snapshot.files if f.status == "removed")
    assert (removed.content, removed.skipped_reason) == (None, "removed")
    assert removed.patch  # the diff of a removed file is still available
    assert not any("old%20name" in r.url.raw_path.decode() for r in fake.content_requests())


def test_binary_files_are_skipped():
    snapshot = _client(FakeGitHub()).fetch_pull_request(PR_URL)
    logo = next(f for f in snapshot.files if f.path == "static/logo.png")
    assert (logo.content, logo.skipped_reason) == (None, "binary")


def test_large_files_are_skipped_without_reading_them_fully(monkeypatch):
    monkeypatch.setattr(github_service, "MAX_FILE_BYTES", 10)
    fake = FakeGitHub(contents={**CONTENTS, "app/export.py": b"x" * 11})
    snapshot = _client(fake).fetch_pull_request(PR_URL)
    big = next(f for f in snapshot.files if f.path == "app/export.py")
    assert (big.content, big.skipped_reason) == (None, "too_large")


def test_file_paths_are_url_encoded():
    fake = FakeGitHub(files=[{"filename": "dir/a b#c.py", "status": "added"}],
                      contents={"dir/a b#c.py": b"ok\n"})
    snapshot = _client(fake).fetch_pull_request(PR_URL)
    assert snapshot.files[0].content == "ok\n"
    assert fake.content_requests()[0].url.raw_path.startswith(b"/repos/octo/demo/contents/dir/a%20b%23c.py?")


def test_more_files_than_the_limit_are_reported_as_truncated(monkeypatch):
    monkeypatch.setattr(github_service, "MAX_CHANGED_FILES", 2)
    snapshot = _client(FakeGitHub()).fetch_pull_request(PR_URL)
    assert len(snapshot.files) == 2
    assert snapshot.files_truncated is True


def test_pull_request_without_valid_head_sha_is_an_error():
    fake = FakeGitHub(pr=_pr(head={"sha": "not-a-sha"}))
    with pytest.raises(GitHubUnavailable):
        _client(fake).fetch_pull_request(PR_URL)


# --- errors --------------------------------------------------------------------------------

def _fail_pr(response):
    return lambda request: response if request.url.path.endswith("/pulls/7") else None


def test_private_or_missing_repository_gives_clear_error():
    fake = FakeGitHub(error=_fail_pr(httpx.Response(404, json={"message": "Not Found"})))
    with pytest.raises(GitHubNotFound) as exc:
        _client(fake).fetch_pull_request(PR_URL)
    assert exc.value.status_code == 404
    assert "private" in exc.value.message and "public" in exc.value.message


def test_forbidden_without_rate_limit_does_not_say_private():
    response = httpx.Response(403, headers={"x-ratelimit-remaining": "42"}, json={"message": "Forbidden"})
    with pytest.raises(GitHubUnavailable) as exc:
        _client(FakeGitHub(error=_fail_pr(response))).fetch_pull_request(PR_URL)
    assert exc.value.status_code == 502
    assert exc.value.message == "GitHub refused the request (403). Try again later."
    assert "private" not in exc.value.message


def test_primary_rate_limit_reports_reset_time():
    response = httpx.Response(403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1767225600"},
                              json={"message": "API rate limit exceeded"})
    with pytest.raises(GitHubRateLimited) as exc:
        _client(FakeGitHub(error=_fail_pr(response))).fetch_pull_request(PR_URL)
    assert exc.value.status_code == 429
    assert "00:00 UTC" in exc.value.message
    assert "GITHUB_TOKEN" in exc.value.message  # hint, since no token is configured


def test_secondary_rate_limit_reports_retry_after():
    response = httpx.Response(429, headers={"retry-after": "30"})
    with pytest.raises(GitHubRateLimited) as exc:
        _client(FakeGitHub(error=_fail_pr(response))).fetch_pull_request(PR_URL)
    assert "30 seconds" in exc.value.message


def test_timeout_gives_clear_error():
    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)
    with pytest.raises(GitHubUnavailable) as exc:
        _client(FakeGitHub(error=timeout)).fetch_pull_request(PR_URL)
    assert "in time" in exc.value.message


def test_server_error_gives_clear_error():
    with pytest.raises(GitHubUnavailable) as exc:
        _client(FakeGitHub(error=_fail_pr(httpx.Response(502)))).fetch_pull_request(PR_URL)
    assert "502" in exc.value.message


def test_bad_token_error_does_not_leak_the_token():
    secret = "ghp_" + "s" * 36
    with pytest.raises(GitHubUnavailable) as exc:
        _client(FakeGitHub(error=_fail_pr(httpx.Response(401))), token=secret).fetch_pull_request(PR_URL)
    assert "GITHUB_TOKEN" in exc.value.message
    assert secret not in exc.value.message


# --- token and host --------------------------------------------------------------------------

def test_unauthenticated_by_default(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    fake = FakeGitHub()
    GitHubClient(transport=httpx.MockTransport(fake)).fetch_pull_request(PR_URL)
    assert all("authorization" not in r.headers for r in fake.requests)


def test_github_token_from_environment_is_sent(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token-value")
    fake = FakeGitHub()
    GitHubClient(transport=httpx.MockTransport(fake)).fetch_pull_request(PR_URL)
    assert all(r.headers["authorization"] == "Bearer test-token-value" for r in fake.requests)


def test_requests_only_go_to_api_github_com():
    fake = FakeGitHub()
    _client(fake).fetch_pull_request(PR_URL)
    assert {(r.url.scheme, r.url.host) for r in fake.requests} == {("https", "api.github.com")}


def test_redirect_to_another_host_is_refused_and_gets_no_token():
    def redirect(request):
        if request.url.host == "api.github.com" and request.url.path.endswith("/pulls/7"):
            return httpx.Response(301, headers={"location": "https://evil.example/steal"})
        return None
    fake = FakeGitHub(error=redirect)
    with pytest.raises(GitHubUnavailable):
        _client(fake, token="test-token-value").fetch_pull_request(PR_URL)
    assert all(r.url.host == "api.github.com" for r in fake.requests)


def test_redirect_within_api_github_com_is_followed():
    # A renamed repository answers with a 301 to its new API path.
    def redirect(request):
        if request.url.path == "/repos/octo/old-name/pulls/7":
            return httpx.Response(301, headers={"location": "https://api.github.com/repos/octo/demo/pulls/7"})
        return None
    fake = FakeGitHub(error=redirect)
    client = _client(fake)
    # Only the PR call goes to the old name here; enough to show the redirect is followed.
    pr = client._send("GET", "/repos/octo/old-name/pulls/7").json()
    assert pr["head"]["sha"] == SHA
