"""AI review of a change request and the public GitHub pull request it links to (FR-20).

1. Fetch the PR at its head commit (github_service): diff and changed files.
2. 'extended' scope: also files the changed files import or are imported by,
   and top-level config files (related_files).
3. Mask hard-coded secret values in everything that is sent (secret_masking).
4. Assemble the input within MAX_INPUT_CHARS; whatever does not fit is skipped
   and reported.
5. Ask the model for structured JSON (openai_client) and validate it.

Nothing is stored here: the caller saves the result and its audit entry. The
review is advisory and never changes the request's risk level or status.
"""
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError, field_validator

from backend.models.enums import AIReviewScope
from backend.services import related_files
from backend.services.ai_review_prompt import OUTPUT_SCHEMA, PROMPT_VERSION, SYSTEM_PROMPT
from backend.services.github_service import MAX_FILE_BYTES, GitHubClient, PullRequestSnapshot
from backend.services.openai_client import AIServiceError, OpenAIClient
from backend.services.pull_request_data import stored_files, stored_total
from backend.services.secret_masking import mask_secret_values

MAX_INPUT_CHARS = 120_000   # about 30k tokens; the whole user message must fit
MAX_TEXT_ITEM = 1_000
MAX_LIST_ITEMS = 20


@dataclass(frozen=True)
class RequestFacts:
    """What the AI sees about the request. No names or e-mails."""
    title: str
    description: str
    request_type: str
    target_system: str
    environment: str
    risk_level: str
    author_role: str | None
    repository_name: str | None
    branch_name: str | None
    target_branch: str | None
    pull_request_url: str
    # Set when the Git data was fetched from GitHub at submission: the review then
    # reads the files at this commit, not at the PR's current head.
    submitted_commit: str | None = None
    submitted_diff: str | None = None
    submitted_summary: str | None = None


@dataclass
class ReviewInput:
    text: str
    reviewed_commit: str
    review_scope: AIReviewScope
    files_reviewed: list[dict] = field(default_factory=list)   # [{path, source}]
    files_skipped: list[dict] = field(default_factory=list)    # [{path, reason}]
    changed_files_total: int = 0
    input_truncated: bool = False
    secrets_masked: int = 0
    head_moved: bool = False          # the PR has new commits since submission


class AIReviewOutput(BaseModel):
    summary: str
    suggested_risk_level: str
    recommended_reviewer_role: str
    impact_area: str
    red_flags: list[str]
    verification_checklist: list[str]
    improvement_suggestions: list[str]

    @field_validator("suggested_risk_level")
    @classmethod
    def _risk(cls, v):
        if v not in OUTPUT_SCHEMA["properties"]["suggested_risk_level"]["enum"]:
            raise ValueError("unknown risk level")
        return v

    @field_validator("recommended_reviewer_role")
    @classmethod
    def _role(cls, v):
        if v not in OUTPUT_SCHEMA["properties"]["recommended_reviewer_role"]["enum"]:
            raise ValueError("unknown role")
        return v

    @field_validator("summary", "impact_area")
    @classmethod
    def _text(cls, v):
        return v.strip()[:4 * MAX_TEXT_ITEM]

    @field_validator("red_flags", "verification_checklist", "improvement_suggestions")
    @classmethod
    def _lists(cls, v):
        return [item.strip()[:MAX_TEXT_ITEM] for item in v if item.strip()][:MAX_LIST_ITEMS]


@dataclass
class AIReview:
    input: ReviewInput
    output: AIReviewOutput
    model_name: str
    prompt_version: str = PROMPT_VERSION


# --- collecting files ---------------------------------------------------------------------------

@dataclass
class _File:
    path: str
    source: str                 # changed, related, config
    content: str | None
    reason: str | None = None   # why content is None


