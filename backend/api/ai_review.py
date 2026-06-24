from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.db import get_db
from backend.models.change_request import ChangeRequest
from backend.models.ai_review_result import AIReviewResult
from backend.core.dependencies import get_current_user
from backend.models.user import User
from backend.schemas.ai_review_result import AIReviewResultResponse
from backend.services.audit_service import log_action

router = APIRouter(prefix="/change-requests", tags=["AI Review"])


def _get_request_or_404(request_id: int, db: Session) -> ChangeRequest:
    cr = db.query(ChangeRequest).filter(ChangeRequest.id == request_id).first()
    if not cr:
        raise HTTPException(status_code=404, detail="Change request not found")
    return cr


def _check_access(cr: ChangeRequest, current_user: User):
    if current_user.role.name == "admin":
        return
    if cr.created_by != current_user.id and cr.assigned_reviewer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")


@router.get("/{request_id}/ai-review", response_model=list[AIReviewResultResponse])
def get_ai_review_results(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cr = _get_request_or_404(request_id, db)
    _check_access(cr, current_user)

    return (
        db.query(AIReviewResult)
        .filter(AIReviewResult.change_request_id == request_id)
        .order_by(AIReviewResult.created_at.desc())
        .all()
    )


@router.post("/{request_id}/ai-review", response_model=AIReviewResultResponse)
def trigger_ai_review(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stub: creates a placeholder AI review result. Replace with real AI call later."""
    cr = _get_request_or_404(request_id, db)
    _check_access(cr, current_user)

    result = AIReviewResult(
        change_request_id=request_id,
        summary="AI review not yet configured. This is a placeholder result.",
        suggested_risk_level=cr.risk_level.value,
        recommended_reviewer_role=None,
        impact_area=cr.target_system,
        red_flags="[]",
        verification_checklist="[]",
        improvement_suggestions="[]",
        model_name="stub",
        prompt_version="0.0.1",
    )

    db.add(result)
    db.commit()
    db.refresh(result)

    log_action(
        db=db,
        user_id=current_user.id,
        action="AI_REVIEW_GENERATED",
        entity_type="change_request",
        entity_id=request_id,
        request_id=request_id,
        severity="low",
        details=f"AI review triggered (stub) for request {request_id}",
    )
    db.commit()

    return result
