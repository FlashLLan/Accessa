from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.models.enums import RequestStatus, ApprovalDecision, RiskLevel
from database.db import get_db
from backend.models.change_request import ChangeRequest
from backend.models.git_context import GitContext
from backend.models.user import User
from backend.models.role import Role
from backend.models.approval import Approval
from backend.schemas.change_request import (
    ChangeRequestCreate,
    ChangeRequestResponse,
    ChangeRequestUpdate,
    ApprovalAction,
    ApprovalHistoryResponse,
)
from backend.core.dependencies import (
    ClientInfo,
    get_client_info,
    get_current_user,
    get_current_workspace_id,
    scoped,
    get_request_or_404,
    get_user_or_404,
)
from backend.api.git_context import format_identifiers
from backend.models.enums import GitContextSource
from backend.services.github_service import GitHubError
from backend.services.pull_request_data import fetch_for_submission, is_github_pull_request
from backend.services.audit_service import log_action
from backend.core.timeutils import utc_now
from backend.services.approval_service import can_user_decide_request
from backend.models.comment import Comment
from backend.schemas.comment import CommentCreate, CommentResponse
router = APIRouter(prefix="/change-requests", tags=["Change Requests"])

def _get_active_admin_count(db: Session, workspace_id: int) -> int:
    """Active admins in one workspace; the two-admin rule never counts other workspaces."""
    return (
        scoped(db, User, workspace_id)
        .join(User.role)
        .filter(User.is_active == True, Role.name == "admin")
        .count()
    )


def validate_reviewer_for_request(reviewer: User, risk_level: RiskLevel, requester_role: str):
    from backend.services.approval_service import get_allowed_approver_roles
    eligible_roles = get_allowed_approver_roles(requester_role, risk_level.value)
    if reviewer.role.name not in eligible_roles:
        raise HTTPException(
            status_code=400,
            detail="Assigned reviewer is not eligible to review this type of request."
        )

@router.post("/", response_model=ChangeRequestResponse)
def create_change_request(
    request_data: ChangeRequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    workspace_id: int = Depends(get_current_workspace_id),
    client: ClientInfo = Depends(get_client_info),
):
    reviewer = get_user_or_404(db, workspace_id, request_data.assigned_reviewer_id, detail="Assigned reviewer not found")

    if reviewer.id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot assign yourself as reviewer")

    validate_reviewer_for_request(reviewer, request_data.risk_level, current_user.role.name)

    new_request = ChangeRequest(
        title=request_data.title,
        description=request_data.description,
        request_type=request_data.request_type,
        target_system=request_data.target_system,
        environment=request_data.environment,
        risk_level=request_data.risk_level,
        status=RequestStatus.DRAFT,
        workspace_id=workspace_id,
        created_by=current_user.id,
        assigned_reviewer_id=request_data.assigned_reviewer_id
    )

    db.add(new_request)
    db.flush()  # assign ids; committed together with the audit entry below

    log_action(
        db=db,
        ip_address=client.ip_address,
        user_agent=client.user_agent,
        user_id=current_user.id,
        action="REQUEST_CREATED",
        entity_type="change_request",
        entity_id=new_request.id,
        severity="low",
        # No title: user-written text stays in change_requests, not in the audit log.
        details=f"Created request assigned to reviewer_id={new_request.assigned_reviewer_id}"
    )

    if request_data.git_context is not None and request_data.git_context.has_any_data():
        gc = request_data.git_context
        git_ctx = GitContext(
            change_request_id=new_request.id,
            **gc.model_dump(),
        )
        db.add(git_ctx)
        log_action(
            db=db,
            ip_address=client.ip_address,
            user_agent=client.user_agent,
            user_id=current_user.id,
            action="GIT_CONTEXT_LINKED",
            entity_type="change_request",
            entity_id=new_request.id,
            request_id=new_request.id,
            severity="low",
            # Technical identifiers only; never diff_text or changed_files_summary.
            details=f"Git context linked: {format_identifiers(gc.model_dump())}",
        )

    db.commit()
    db.refresh(new_request)
    return new_request


@router.get("/", response_model=list[ChangeRequestResponse])
def list_change_requests(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    workspace_id: int = Depends(get_current_workspace_id),
):
    if current_user.role.name == "admin":
        return scoped(db, ChangeRequest, workspace_id).order_by(ChangeRequest.created_at.desc()).all()

    return scoped(db, ChangeRequest, workspace_id).filter(
        (ChangeRequest.created_by == current_user.id) |
        (ChangeRequest.assigned_reviewer_id == current_user.id)
    ).order_by(ChangeRequest.created_at.desc()).all()