def _related(client: GitHubClient, snapshot: PullRequestSnapshot) -> list[_File]:
    """Files the changed files import or are imported by, then top-level config files."""
    owner, repo, sha = snapshot.owner, snapshot.repo, snapshot.head_sha
    tree_sizes = client.list_tree(owner, repo, sha)
    tree = set(tree_sizes)
    changed = {f.path for f in snapshot.files}
    fetched: dict[str, tuple[str | None, str | None]] = {}

    def fetch(path: str) -> tuple[str | None, str | None]:
        if path not in fetched:
            if tree_sizes.get(path, 0) > MAX_FILE_BYTES:
                fetched[path] = (None, "too_large")  # known from the tree; not downloaded
            else:
                fetched[path] = client.get_file(owner, repo, path, sha)
        return fetched[path]

    related: list[str] = []

    def add(path: str) -> None:
        if path not in changed and path not in related and len(related) < related_files.MAX_RELATED_FILES:
            related.append(path)

    # Imported by the changed files.
    for f in snapshot.files:
        if f.content is not None:
            for path in sorted(related_files.imports_of(f.path, f.content, tree)):
                add(path)

    # Importing a changed file (nearby candidates only).
    for candidate in related_files.importer_candidates(sorted(changed), tree_sizes, MAX_FILE_BYTES):
        content, _ = fetch(candidate)
        if content is not None and related_files.imports_of(candidate, content, tree) & changed:
            add(candidate)

    files = [_File(path, "related", *fetch(path)) for path in related]
    files += [_File(path, "config", *fetch(path))
              for path in related_files.config_files(tree_sizes, exclude=changed | set(related))]
    return files


# --- assembling the input --------------------------------------------------------------------------

def _metadata_block(facts: RequestFacts, snapshot: PullRequestSnapshot, scope: AIReviewScope) -> str:
    lines = [
        "# Change request",
        f"Title: {facts.title}",
        f"Type: {facts.request_type}",
        f"Target system: {facts.target_system}",
        f"Environment: {facts.environment}",
        f"Risk level declared by the author: {facts.risk_level}",
        f"Author's role: {facts.author_role or 'unknown'}",
        "Description:",
        facts.description,
        "",
        "# Pull request",
        f"URL: {facts.pull_request_url}",
        f"Title: {snapshot.title}",
        f"Repository: {snapshot.owner}/{snapshot.repo}",
        f"Branch: {snapshot.head_ref or facts.branch_name or '-'} -> {snapshot.base_ref or facts.target_branch or '-'}",
        f"Reviewed commit: {snapshot.head_sha}",
        f"Changed files: {snapshot.changed_files_total}"
        + (f" (only the first {len(snapshot.files)} are included)" if snapshot.files_truncated else ""),
        f"Review scope: {scope.value}",
    ]
    if snapshot.current_head_sha and snapshot.current_head_sha != snapshot.head_sha:
        lines.append(
            f"Note: the pull request has new commits since submission (now at {snapshot.current_head_sha}); "
            f"this review covers the submitted commit {snapshot.head_sha}."
        )
    return "\n".join(lines)


def build_input(facts: RequestFacts, snapshot: PullRequestSnapshot, scope: AIReviewScope,
                extra: list[_File]) -> ReviewInput:
    result = ReviewInput(
        text="",
        reviewed_commit=snapshot.head_sha,
        review_scope=scope,
        changed_files_total=snapshot.changed_files_total,
    )
    parts: list[str] = []
    used = 0
    reviewed: dict[str, str] = {}   # path -> source, in order
    # Distinct secret values that were actually sent masked; a secret that shows up
    # in a file's diff and in its full content counts once. Never stored.
    secrets: set[str] = set()

    def masked(text: str, path: str | None = None) -> tuple[str, list[str]]:
        return mask_secret_values(text, path)

    def try_add(block: str, found: list[str]) -> bool:
        nonlocal used
        if used + len(block) > MAX_INPUT_CHARS:
            result.input_truncated = True
            return False
        parts.append(block)
        used += len(block)
        secrets.update(found)
        return True

    def skip(path: str, reason: str) -> None:
        if not any(s["path"] == path for s in result.files_skipped):
            result.files_skipped.append({"path": path, "reason": reason})

    # 1. Request and PR metadata: always included (masked like everything else).
    meta, n = masked(_metadata_block(facts, snapshot, scope))
    try_add(meta, n)

    # 2. The diff, file by file.
    try_add("\n\n# Diff (unified, per file)", [])
    for f in snapshot.files:
        if not f.patch:
            continue
        rename = f" (renamed from {f.previous_path})" if f.previous_path else ""
        patch, n = masked(f.patch, f.path)
        block = f"\n\n<<<DIFF {f.path} [{f.status}{rename}]>>>\n{patch}\n<<<END DIFF>>>"
        if try_add(block, n):
            reviewed.setdefault(f.path, "changed")
        else:
            skip(f.path, "size_limit")

    # 3. Full content of the changed files at the reviewed commit.
    try_add(f"\n\n# Changed files, full content at {snapshot.head_sha}", [])
    for f in snapshot.files:
        if f.content is None:
            skip(f.path, f.skipped_reason or "unavailable")
            continue
        content, n = masked(f.content, f.path)
        block = f"\n\n<<<FILE {f.path}>>>\n{content}\n<<<END FILE>>>"
        if try_add(block, n):
            reviewed.setdefault(f.path, "changed")
        else:
            skip(f.path, "size_limit")

    # 4. Extended scope: related files and top-level config files.
    if extra:
        try_add(f"\n\n# Related files (imports, importers, top-level config) at {snapshot.head_sha}", [])
    for f in extra:
        if f.content is None:
            skip(f.path, f.reason or "unavailable")
            continue
        content, n = masked(f.content, f.path)
        block = f"\n\n<<<FILE {f.path} [{f.source}]>>>\n{content}\n<<<END FILE>>>"
        if try_add(block, n):
            reviewed.setdefault(f.path, f.source)
        else:
            skip(f.path, "size_limit")

    result.files_reviewed = [{"path": p, "source": s} for p, s in reviewed.items()]
    result.secrets_masked = len(secrets)
    result.text = "".join(parts)
    return result


