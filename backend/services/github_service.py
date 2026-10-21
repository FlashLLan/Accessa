"""Read-only access to PUBLIC GitHub pull requests through the GitHub REST API (FR-21).

Given a pull request URL (https://github.com/<owner>/<repo>/pull/<n>) this fetches
the PR's head commit SHA, its changed files with their patches, and the full
content of each changed file AT THAT SHA. Nothing is stored here; the caller
decides what (if anything) to keep.

Unauthenticated by default (60 requests/hour per IP). If GITHUB_TOKEN is set it is
sent as a bearer token (5,000 requests/hour); it only needs to read public repos.
Requests only ever go to api.github.com, also after redirects, so the token can
never be sent anywhere else.
"""
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

API_HOST = "api.github.com"
API_BASE = f"https://{API_HOST}"
TIMEOUT = httpx.Timeout(10.0, connect=5.0)

MAX_CHANGED_FILES = 100        # one page of the PR files API; more is reported as truncated
MAX_FILE_BYTES = 200_000       # larger files are skipped, not downloaded in full

# github.com/<owner>/<repo>/pull/<n>, optionally followed by /files, /commits, ...
# Owner: GitHub user/org name rules. Repo: letters, digits, '.', '_', '-'.
_PR_URL = re.compile(
    r"^https://(?:www\.)?github\.com/"
    r"(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/"
    r"(?P<repo>[A-Za-z0-9._-]{1,100})/"
    r"pull/(?P<number>[1-9][0-9]{0,9})"
    r"(?:/[A-Za-z0-9/_-]*)?/?(?:[?#].*)?$"
)


# --- errors ---------------------------------------------------------------------------
# `status_code` is what the API endpoint should answer with; `message` is safe to
# show to the user (never contains the token).

class GitHubError(Exception):
    status_code = 502

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InvalidPullRequestUrl(GitHubError):
    status_code = 400


class GitHubNotFound(GitHubError):
    status_code = 404


class GitHubRateLimited(GitHubError):
    status_code = 429


class GitHubUnavailable(GitHubError):
    status_code = 502


# --- results ----------------------------------------------------------------------------

@dataclass
class PullRequestRef:
    owner: str
    repo: str
    number: int


@dataclass
class ChangedFile:
    path: str
    status: str                      # added, modified, removed, renamed, ...
    additions: int = 0
    deletions: int = 0
    patch: str | None = None         # None for binary files or very large diffs
    previous_path: str | None = None  # set for renames
    content: str | None = None       # full file at the head SHA; None if skipped
    skipped_reason: str | None = None  # "removed", "binary", "too_large"


@dataclass
class PullRequestSnapshot:
    owner: str
    repo: str
    number: int
    title: str
    head_sha: str
    base_ref: str | None
    head_ref: str | None
    files: list[ChangedFile] = field(default_factory=list)
    files_truncated: bool = False    # the PR has more than MAX_CHANGED_FILES files
    changed_files_total: int = 0     # as reported by GitHub; may exceed len(files)


# --- URL parsing ------------------------------------------------------------------------

def parse_pull_request_url(url: str | None) -> PullRequestRef:
    if not url or not url.strip():
        raise InvalidPullRequestUrl("No pull request URL is linked to this request.")
    match = _PR_URL.match(url.strip())
    if not match:
        raise InvalidPullRequestUrl(
            "Only GitHub pull request URLs are supported "
            "(https://github.com/<owner>/<repo>/pull/<number>)."
        )
    repo = match["repo"].removesuffix(".git")
    if repo in ("", ".", ".."):
        raise InvalidPullRequestUrl("Invalid repository name in the pull request URL.")
    return PullRequestRef(owner=match["owner"], repo=repo, number=int(match["number"]))


# --- client -----------------------------------------------------------------------------

def _only_api_host(request: httpx.Request) -> None:
    # Applies to the first request and to every redirect httpx follows.
    if request.url.scheme != "https" or request.url.host != API_HOST:
        raise GitHubUnavailable("GitHub redirected to an unexpected host; request stopped.")