@router.get("/{request_id}", response_model=ChangeRequestResponse)
def get_change_request(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    workspace_id: int = Depends(get_current_workspace_id),
):
    change_request = get_request_or_404(db, workspace_id, request_id)

    if current_user.role.name != "admin":
        if (
            change_request.created_by != current_user.id and
            change_request.assigned_reviewer_id != current_user.id
        ):
            raise HTTPException(status_code=403, detail="Access denied")

    return change_request


@router.post("/{request_id}/approve", response_model=ChangeRequestResponse)
def approve_change_request(
    request_id: int,
    action: ApprovalAction,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    workspace_id: int = Depends(get_current_workspace_id),
    client: ClientInfo = Depends(get_client_info),
):
    change_request = get_request_or_404(db, workspace_id, request_id, for_update=True)

    active_admin_count = None
    if change_request.creator.role.name == "admin":
        active_admin_count = _get_active_admin_count(db, change_request.workspace_id)

    allowed, reason = can_user_decide_request(current_user, change_request, active_admin_count)

    if not allowed:
        if reason == "not_pending":
            raise HTTPException(status_code=400, detail="Only pending requests can be approved")
        if reason == "self_approval":
            raise HTTPException(status_code=403, detail="You cannot approve your own request")
        if reason == "not_assigned_reviewer":
            raise HTTPException(status_code=403, detail="Only the assigned reviewer can decide this request")
        if reason == "admin_insufficient_admins":
            raise HTTPException(
                status_code=400,
                detail="Admin request workflow requires at least two active admins."
            )
        raise HTTPException(status_code=403, detail="You are not allowed to approve this request.")

    approval = Approval(
        change_request_id=change_request.id,
        reviewer_id=current_user.id,
        decision=ApprovalDecision.APPROVED,
        decision_comment=action.decision_comment
    )

    db.add(approval)
    change_request.status = RequestStatus.APPROVED
    db.flush()  # assign ids; committed together with the audit entry below

    log_action(
        db=db,
        ip_address=client.ip_address,
        user_agent=client.user_agent,
        user_id=current_user.id,
        action="REQUEST_APPROVED",
        entity_type="change_request",
        entity_id=change_request.id,
        severity="high",
        details=(
            f"Approved | approver_role={current_user.role.name} | "
            f"requester_role={change_request.creator.role.name} | "
            f"risk_level={change_request.risk_level.value} | "
            # Only whether a comment was given: its text stays in the approvals table.
            f"comment={'yes' if (action.decision_comment or '').strip() else 'no'}"
        )
    )
    db.commit()

    return change_request


@router.post("/{request_id}/reject", response_model=ChangeRequestResponse)
def reject_change_request(
    request_id: int,
    action: ApprovalAction,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    workspace_id: int = Depends(get_current_workspace_id),
    client: ClientInfo = Depends(get_client_info),
):
    change_request = get_request_or_404(db, workspace_id, request_id, for_update=True)

    active_admin_count = None
    if change_request.creator.role.name == "admin":
        active_admin_count = _get_active_admin_count(db, change_request.workspace_id)

    allowed, reason = can_user_decide_request(current_user, change_request, active_admin_count)

    if not allowed:
        if reason == "not_pending":
            raise HTTPException(status_code=400, detail="Only pending requests can be rejected")
        if reason == "self_approval":
            raise HTTPException(status_code=403, detail="You cannot reject your own request")
        if reason == "not_assigned_reviewer":
            raise HTTPException(status_code=403, detail="Only the assigned reviewer can decide this request")
        if reason == "admin_insufficient_admins":
            raise HTTPException(
                status_code=400,
                detail="Admin request workflow requires at least two active admins."
            )
        raise HTTPException(status_code=403, detail="You are not allowed to reject this request.")

    approval = Approval(
        change_request_id=change_request.id,
        reviewer_id=current_user.id,
        decision=ApprovalDecision.REJECTED,
        decision_comment=action.decision_comment
    )

    db.add(approval)
    change_request.status = RequestStatus.REJECTED
    change_request.closed_at = utc_now()
    db.flush()  # assign ids; committed together with the audit entry below

    log_action(
        db=db,
        ip_address=client.ip_address,
        user_agent=client.user_agent,
        user_id=current_user.id,
        action="REQUEST_REJECTED",
        entity_type="change_request",
        entity_id=change_request.id,
        severity="high",
        details=(
            f"Rejected | approver_role={current_user.role.name} | "
            f"requester_role={change_request.creator.role.name} | "
            f"risk_level={change_request.risk_level.value} | "
            # Only whether a comment was given: its text stays in the approvals table.
            f"comment={'yes' if (action.decision_comment or '').strip() else 'no'}"
        )
    )
    db.commit()

    return change_request


