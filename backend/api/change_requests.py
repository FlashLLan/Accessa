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
from backend.core.dependencies import get_current_user
from backend.services.audit_service import log_action
from backend.services.approval_service import can_user_decide_request
from backend.models.comment import Comment
from backend.schemas.comment import CommentCreate, CommentResponse
router = APIRouter(prefix="/change-requests", tags=["Change Requests"])

def _get_active_admin_count(db: Session) -> int:
    return (
        db.query(User)
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
    current_user: User = Depends(get_current_user)
):
    reviewer = db.query(User).filter(User.id == request_data.assigned_reviewer_id).first()
    if not reviewer:
        raise HTTPException(status_code=400, detail="Assigned reviewer not found")

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
        created_by=current_user.id,
        assigned_reviewer_id=request_data.assigned_reviewer_id
    )

    db.add(new_request)
    db.commit()
    db.refresh(new_request)

    log_action(
        db=db,
        user_id=current_user.id,
        action="create_change_request",
        entity_type="change_request",
        entity_id=new_request.id,
        details=f"Created request '{new_request.title}' assigned to reviewer_id={new_request.assigned_reviewer_id}"
    )
    db.commit()

    if request_data.git_context is not None and request_data.git_context.has_any_data():
        gc = request_data.git_context
        git_ctx = GitContext(
            change_request_id=new_request.id,
            **gc.model_dump(),
        )
        db.add(git_ctx)
        db.commit()
        log_action(
            db=db,
            user_id=current_user.id,
            action="git_context_linked",
            entity_type="change_request",
            entity_id=new_request.id,
            request_id=new_request.id,
            details=(
                f"Git context linked: "
                f"repo={gc.repository_url or '-'}, "
                f"branch={gc.branch_name or '-'}, "
                f"commit={gc.commit_hash or '-'}"
            ),
        )
        db.commit()
        db.refresh(new_request)

    return new_request


