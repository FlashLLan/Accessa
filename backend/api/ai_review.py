import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database.db import get_db
from backend.core.limiter import limiter
from backend.models.change_request import ChangeRequest
from backend.models.ai_review_result import AIReviewResult
from backend.models.enums import AIReviewScope, GitContextSource, RequestStatus
from backend.core.dependencies import get_current_user, get_current_workspace_id, get_request_or_404, ClientInfo, get_client_info
from backend.models.user import User
from backend.schemas.ai_review_result import AIReviewResultResponse, AIReviewTrigger
from backend.services.ai_review_service import (
    RequestFacts,
    current_head_quietly,
    review_target_commit,
    run_ai_review,
)
from backend.services.audit_service import log_action
from backend.services.github_service import GitHubError
from backend.services.openai_client import AIServiceError

router = APIRouter(prefix="/change-requests", tags=["AI Review"])

# 409 detail code when a regeneration would use the same commit and scope.
AI_REVIEW_UNCHANGED = "ai_review_unchanged"
SCOPE_LABELS = {AIReviewScope.CHANGED_FILES: "Changed files", AIReviewScope.EXTENDED: "Extended"}


def _check_access(cr: ChangeRequest, current_user: User):
    # Reading: same rule as the other request endpoints: admin, creator or assigned reviewer.
    if current_user.role.name == "admin":
        return
    authorized = cr.created_by == current_user.id or cr.assigned_reviewer_id == current_user.id
    if not authorized:
        raise HTTPException(status_code=403, detail="Access denied")


def _check_can_generate(cr: ChangeRequest, current_user: User):
    # Only the assigned reviewer, while the request waits for their decision. For an
    # admin's request that is the second admin (two-admin rule); other admins and
    # the creator cannot trigger it.
    if cr.assigned_reviewer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the assigned reviewer can generate an AI review")
    if cr.status != RequestStatus.PENDING_REVIEW:
        raise HTTPException(status_code=409, detail="An AI review can only be generated while the request is pending review")


@router.get("/{request_id}/ai-review", response_model=list[AIReviewResultResponse])
def get_ai_review_results(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    workspace_id: int = Depends(get_current_workspace_id),
):
    cr = get_request_or_404(db, workspace_id, request_id)
    _check_access(cr, current_user)

    return (
        db.query(AIReviewResult)
        .filter(AIReviewResult.change_request_id == request_id)
        .order_by(AIReviewResult.created_at.desc(), AIReviewResult.id.desc())
        .all()
    )


