from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.db import get_db
from backend.models.change_request import ChangeRequest
from backend.models.ai_review_result import AIReviewResult
from backend.core.dependencies import get_current_user, get_current_workspace_id, get_request_or_404
from backend.models.user import User
from backend.schemas.ai_review_result import AIReviewResultResponse
from backend.services.audit_service import log_action

router = APIRouter(prefix="/change-requests", tags=["AI Review"])


def _check_access(cr: ChangeRequest, current_user: User):
    # Same rule as the other request endpoints: admin, creator or assigned reviewer.
    if current_user.role.name == "admin":
        return
    authorized = cr.created_by == current_user.id or cr.assigned_reviewer_id == current_user.id
    if not authorized:
        raise HTTPException(status_code=403, detail="Access denied")


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
        .order_by(AIReviewResult.created_at.desc())
        .all()
    )


@router.post("/{request_id}/ai-review", response_model=AIReviewResultResponse)
def trigger_ai_review(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    workspace_id: int = Depends(get_current_workspace_id),
):
    """Stub: creates a placeholder AI review result. Replace with real AI call later."""
    cr = get_request_or_404(db, workspace_id, request_id)
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
