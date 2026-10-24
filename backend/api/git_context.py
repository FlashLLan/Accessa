from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.db import get_db
from backend.models.change_request import ChangeRequest
from backend.models.enums import RequestStatus
from backend.models.git_context import GitContext
from backend.core.dependencies import get_current_user, get_current_workspace_id, get_request_or_404, ClientInfo, get_client_info
from backend.models.user import User
from backend.schemas.git_context import GitContextCreate, GitContextResponse
from backend.services.audit_service import log_action

router = APIRouter(prefix="/change-requests", tags=["Git Context"])

# Technical identifiers that are recorded in the audit log. diff_text,
# changed_files_summary and the free-form names are never logged.
GIT_IDENTIFIER_FIELDS = ("repository_url", "branch_name", "target_branch", "commit_hash", "pull_request_url")

NOT_A_DRAFT = "Git context can only be changed while the request is a draft"


def format_identifiers(values: dict, fields=GIT_IDENTIFIER_FIELDS) -> str:
    """'repository_url=https://...; branch_name=feature/x' for the given fields ('-' if empty)."""
    return "; ".join(f"{field}={values.get(field) or '-'}" for field in fields)


def _check_access(cr: ChangeRequest, current_user: User):
    if current_user.role.name == "admin":
        return
    authorized = cr.created_by == current_user.id or cr.assigned_reviewer_id == current_user.id
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
    client: ClientInfo = Depends(get_client_info),
):
    """Same rule as editing the request: only its creator, only while it is a draft.
    After submission the Git context is read-only for everyone."""
    # Row lock: a concurrent submit cannot slip between this check and the change.
    cr = get_request_or_404(db, workspace_id, request_id, for_update=True)
    _check_access(cr, current_user)
    if cr.status != RequestStatus.DRAFT:
        raise HTTPException(status_code=400, detail=NOT_A_DRAFT)
    if cr.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Only the creator can change the Git context")

    changes = payload.model_dump(exclude_unset=True)
    old_value = new_value = None
    if cr.git_context:
        git_ctx = cr.git_context
        before = {field: getattr(git_ctx, field) for field in GIT_IDENTIFIER_FIELDS}
        for field, value in changes.items():
            setattr(git_ctx, field, value)
        changed = [f for f in GIT_IDENTIFIER_FIELDS if getattr(git_ctx, f) != before[f]]
        other = [f for f in ("diff_text", "changed_files_summary") if f in changes]
        audit_action = "GIT_CONTEXT_UPDATED"
        if changed:
            old_value = format_identifiers(before, changed)
            new_value = format_identifiers({f: getattr(git_ctx, f) for f in changed}, changed)
        details = (
            f"Git context updated: identifiers changed={','.join(changed) or 'none'}"
            # Only that the diff/summary was sent, never its content.
            + (f"; also sent: {','.join(other)}" if other else "")
        )
    else:
        git_ctx = GitContext(change_request_id=request_id, **payload.model_dump())
        db.add(git_ctx)
        audit_action = "GIT_CONTEXT_LINKED"
        details = f"Git context linked: {format_identifiers(payload.model_dump())}"

    log_action(
        db=db,
        ip_address=client.ip_address,
        user_agent=client.user_agent,
        user_id=current_user.id,
        action=audit_action,
        entity_type="change_request",
        entity_id=request_id,
        request_id=request_id,
        old_value=old_value,
        new_value=new_value,
        details=details,
    )
    # Git context and its audit entry are committed together.
    db.commit()
    db.refresh(git_ctx)

    return git_ctx
