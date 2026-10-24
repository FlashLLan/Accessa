"""Git data of a pull request as stored in git_context at submission (FR-21).

build_git_data() turns a fetched PullRequestSnapshot into
- diff_text: one standard multi-file unified diff ("diff --git a/x b/x" per file,
  so the frontend can group it by file), secret values masked, at most
  MAX_DIFF_CHARS (whole files only; the rest is listed as not included);
- changed_files_summary: "N changed files (+a -d) at <sha>", one line per file,
  and notes on truncation and masking.

stored_files() reads diff_text back into ChangedFile objects, so the AI review
works on exactly the files and patches that were submitted.
"""
import re
from dataclasses import dataclass

from backend.services.github_service import (
    ChangedFile,
    GitHubClient,
    InvalidPullRequestUrl,
    PullRequestSnapshot,
    parse_pull_request_url,
)
from backend.services.secret_masking import mask_secret_values

MAX_DIFF_CHARS = 200_000

_STATUS_WORD = {"added": "added", "removed": "deleted", "renamed": "renamed", "modified": "modified"}
_TOTAL = re.compile(r"^(\d+) changed files?\b")
_FILE_HEADER = re.compile(r"^diff --git a/(.+?) b/(.+)$")


@dataclass
class GitData:
    commit_hash: str
    diff_text: str
    changed_files_summary: str
    secrets_masked: int
    files_omitted: int        # changed files whose diff did not fit (or beyond GitHub's list)


def _file_block(f: ChangedFile) -> tuple[str, list[str]]:
    old_path = f.previous_path or f.path
    lines = [f"diff --git a/{old_path} b/{f.path}"]
    if f.status == "added":
        lines.append("new file mode 100644")
    elif f.status == "removed":
        lines.append("deleted file mode 100644")
    elif f.previous_path:
        lines += [f"rename from {f.previous_path}", f"rename to {f.path}"]
    if f.patch is None:
        lines.append(f"Binary files a/{old_path} and b/{f.path} differ (or the diff is too large to show)")
        return "\n".join(lines), []
    masked, found = mask_secret_values(f.patch, f.path)
    lines.append("--- /dev/null" if f.status == "added" else f"--- a/{old_path}")
    lines.append("+++ /dev/null" if f.status == "removed" else f"+++ b/{f.path}")
    lines.append(masked)
    return "\n".join(lines), found


def build_git_data(snapshot: PullRequestSnapshot) -> GitData:
    blocks, secrets, omitted_paths = [], set(), []
    used = 0
    for f in snapshot.files:
        block, found = _file_block(f)
        if used + len(block) + 1 > MAX_DIFF_CHARS:
            omitted_paths.append(f.path)
            continue
        blocks.append(block)
        used += len(block) + 1
        secrets.update(found)

    additions = sum(f.additions for f in snapshot.files)
    deletions = sum(f.deletions for f in snapshot.files)
    beyond_list = max(0, snapshot.changed_files_total - len(snapshot.files))
    summary = [f"{snapshot.changed_files_total} changed files (+{additions} -{deletions}) at {snapshot.head_sha}"]
    summary += [
        f"{_STATUS_WORD.get(f.status, f.status):<8} {f.path}"
        + (f" (from {f.previous_path})" if f.previous_path else "")
        + f" (+{f.additions} -{f.deletions})"
        for f in snapshot.files
    ]
    if beyond_list:
        summary.append(f"[{beyond_list} more changed file(s) not listed: GitHub returns at most {len(snapshot.files)}]")
    if omitted_paths:
        summary.append(f"[diff truncated at {MAX_DIFF_CHARS:,} characters: {len(omitted_paths)} file(s) not included: "
                       + ", ".join(omitted_paths) + "]")
    if secrets:
        summary.append(f"[{len(secrets)} secret value(s) masked in the diff]")

    return GitData(
        commit_hash=snapshot.head_sha,
        diff_text="\n".join(blocks),
        changed_files_summary="\n".join(summary),
        secrets_masked=len(secrets),
        files_omitted=len(omitted_paths) + beyond_list,
    )


def stored_files(diff_text: str | None) -> list[ChangedFile]:
    """The files and patches of a diff written by build_git_data()."""
    files: list[ChangedFile] = []
    current: ChangedFile | None = None
    patch_lines: list[str] | None = None

    def finish():
        if current is not None:
            current.patch = "\n".join(patch_lines) if patch_lines is not None else None
            files.append(current)

    for line in (diff_text or "").split("\n"):
        header = _FILE_HEADER.match(line)
        if header:
            finish()
            old_path, new_path = header.groups()
            current = ChangedFile(path=new_path, status="modified",
                                  previous_path=old_path if old_path != new_path else None)
            if current.previous_path:
                current.status = "renamed"
            patch_lines = None
            continue
        if current is None:
            continue
        if patch_lines is None:
            if line.startswith("new file mode"):
                current.status = "added"
            elif line.startswith("deleted file mode"):
                current.status = "removed"
            elif line.startswith("+++ "):
                patch_lines = []
            continue
        patch_lines.append(line)
    finish()
    return files


def stored_total(summary: str | None, fallback: int) -> int:
    match = _TOTAL.match(summary or "")
    return int(match.group(1)) if match else fallback


def is_github_pull_request(url: str | None) -> bool:
    try:
        parse_pull_request_url(url)
        return True
    except InvalidPullRequestUrl:
        return False


def fetch_for_submission(pull_request_url: str) -> GitData:
    """Head commit, file list and patches of a public GitHub PR, ready to store.
    Raises GitHubError (status_code + safe message) if GitHub cannot be read."""
    with GitHubClient() as client:
        snapshot = client.fetch_pull_request(pull_request_url, with_contents=False)
    return build_git_data(snapshot)