@router.post("/{request_id}/ai-review", response_model=AIReviewResultResponse)
@limiter.limit("10/minute")
def trigger_ai_review(
    request: Request,
    request_id: int,
    payload: AIReviewTrigger | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    workspace_id: int = Depends(get_current_workspace_id),
    client: ClientInfo = Depends(get_client_info),
):
    """Advisory AI review of the request and its public GitHub pull request.
    Never changes the request's risk level or status. If GitHub or the AI service
    fails, an error is returned and nothing is saved."""
    trigger = payload or AIReviewTrigger()
    scope = trigger.scope
    cr = get_request_or_404(db, workspace_id, request_id)
    _check_can_generate(cr, current_user)

    git = cr.git_context
    if git is None or not git.pull_request_url:
        raise HTTPException(status_code=400, detail="Link a GitHub pull request in the Git context first")

    facts = RequestFacts(
        title=cr.title,
        description=cr.description,
        request_type=cr.request_type.value,
        target_system=cr.target_system,
        environment=cr.environment.value,
        risk_level=cr.risk_level.value,
        author_role=cr.creator.role.name if cr.creator and cr.creator.role else None,
        repository_name=git.repository_name,
        branch_name=git.branch_name,
        target_branch=git.target_branch,
        pull_request_url=git.pull_request_url,
        # Fetched from GitHub at submission: review that commit, not the current head.
        submitted_commit=git.commit_hash if git.source == GitContextSource.GITHUB else None,
        submitted_diff=git.diff_text if git.source == GitContextSource.GITHUB else None,
        submitted_summary=git.changed_files_summary if git.source == GitContextSource.GITHUB else None,
    )
    # Earlier results, oldest first (their position is "review n of N" in the UI).
    earlier = (
        db.query(AIReviewResult.id, AIReviewResult.reviewed_commit, AIReviewResult.review_scope)
        .filter(AIReviewResult.change_request_id == request_id)
        .order_by(AIReviewResult.created_at.asc(), AIReviewResult.id.asc())
        .all()
    )
    # The latest review with the requested scope: alternating scopes must not
    # hide that this scope was already reviewed at the same commit.
    same_scope = [(n, row) for n, row in enumerate(earlier, start=1) if row.review_scope == scope]
    match = same_scope[-1] if same_scope else None
    # GitHub and the AI can take up to a minute: do not keep a transaction open.
    db.rollback()

    try:
        # Same commit as the latest review with the same scope: the AI would see
        # the same input. Ask first (409) instead of paying for an identical review.
        if match and not trigger.force:
            number, matched = match
            target_commit = review_target_commit(facts)
            if matched.reviewed_commit == target_commit:
                # Submitted snapshot: the PR may have moved on, which the reviewer
                # should know (one GitHub request; unknown if GitHub fails).
                current_head = current_head_quietly(facts) if facts.submitted_commit else target_commit
                head_moved = current_head is not None and current_head != target_commit
                short = target_commit[:7]
                scope_label = SCOPE_LABELS[scope]
                which = f"review {number} of {len(earlier)}"
                if head_moved:
                    message = (
                        f"The pull request has new commits since submission (now at {current_head[:7]}). "
                        f"This request covers only {short}; new changes require a new request. "
                        f"A new AI review will still cover only the submitted commit {short}, which was "
                        f"already reviewed with the {scope_label} scope ({which}). Generate it again anyway?"
                    )
                else:
                    message = (
                        f"Nothing has changed since {which}: same commit {short} and same scope "
                        f"({scope_label}). Generate it again anyway?"
                    )
                raise HTTPException(status_code=409, detail={
                    "code": AI_REVIEW_UNCHANGED,
                    "message": message,
                    "commit": target_commit,
                    "current_head": current_head,
                    "head_moved": head_moved,
                    "scope": scope.value,
                    "matching_review_id": matched.id,
                    "matching_review_number": number,
                })
        review = run_ai_review(facts, scope)
    except (GitHubError, AIServiceError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from None

    # The request may have been decided, escalated or delegated in the meantime.
    db.refresh(cr)
    if cr.assigned_reviewer_id != current_user.id or cr.status != RequestStatus.PENDING_REVIEW:
        raise HTTPException(status_code=409, detail="The request changed while the AI review was running; nothing was saved")

    data, out = review.input, review.output
    result = AIReviewResult(
        change_request_id=request_id,
        summary=out.summary,
        suggested_risk_level=out.suggested_risk_level,
        recommended_reviewer_role=out.recommended_reviewer_role,
        impact_area=out.impact_area,
        red_flags=json.dumps(out.red_flags),
        verification_checklist=json.dumps(out.verification_checklist),
        improvement_suggestions=json.dumps(out.improvement_suggestions),
        model_name=review.model_name,
        prompt_version=review.prompt_version,
        reviewed_commit=data.reviewed_commit,
        review_scope=data.review_scope,
        files_reviewed=data.files_reviewed,
        files_skipped=data.files_skipped,
        changed_files_total=data.changed_files_total,
        input_truncated=data.input_truncated,
        secrets_masked=data.secrets_masked,
        # Snapshot: stays "senior" after an escalation or a later role change.
        generated_by_role=current_user.role.name,
    )
    db.add(result)
    db.flush()  # assign ids; committed together with the audit entry below

    log_action(
        db=db,
        ip_address=client.ip_address,
        user_agent=client.user_agent,
        user_id=current_user.id,
        action="AI_REVIEW_GENERATED",
        entity_type="change_request",
        entity_id=request_id,
        request_id=request_id,
        severity="low",
        new_value=data.review_scope.value,
        details=(
            f"AI review generated: commit {data.reviewed_commit}, scope {data.review_scope.value}, "
            f"{len(data.files_reviewed)} file(s) reviewed, {len(data.files_skipped)} skipped, "
            f"{data.secrets_masked} secret(s) masked{', input truncated' if data.input_truncated else ''}, "
            f"model {review.model_name}, prompt {review.prompt_version}"
        ),
    )
    db.commit()

    return result