@router.get("/{request_id}/approvals", response_model=list[ApprovalHistoryResponse])
def get_request_approvals(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    workspace_id: int = Depends(get_current_workspace_id),
):
    change_request = get_request_or_404(db, workspace_id, request_id)

    if current_user.role.name != "admin":
        if (
            change_request.created_by != current_user.id and
            change_request.assigned_reviewer_id != current_user.id
        ):
            raise HTTPException(status_code=403, detail="Access denied")

    return (
        db.query(Approval)
        .filter(Approval.change_request_id == request_id)
        .order_by(Approval.created_at.desc())
        .all()
    )


@router.patch("/{request_id}", response_model=ChangeRequestResponse)
def update_change_request(
    request_id: int,
    request_data: ChangeRequestUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    workspace_id: int = Depends(get_current_workspace_id),
    client: ClientInfo = Depends(get_client_info),
):
    change_request = get_request_or_404(db, workspace_id, request_id)

    # Only the author may change or submit their own request; admins have no exception
    # here, so an admin cannot alter or push someone else's draft into review.
    if change_request.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Only the creator can edit this request")

    if change_request.status != RequestStatus.DRAFT:
        raise HTTPException(
            status_code=400,
            detail="Only draft requests can be edited"
        )

    if request_data.assigned_reviewer_id is not None:
        reviewer = get_user_or_404(db, workspace_id, request_data.assigned_reviewer_id, detail="Assigned reviewer not found")
        if reviewer.id == current_user.id:
            raise HTTPException(status_code=400, detail="You cannot assign yourself as reviewer")

        new_risk_level = (
            request_data.risk_level
            if request_data.risk_level is not None
            else change_request.risk_level
        )
        validate_reviewer_for_request(reviewer, new_risk_level, change_request.creator.role.name)

    if request_data.assigned_reviewer_id is None and request_data.risk_level is not None:
        validate_reviewer_for_request(
            change_request.assigned_reviewer,
            request_data.risk_level,
            change_request.creator.role.name,
        )


    update_data = request_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(change_request, field, value)

    db.flush()  # assign ids; committed together with the audit entry below

    log_action(
        db=db,
        ip_address=client.ip_address,
        user_agent=client.user_agent,
        user_id=current_user.id,
        action="REQUEST_UPDATED",
        entity_type="change_request",
        entity_id=change_request.id,
        severity="low",
        details="Change request updated"
    )
    db.commit()

    return change_request


