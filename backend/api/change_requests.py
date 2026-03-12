from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.db import get_db
from backend.models.change_request import ChangeRequest
from backend.models.user import User
from backend.models.approval import Approval
from backend.models.enums import RequestStatus, ApprovalDecision
from backend.schemas.change_request import (
    ChangeRequestCreate,
    ChangeRequestResponse,
    ApprovalAction,
)
from backend.core.dependencies import get_current_user
from backend.services.audit_service import log_action
router = APIRouter(prefix="/change-requests", tags=["Change Requests"])


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

    new_request = ChangeRequest(
        title=request_data.title,
        description=request_data.description,
        request_type=request_data.request_type,
        target_system=request_data.target_system,
        environment=request_data.environment,
        risk_level=request_data.risk_level,
        status=RequestStatus.PENDING_REVIEW,
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

    return new_request


@router.get("/", response_model=list[ChangeRequestResponse])
def list_change_requests(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role.name == "admin":
        return db.query(ChangeRequest).all()

    return db.query(ChangeRequest).filter(
        (ChangeRequest.created_by == current_user.id) |
        (ChangeRequest.assigned_reviewer_id == current_user.id)
    ).all()


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
            change_request.assigned_reviewer_id != current_user.id
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

    if current_user.role.name != "admin" and change_request.assigned_reviewer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the assigned reviewer or admin can approve this request")

    if change_request.created_by == current_user.id:
        raise HTTPException(status_code=403, detail="You cannot approve your own request")

    if change_request.status != RequestStatus.PENDING_REVIEW:
        raise HTTPException(status_code=400, detail="Only pending requests can be approved")

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
        details=action.decision_comment or "Approved without comment"
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

    if current_user.role.name != "admin" and change_request.assigned_reviewer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the assigned reviewer or admin can reject this request")

    if change_request.created_by == current_user.id:
        raise HTTPException(status_code=403, detail="You cannot reject your own request")

    if change_request.status != RequestStatus.PENDING_REVIEW:
        raise HTTPException(status_code=400, detail="Only pending requests can be rejected")

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
        details=action.decision_comment or "Rejected without comment"
    )
    db.commit()

    return change_request