# --- the whole review ---------------------------------------------------------------------------------

HEAD_MOVED_FLAG = "The pull request has new commits since submission"


def review_target_commit(facts: RequestFacts) -> str:
    """The commit a review would cover now: the one stored at submission, or (for
    manually entered Git data) the PR's current head, which costs one GitHub request."""
    if facts.submitted_commit:
        return facts.submitted_commit
    with GitHubClient() as github:
        return github.pull_request(facts.pull_request_url)[2]


def _submitted_snapshot(github: GitHubClient, facts: RequestFacts) -> PullRequestSnapshot:
    """The PR as submitted: files and patches from the stored diff, full contents
    read at the stored commit. One extra request tells whether the head moved."""
    ref, pr, current_head = github.pull_request(facts.pull_request_url)
    files = stored_files(facts.submitted_diff)
    for f in files:
        if f.status == "removed":
            f.skipped_reason = "removed"
        else:
            f.content, f.skipped_reason = github.get_file(ref.owner, ref.repo, f.path, facts.submitted_commit)
    total = stored_total(facts.submitted_summary, len(files))
    return PullRequestSnapshot(
        owner=ref.owner,
        repo=ref.repo,
        number=ref.number,
        title=pr.get("title") or "",
        head_sha=facts.submitted_commit,
        base_ref=(pr.get("base") or {}).get("ref"),
        head_ref=(pr.get("head") or {}).get("ref"),
        files=files,
        files_truncated=total > len(files),
        changed_files_total=total,
        current_head_sha=current_head,
    )


def run_ai_review(facts: RequestFacts, scope: AIReviewScope,
                  github: GitHubClient | None = None, ai: OpenAIClient | None = None) -> AIReview:
    """Raises GitHubError or AIServiceError (both carry status_code and a safe message)."""
    ai = ai or OpenAIClient()
    ai.ensure_configured()  # fail before spending GitHub requests

    own_client = github is None
    github = github or GitHubClient()
    try:
        if facts.submitted_commit:
            snapshot = _submitted_snapshot(github, facts)
        else:  # Git data entered manually: the PR as it is now
            snapshot = github.fetch_pull_request(facts.pull_request_url)
        extra = _related(github, snapshot) if scope is AIReviewScope.EXTENDED else []
    finally:
        if own_client:
            github.close()

    review_input = build_input(facts, snapshot, scope, extra)
    review_input.head_moved = bool(snapshot.current_head_sha and snapshot.current_head_sha != snapshot.head_sha)
    raw = ai.complete_json(SYSTEM_PROMPT, review_input.text, OUTPUT_SCHEMA, "ai_review")
    try:
        output = AIReviewOutput.model_validate(raw)
    except ValidationError:
        raise AIServiceError("The AI service returned an invalid review.") from None

    if review_input.secrets_masked:
        output.red_flags.insert(0, f"{review_input.secrets_masked} hard-coded secret(s) detected and masked")
    if review_input.head_moved:
        output.red_flags.insert(0, HEAD_MOVED_FLAG)
    return AIReview(input=review_input, output=output, model_name=ai.model)
