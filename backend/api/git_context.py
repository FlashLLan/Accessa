from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.db import get_db
from backend.models.change_request import ChangeRequest
from backend.models.git_context import GitContext
from backend.core.dependencies import get_current_user, get_current_workspace_id, get_request_or_404
from backend.models.user import User
from backend.schemas.git_context import GitContextCreate, GitContextResponse
from backend.services.audit_service import log_action

router = APIRouter(prefix="/change-requests", tags=["Git Context"])


def _check_access(cr: ChangeRequest, current_user: User):
    if current_user.role.name == "admin":
        return
    authorized = (
        cr.created_by == current_user.id
        or cr.assigned_reviewer_id == current_user.id
        or (cr.current_reviewer_id is not None and cr.current_reviewer_id == current_user.id)
    )
    if not authorized:
        raise HTTPException(status_code=403, detail="Access denied")


@router.get("/{request_id}/git-context", response_model=GitContextResponse)
def get_git_context(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    workspace_id: int = Depends(get_current_workspace_id),
):
    cr = get_request_or_404(db, workspace_id, request_id)
    _check_access(cr, current_user)

    if not cr.git_context:
        raise HTTPException(status_code=404, detail="No git context for this request")

    return cr.git_context


@router.post("/{request_id}/git-context", response_model=GitContextResponse)
def upsert_git_context(
    request_id: int,
    payload: GitContextCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    workspace_id: int = Depends(get_current_workspace_id),
):
    cr = get_request_or_404(db, workspace_id, request_id)
    _check_access(cr, current_user)

    if cr.git_context:
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(cr.git_context, field, value)
        db.commit()
        db.refresh(cr.git_context)
        git_ctx = cr.git_context
        audit_action = "git_context_updated"
    else:
        git_ctx = GitContext(
            change_request_id=request_id,
            **payload.model_dump(),
        )
        db.add(git_ctx)
        db.commit()
        db.refresh(git_ctx)
        audit_action = "git_context_linked"

    log_action(
        db=db,
        user_id=current_user.id,
        action=audit_action,
        entity_type="change_request",
        entity_id=request_id,
        request_id=request_id,
        details=(
            f"Git context {'updated' if audit_action == 'git_context_updated' else 'linked'}: "
            f"repo={payload.repository_url or '-'}, "
            f"branch={payload.branch_name or '-'}, "
            f"commit={payload.commit_hash or '-'}"
        ),
    )
    db.commit()

    return git_ctx
