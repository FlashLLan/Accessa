from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.db import get_db
from backend.models.change_request import ChangeRequest
from backend.models.review_action import ReviewAction
from backend.models.user import User
from backend.models.enums import RequestStatus, ReviewActionType
from backend.core.dependencies import (
    ClientInfo,
    get_client_info,
    get_current_user,
    get_current_workspace_id,
    get_request_or_404,
    get_user_or_404,
)
from backend.schemas.review_action import ReviewActionResponse
from backend.services.approval_service import get_allowed_approver_roles
from backend.services.audit_service import log_action

router = APIRouter(prefix="/change-requests", tags=["Review Actions"])



class ReviewTransferPayload(BaseModel):
    target_reviewer_id: int
    comment: str | None = None


def _check_access(cr: ChangeRequest, current_user: User):
    if current_user.role.name == "admin":
        return
    if cr.created_by != current_user.id and cr.assigned_reviewer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")


def _get_target_reviewer(target_id: int, current_user: User, db: Session, workspace_id: int) -> User:
    # A user from another workspace is indistinguishable from a non-existent one (404).
    target = get_user_or_404(
        db, workspace_id, target_id, active_only=True, detail="Target reviewer not found or inactive"
    )
    if target.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot transfer to yourself")
    return target


def _assert_can_transfer(cr: ChangeRequest, current_user: User, verb: str):
    """Only the assigned reviewer (or an admin) may hand a request on.

    Escalation and delegation move assigned_reviewer_id to the target, so after
    a transfer the previous reviewer loses this right automatically.
    """
    if current_user.role.name == "admin":
        return
    if current_user.id != cr.assigned_reviewer_id:
        raise HTTPException(status_code=403, detail=f"Only the assigned reviewer or admin can {verb}")


def _assert_matrix_eligible(target: User, cr: ChangeRequest):
    eligible_roles = get_allowed_approver_roles(cr.creator.role.name, cr.risk_level.value)
    if target.role.name not in eligible_roles:
        raise HTTPException(
            status_code=400,
            detail="Target reviewer is not eligible to review this request per the approval matrix.",
        )


@router.get("/{request_id}/review-actions", response_model=list[ReviewActionResponse])
def list_review_actions(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    workspace_id: int = Depends(get_current_workspace_id),
):
    cr = get_request_or_404(db, workspace_id, request_id)
    _check_access(cr, current_user)

    return (
        db.query(ReviewAction)
        .filter(ReviewAction.change_request_id == request_id)
        .order_by(ReviewAction.created_at.asc())
        .all()
    )


@router.post("/{request_id}/escalate", response_model=ReviewActionResponse)
def escalate_request(
    request_id: int,
    payload: ReviewTransferPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    workspace_id: int = Depends(get_current_workspace_id),
    client: ClientInfo = Depends(get_client_info),
):
    cr = get_request_or_404(db, workspace_id, request_id)

    _assert_can_transfer(cr, current_user, "escalate")

    if cr.status != RequestStatus.PENDING_REVIEW:
        raise HTTPException(status_code=400, detail="Only pending requests can be escalated")

    target = _get_target_reviewer(payload.target_reviewer_id, current_user, db, workspace_id)

    if target.id == cr.created_by:
        raise HTTPException(status_code=400, detail="Cannot escalate to the request creator")

    already_handled = db.query(ReviewAction).filter(
        ReviewAction.change_request_id == request_id,
        ReviewAction.actor_id == target.id,
    ).first()
    if already_handled:
        raise HTTPException(
            status_code=400,
            detail="Cannot escalate to a reviewer who has already handled this request",
        )

    # Seniority comes from the roles table (roles.level), the same data the
    # approval policy is built on, not from a list duplicated in code.
    current_level = current_user.role.level
    target_level = target.role.level
    if target_level <= current_level:
        raise HTTPException(
            status_code=400,
            detail="Escalation must go to a higher role. Use delegation for the same role.",
        )

    _assert_matrix_eligible(target, cr)

    cr.assigned_reviewer_id = target.id

    action = ReviewAction(
        change_request_id=request_id,
        actor_id=current_user.id,
        action_type=ReviewActionType.ESCALATE,
        target_reviewer_id=target.id,
        comment=payload.comment,
    )
    db.add(action)
    db.flush()  # assign ids; committed together with the audit entry below

    log_action(
        db=db,
        ip_address=client.ip_address,
        user_agent=client.user_agent,
        user_id=current_user.id,
        action="REQUEST_ESCALATED",
        entity_type="change_request",
        entity_id=request_id,
        request_id=request_id,
        severity="medium",
        details=f"Escalated to reviewer_id={target.id} ({target.full_name})",
    )
    db.commit()

    return action


@router.post("/{request_id}/delegate", response_model=ReviewActionResponse)
def delegate_request(
    request_id: int,
    payload: ReviewTransferPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    workspace_id: int = Depends(get_current_workspace_id),
    client: ClientInfo = Depends(get_client_info),
):
    cr = get_request_or_404(db, workspace_id, request_id)

    _assert_can_transfer(cr, current_user, "delegate")

    if cr.status != RequestStatus.PENDING_REVIEW:
        raise HTTPException(status_code=400, detail="Only pending requests can be delegated")

    target = _get_target_reviewer(payload.target_reviewer_id, current_user, db, workspace_id)

    if target.id == cr.created_by:
        raise HTTPException(status_code=400, detail="Cannot delegate to the request creator")

    # Seniority comes from the roles table (roles.level), the same data the
    # approval policy is built on, not from a list duplicated in code.
    current_level = current_user.role.level
    target_level = target.role.level
    if target_level < current_level:
        raise HTTPException(
            status_code=400,
            detail="Delegation to a lower role is not allowed.",
        )
    if target_level > current_level:
        raise HTTPException(
            status_code=400,
            detail="Delegation to a higher role is not allowed. Use escalation instead.",
        )

    _assert_matrix_eligible(target, cr)

    already_handled = db.query(ReviewAction).filter(
        ReviewAction.change_request_id == request_id,
        ReviewAction.actor_id == target.id,
    ).first()
    if already_handled:
        raise HTTPException(
            status_code=400,
            detail="Cannot delegate to a reviewer who has already handled this request",
        )

    cr.assigned_reviewer_id = target.id
    cr.status = RequestStatus.PENDING_REVIEW

    action = ReviewAction(
        change_request_id=request_id,
        actor_id=current_user.id,
        action_type=ReviewActionType.DELEGATE,
        target_reviewer_id=target.id,
        comment=payload.comment,
    )
    db.add(action)
    db.flush()  # assign ids; committed together with the audit entry below

    log_action(
        db=db,
        ip_address=client.ip_address,
        user_agent=client.user_agent,
        user_id=current_user.id,
        action="REQUEST_DELEGATED",
        entity_type="change_request",
        entity_id=request_id,
        request_id=request_id,
        severity="medium",
        details=f"Delegated to reviewer_id={target.id} ({target.full_name})",
    )
    db.commit()

    return action