@router.get("/", response_model=list[ChangeRequestResponse])
def list_change_requests(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role.name == "admin":
        return db.query(ChangeRequest).order_by(ChangeRequest.created_at.desc()).all()

    return db.query(ChangeRequest).filter(
        (ChangeRequest.created_by == current_user.id) |
        (ChangeRequest.assigned_reviewer_id == current_user.id) |
        (ChangeRequest.current_reviewer_id == current_user.id)
    ).order_by(ChangeRequest.created_at.desc()).all()


@router.get("/{request_id}", response_model=ChangeRequestResponse)
def get_change_request(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    change_request = db.query(ChangeRequest).filter(ChangeRequest.id == request_id).first()

    if not change_request:
        raise HTTPException(status_code=404, detail="Change request not found")

    if current_user.role.name != "admin":
        if (
            change_request.created_by != current_user.id and
            change_request.assigned_reviewer_id != current_user.id and
            change_request.current_reviewer_id != current_user.id
        ):
            raise HTTPException(status_code=403, detail="Access denied")

    return change_request


@router.post("/{request_id}/approve", response_model=ChangeRequestResponse)
def approve_change_request(
    request_id: int,
    action: ApprovalAction,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    change_request = db.query(ChangeRequest).filter(ChangeRequest.id == request_id).first()

    if not change_request:
        raise HTTPException(status_code=404, detail="Change request not found")

    active_admin_count = None
    if change_request.creator.role.name == "admin":
        active_admin_count = _get_active_admin_count(db)

    allowed, reason = can_user_decide_request(current_user, change_request, active_admin_count)

    if not allowed:
        if reason == "not_pending":
            raise HTTPException(status_code=400, detail="Only pending requests can be approved")
        if reason == "self_approval":
            raise HTTPException(status_code=403, detail="You cannot approve your own request")
        if reason == "not_current_reviewer":
            raise HTTPException(status_code=403, detail="This request has been escalated or delegated to another reviewer.")
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
    db.commit()
    db.refresh(change_request)

    log_action(
        db=db,
        user_id=current_user.id,
        action="approve_change_request",
        entity_type="change_request",
        entity_id=change_request.id,
        details=(
            f"Approved | approver_role={current_user.role.name} | "
            f"requester_role={change_request.creator.role.name} | "
            f"severity={change_request.risk_level.value} | "
            f"comment={action.decision_comment or 'none'}"
        )
    )
    db.commit()

    return change_request


@router.post("/{request_id}/reject", response_model=ChangeRequestResponse)
def reject_change_request(
    request_id: int,
    action: ApprovalAction,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    change_request = db.query(ChangeRequest).filter(ChangeRequest.id == request_id).first()

    if not change_request:
        raise HTTPException(status_code=404, detail="Change request not found")

    active_admin_count = None
    if change_request.creator.role.name == "admin":
        active_admin_count = _get_active_admin_count(db)

    allowed, reason = can_user_decide_request(current_user, change_request, active_admin_count)

    if not allowed:
        if reason == "not_pending":
            raise HTTPException(status_code=400, detail="Only pending requests can be rejected")
        if reason == "self_approval":
            raise HTTPException(status_code=403, detail="You cannot reject your own request")
        if reason == "not_current_reviewer":
            raise HTTPException(status_code=403, detail="This request has been escalated or delegated to another reviewer.")
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
    db.commit()
    db.refresh(change_request)

    log_action(
        db=db,
        user_id=current_user.id,
        action="reject_change_request",
        entity_type="change_request",
        entity_id=change_request.id,
        details=(
            f"Rejected | approver_role={current_user.role.name} | "
            f"requester_role={change_request.creator.role.name} | "
            f"severity={change_request.risk_level.value} | "
            f"comment={action.decision_comment or 'none'}"
        )
    )
    db.commit()

    return change_request


@router.get("/{request_id}/approvals", response_model=list[ApprovalHistoryResponse])
def get_request_approvals(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    change_request = db.query(ChangeRequest).filter(ChangeRequest.id == request_id).first()

    if not change_request:
        raise HTTPException(status_code=404, detail="Change request not found")

    if current_user.role.name != "admin":
        if (
            change_request.created_by != current_user.id and
            change_request.assigned_reviewer_id != current_user.id and
            change_request.current_reviewer_id != current_user.id
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
    current_user: User = Depends(get_current_user)
):
    change_request = db.query(ChangeRequest).filter(ChangeRequest.id == request_id).first()

    if not change_request:
        raise HTTPException(status_code=404, detail="Change request not found")

    if change_request.created_by != current_user.id and current_user.role.name != "admin":
        raise HTTPException(status_code=403, detail="Only the creator or admin can edit this request")

    if change_request.status not in [RequestStatus.DRAFT, RequestStatus.REJECTED]:
        raise HTTPException(
            status_code=400,
            detail="Only draft or rejected requests can be edited"
        )

    if request_data.assigned_reviewer_id is not None:
        reviewer = db.query(User).filter(User.id == request_data.assigned_reviewer_id).first()
        if not reviewer:
            raise HTTPException(status_code=400, detail="Assigned reviewer not found")
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

    db.commit()
    db.refresh(change_request)

    log_action(
        db=db,
        user_id=current_user.id,
        action="update_change_request",
        entity_type="change_request",
        entity_id=change_request.id,
        details="Change request updated"
    )
    db.commit()

    return change_request


@router.post("/{request_id}/submit", response_model=ChangeRequestResponse)
def submit_change_request(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    change_request = db.query(ChangeRequest).filter(ChangeRequest.id == request_id).first()

    if not change_request:
        raise HTTPException(status_code=404, detail="Change request not found")

    if change_request.created_by != current_user.id and current_user.role.name != "admin":
        raise HTTPException(status_code=403, detail="Only the creator or admin can submit this request")

    if change_request.status not in [RequestStatus.DRAFT, RequestStatus.REJECTED]:
        raise HTTPException(
            status_code=400,
            detail="Only draft or rejected requests can be submitted for review"
        )

    change_request.status = RequestStatus.PENDING_REVIEW
    db.commit()
    db.refresh(change_request)

    log_action(
        db=db,
        user_id=current_user.id,
        action="submit_change_request",
        entity_type="change_request",
        entity_id=change_request.id,
        details="Submitted for review"
    )
    db.commit()

    return change_request

@router.get("/{request_id}/comments", response_model=list[CommentResponse])
def list_request_comments(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    change_request = db.query(ChangeRequest).filter(ChangeRequest.id == request_id).first()

    if not change_request:
        raise HTTPException(status_code=404, detail="Change request not found")

    if current_user.role.name != "admin":
        if (
            change_request.created_by != current_user.id and
            change_request.assigned_reviewer_id != current_user.id and
            change_request.current_reviewer_id != current_user.id
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
    current_user: User = Depends(get_current_user)
):
    change_request = db.query(ChangeRequest).filter(ChangeRequest.id == request_id).first()

    if not change_request:
        raise HTTPException(status_code=404, detail="Change request not found")

    if current_user.role.name != "admin":
        if (
            change_request.created_by != current_user.id and
            change_request.assigned_reviewer_id != current_user.id and
            change_request.current_reviewer_id != current_user.id
        ):
            raise HTTPException(status_code=403, detail="Access denied")

    new_comment = Comment(
        change_request_id=request_id,
        user_id=current_user.id,
        comment_text=comment_data.comment_text
    )

    db.add(new_comment)
    db.commit()
    db.refresh(new_comment)

    log_action(
        db=db,
        user_id=current_user.id,
        action="add_comment",
        entity_type="change_request",
        entity_id=request_id,
        details=comment_data.comment_text
    )
    db.commit()

    return new_comment


@router.post("/{request_id}/apply", response_model=ChangeRequestResponse)
def apply_change_request(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    change_request = db.query(ChangeRequest).filter(ChangeRequest.id == request_id).first()

    if not change_request:
        raise HTTPException(status_code=404, detail="Change request not found")

    if current_user.role.name != "admin" and change_request.created_by != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Only the creator or admin can mark this request as applied"
        )

    if change_request.status != RequestStatus.APPROVED:
        raise HTTPException(
            status_code=400,
            detail="Only approved requests can be marked as applied"
        )

    change_request.status = RequestStatus.APPLIED
    db.commit()
    db.refresh(change_request)

    log_action(
        db=db,
        user_id=current_user.id,
        action="apply_change_request",
        entity_type="change_request",
        entity_id=change_request.id,
        details="Marked request as applied"
    )
    db.commit()

    return change_request