@router.post("/{request_id}/submit", response_model=ChangeRequestResponse)
def submit_change_request(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    workspace_id: int = Depends(get_current_workspace_id),
    client: ClientInfo = Depends(get_client_info),
):
    def check(cr: ChangeRequest) -> None:
        # Only the author may change or submit their own request; admins have no exception
        # here, so an admin cannot alter or push someone else's draft into review.
        if cr.created_by != current_user.id:
            raise HTTPException(status_code=403, detail="Only the creator can submit this request")
        if cr.status != RequestStatus.DRAFT:
            raise HTTPException(status_code=400, detail="Only draft requests can be submitted for review")

    # 1. Checks without a lock, so a request that cannot be submitted fails fast.
    change_request = get_request_or_404(db, workspace_id, request_id)
    check(change_request)
    pr_url = change_request.git_context.pull_request_url if change_request.git_context else None

    # 2. With a GitHub pull request link: fetch commit, file list and diff (FR-21)
    #    before any lock or write transaction is held. A failure refuses the
    #    submission and changes nothing.
    fetched = None
    if is_github_pull_request(pr_url):
        db.rollback()  # end the read transaction; GitHub may take a few seconds
        try:
            fetched = fetch_for_submission(pr_url)
        except GitHubError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from None

    # 3. Lock the row and re-check: the request may have changed meanwhile.
    change_request = get_request_or_404(db, workspace_id, request_id, for_update=True)
    check(change_request)
    git = change_request.git_context
    if fetched is not None and (git is None or git.pull_request_url != pr_url):
        raise HTTPException(status_code=409, detail="The Git context changed during submission; submit again")

    if fetched is not None:
        # Replaces whatever the requester pasted.
        git.commit_hash = fetched.commit_hash
        git.changed_files_summary = fetched.changed_files_summary
        git.diff_text = fetched.diff_text
        git.source = GitContextSource.GITHUB
        git.fetched_at = utc_now()
    elif git is not None:
        git.source = GitContextSource.MANUAL
        git.fetched_at = None

    change_request.status = RequestStatus.PENDING_REVIEW
    change_request.submitted_at = utc_now()
    db.flush()  # assign ids; committed together with the audit entry below

    if fetched is not None:
        submitted_details = (
            f"Submitted for review; Git data fetched from GitHub at commit {fetched.commit_hash}"
            + (f"; {fetched.secrets_masked} secret(s) masked" if fetched.secrets_masked else "")
            + (f"; {fetched.files_omitted} file(s) not included" if fetched.files_omitted else "")
        )
    elif git is not None:
        submitted_details = "Submitted for review; Git data entered manually (not verified)"
    else:
        submitted_details = "Submitted for review"

    log_action(
        db=db,
        ip_address=client.ip_address,
        user_agent=client.user_agent,
        user_id=current_user.id,
        action="REQUEST_SUBMITTED",
        entity_type="change_request",
        entity_id=change_request.id,
        severity="medium",
        details=submitted_details,
    )
    db.commit()

    return change_request

@router.get("/{request_id}/comments", response_model=list[CommentResponse])
def list_request_comments(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    workspace_id: int = Depends(get_current_workspace_id),
):
    change_request = get_request_or_404(db, workspace_id, request_id)

    if current_user.role.name != "admin":
        if (
            change_request.created_by != current_user.id and
            change_request.assigned_reviewer_id != current_user.id
        ):
            raise HTTPException(status_code=403, detail="Access denied")

    return (
        db.query(Comment)
        .filter(Comment.change_request_id == request_id)
        .order_by(Comment.created_at.asc())
        .all()
    )


@router.post("/{request_id}/comments", response_model=CommentResponse)
def add_comment_to_request(
    request_id: int,
    comment_data: CommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    workspace_id: int = Depends(get_current_workspace_id),
    client: ClientInfo = Depends(get_client_info),
):
    change_request = get_request_or_404(db, workspace_id, request_id)

    if current_user.role.name != "admin":
        if (
            change_request.created_by != current_user.id and
            change_request.assigned_reviewer_id != current_user.id
        ):
            raise HTTPException(status_code=403, detail="Access denied")

    new_comment = Comment(
        change_request_id=request_id,
        user_id=current_user.id,
        comment_text=comment_data.comment_text
    )

    db.add(new_comment)
    db.flush()  # assign ids; committed together with the audit entry below

    log_action(
        db=db,
        ip_address=client.ip_address,
        user_agent=client.user_agent,
        user_id=current_user.id,
        action="COMMENT_CREATED",
        entity_type="change_request",
        entity_id=request_id,
        severity="low",
        # The comment itself stays in the comments table; free text may contain
        # names or e-mail addresses, which the audit log never stores.
        details=f"Comment id={new_comment.id} added"
    )
    db.commit()

    return new_comment


@router.post("/{request_id}/apply", response_model=ChangeRequestResponse)
def apply_change_request(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    workspace_id: int = Depends(get_current_workspace_id),
    client: ClientInfo = Depends(get_client_info),
):
    change_request = get_request_or_404(db, workspace_id, request_id, for_update=True)

    if change_request.created_by != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Only the creator can mark this request as applied"
        )

    if change_request.status != RequestStatus.APPROVED:
        raise HTTPException(
            status_code=400,
            detail="Only approved requests can be marked as applied"
        )

    change_request.status = RequestStatus.APPLIED
    change_request.closed_at = utc_now()
    db.flush()  # assign ids; committed together with the audit entry below

    log_action(
        db=db,
        ip_address=client.ip_address,
        user_agent=client.user_agent,
        user_id=current_user.id,
        action="REQUEST_APPLIED",
        entity_type="change_request",
        entity_id=change_request.id,
        severity="high",
        details="Marked request as applied"
    )
    db.commit()

    return change_request