class GitHubClient:
    """Small synchronous client. `transport` lets tests plug in httpx.MockTransport."""

    def __init__(self, token: str | None = None, transport: httpx.BaseTransport | None = None):
        token = token if token is not None else os.getenv("GITHUB_TOKEN") or None
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "accessa-ai-review",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._authenticated = bool(token)
        self._http = httpx.Client(
            base_url=API_BASE,
            headers=headers,
            timeout=TIMEOUT,
            follow_redirects=True,  # renamed/transferred repos answer with 301
            transport=transport,
            event_hooks={"request": [_only_api_host]},
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- low level -----------------------------------------------------------------

    def _send(self, method: str, path: str, *, stream: bool = False, **kwargs) -> httpx.Response:
        try:
            request = self._http.build_request(method, path, **kwargs)
            response = self._http.send(request, stream=stream)
        except GitHubError:
            raise
        except httpx.TimeoutException:
            raise GitHubUnavailable("GitHub did not respond in time. Try again later.") from None
        except httpx.HTTPError:
            raise GitHubUnavailable("Could not reach GitHub. Try again later.") from None
        if response.status_code >= 400:
            if stream:
                response.read()
                response.close()
            self._raise_for_status(response)
        return response

    def _raise_for_status(self, response: httpx.Response) -> None:
        status = response.status_code
        remaining = response.headers.get("x-ratelimit-remaining")
        if status == 429 or (status == 403 and (remaining == "0" or "retry-after" in response.headers)):
            raise GitHubRateLimited(self._rate_limit_message(response))
        if status == 401:
            raise GitHubUnavailable("GitHub rejected the configured GITHUB_TOKEN.")
        if status == 403:
            # Not a rate limit (checked above). Private repositories answer 404, not 403.
            raise GitHubUnavailable("GitHub refused the request (403). Try again later.")
        if status == 404:
            # GitHub answers 404 for private repositories it does not show to us.
            raise GitHubNotFound(
                "Repository or pull request not found, or the repository is private. "
                "Only public GitHub repositories are supported."
            )
        raise GitHubUnavailable(f"GitHub returned an error ({status}). Try again later.")

    def _rate_limit_message(self, response: httpx.Response) -> str:
        hint = "" if self._authenticated else " Setting GITHUB_TOKEN raises the limit."
        reset = response.headers.get("x-ratelimit-reset")
        retry_after = response.headers.get("retry-after")
        if reset and reset.isdigit():
            at = datetime.fromtimestamp(int(reset), tz=timezone.utc).strftime("%H:%M UTC")
            return f"GitHub rate limit reached. Try again after {at}.{hint}"
        if retry_after and retry_after.isdigit():
            return f"GitHub rate limit reached. Try again in {retry_after} seconds.{hint}"
        return f"GitHub rate limit reached. Try again later.{hint}"

    # -- API calls -------------------------------------------------------------------

    def get_file(self, owner: str, repo: str, path: str, ref: str) -> tuple[str | None, str | None]:
        """Content of `path` at commit `ref` as (text, None), or (None, reason) when the
        file is binary or larger than MAX_FILE_BYTES. Never reads more than the limit."""
        encoded = "/".join(quote(part, safe="") for part in path.split("/"))
        response = self._send(
            "GET",
            f"/repos/{owner}/{repo}/contents/{encoded}",
            params={"ref": ref},
            headers={"Accept": "application/vnd.github.raw+json"},
            stream=True,
        )
        try:
            data = bytearray()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > MAX_FILE_BYTES:
                    return None, "too_large"
        except httpx.TimeoutException:
            raise GitHubUnavailable("GitHub did not respond in time. Try again later.") from None
        except httpx.HTTPError:
            raise GitHubUnavailable("Could not reach GitHub. Try again later.") from None
        finally:
            response.close()
        if b"\x00" in data:
            return None, "binary"
        try:
            return data.decode("utf-8"), None
        except UnicodeDecodeError:
            return None, "binary"

    def fetch_pull_request(self, url: str) -> PullRequestSnapshot:
        ref = parse_pull_request_url(url)
        base = f"/repos/{ref.owner}/{ref.repo}"

        pr = self._send("GET", f"{base}/pulls/{ref.number}").json()
        head_sha = (pr.get("head") or {}).get("sha")
        if not head_sha or not re.fullmatch(r"[0-9a-f]{40}", head_sha):
            raise GitHubUnavailable("GitHub returned a pull request without a head commit.")

        listed = self._send(
            "GET", f"{base}/pulls/{ref.number}/files", params={"per_page": MAX_CHANGED_FILES, "page": 1}
        ).json()
        changed_files = pr.get("changed_files")
        if not isinstance(changed_files, int):
            changed_files = len(listed)
        truncated = changed_files > len(listed) or len(listed) > MAX_CHANGED_FILES

        files = []
        for item in listed[:MAX_CHANGED_FILES]:
            changed = ChangedFile(
                path=item["filename"],
                status=item.get("status", "modified"),
                additions=item.get("additions", 0),
                deletions=item.get("deletions", 0),
                patch=item.get("patch"),
                previous_path=item.get("previous_filename"),
            )
            if changed.status == "removed":
                changed.skipped_reason = "removed"  # no content at the head commit
            else:
                changed.content, changed.skipped_reason = self.get_file(ref.owner, ref.repo, changed.path, head_sha)
            files.append(changed)

        return PullRequestSnapshot(
            owner=ref.owner,
            repo=ref.repo,
            number=ref.number,
            title=pr.get("title") or "",
            head_sha=head_sha,
            base_ref=(pr.get("base") or {}).get("ref"),
            head_ref=(pr.get("head") or {}).get("ref"),
            files=files,
            files_truncated=truncated,
            changed_files_total=max(changed_files, len(listed)),
        )

    def list_tree(self, owner: str, repo: str, ref: str) -> dict[str, int]:
        """All files of the repository at commit `ref` as {path: size in bytes}.
        GitHub cuts very large trees short; what it returned is used as is."""
        tree = self._send("GET", f"/repos/{owner}/{repo}/git/trees/{ref}", params={"recursive": "1"}).json()
        return {
            item["path"]: item.get("size", 0)
            for item in tree.get("tree", [])
            if item.get("type") == "blob" and isinstance(item.get("path"), str)
        }


def fetch_pull_request(url: str) -> PullRequestSnapshot:
    with GitHubClient() as client:
        return client.fetch_pull_request(url)
