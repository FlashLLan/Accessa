from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.db import get_db
from backend.models.change_request import ChangeRequest
from backend.models.review_action import ReviewAction
from backend.models.user import User
from backend.models.enums import RequestStatus, ReviewActionType
from backend.core.dependencies import get_current_user, get_room_request_or_404, room_users
from backend.schemas.review_action import ReviewActionResponse
from backend.services.approval_service import get_allowed_approver_roles
from backend.services.audit_service import log_action

router = APIRouter(prefix="/change-requests", tags=["Review Actions"])

ROLE_HIERARCHY = {"junior": 0, "mid": 1, "senior": 2, "lead": 3, "admin": 4}


class ReviewTransferPayload(BaseModel):
    target_reviewer_id: int
    comment: str | None = None


def _check_access(cr: ChangeRequest, current_user: User):
    if current_user.role.name == "admin":
        return
    if (
        cr.created_by != current_user.id
        and cr.assigned_reviewer_id != current_user.id
        and cr.current_reviewer_id != current_user.id
    ):
        raise HTTPException(status_code=403, detail="Access denied")


def _get_target_reviewer(target_id: int, current_user: User, db: Session) -> User:
    target = room_users(db, current_user).filter(User.id == target_id, User.is_active == True).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target reviewer not found or inactive")
    if target.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot transfer to yourself")
    return target


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
):
    cr = get_room_request_or_404(db, request_id, current_user)
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
):
    cr = get_room_request_or_404(db, request_id, current_user)

    if current_user.role.name != "admin":
        if cr.assigned_reviewer_id != current_user.id and cr.current_reviewer_id != current_user.id:
            raise HTTPException(status_code=403, detail="Only the assigned reviewer or admin can escalate")

    if cr.status != RequestStatus.PENDING_REVIEW:
        raise HTTPException(status_code=400, detail="Only pending requests can be escalated")

    target = _get_target_reviewer(payload.target_reviewer_id, current_user, db)

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

    current_level = ROLE_HIERARCHY.get(current_user.role.name, -1)
    target_level = ROLE_HIERARCHY.get(target.role.name, -1)
    if target_level <= current_level:
        raise HTTPException(
            status_code=400,
            detail="Escalation must go to a higher role. Use delegation for the same role.",
        )

    _assert_matrix_eligible(target, cr)

    from_status = cr.status.value
    cr.assigned_reviewer_id = target.id
    cr.current_reviewer_id = target.id

    action = ReviewAction(
        change_request_id=request_id,
        actor_id=current_user.id,
        action_type=ReviewActionType.ESCALATE,
        target_reviewer_id=target.id,
        from_status=from_status,
        to_status=from_status,
        comment=payload.comment,
    )
    db.add(action)
    db.commit()
    db.refresh(action)

    log_action(
        db=db,
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
):
    cr = get_room_request_or_404(db, request_id, current_user)

    if current_user.role.name != "admin":
        if cr.assigned_reviewer_id != current_user.id and cr.current_reviewer_id != current_user.id:
            raise HTTPException(status_code=403, detail="Only the assigned reviewer or admin can delegate")

    if cr.status != RequestStatus.PENDING_REVIEW:
        raise HTTPException(status_code=400, detail="Only pending requests can be delegated")

    target = _get_target_reviewer(payload.target_reviewer_id, current_user, db)

    if target.id == cr.created_by:
        raise HTTPException(status_code=400, detail="Cannot delegate to the request creator")

    current_level = ROLE_HIERARCHY.get(current_user.role.name, -1)
    target_level = ROLE_HIERARCHY.get(target.role.name, -1)
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

    from_status = cr.status.value
    cr.assigned_reviewer_id = target.id
    cr.current_reviewer_id = target.id
    cr.status = RequestStatus.PENDING_REVIEW

    action = ReviewAction(
        change_request_id=request_id,
        actor_id=current_user.id,
        action_type=ReviewActionType.DELEGATE,
        target_reviewer_id=target.id,
        from_status=from_status,
        to_status=RequestStatus.PENDING_REVIEW.value,
        comment=payload.comment,
    )
    db.add(action)
    db.commit()
    db.refresh(action)

    log_action(
        db=db,
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
