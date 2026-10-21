from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.db import get_db
from backend.models.user import User
from backend.models.workspace import Workspace
from backend.core.dependencies import get_current_user, get_current_workspace_id, ClientInfo, get_client_info
from backend.schemas.workspace import WorkspaceSettingsResponse, WorkspaceSettingsUpdate
from backend.services.audit_service import log_action

router = APIRouter(prefix="/workspace", tags=["Workspace"])


def _require_admin(current_user: User) -> None:
    if current_user.role.name != "admin":
        raise HTTPException(status_code=403, detail="Only admin can manage workspace settings")


@router.get("/settings", response_model=WorkspaceSettingsResponse)
def get_workspace_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    workspace_id: int = Depends(get_current_workspace_id),
):
    _require_admin(current_user)
    return db.get(Workspace, workspace_id)


@router.patch("/settings", response_model=WorkspaceSettingsResponse)
def update_workspace_settings(
    payload: WorkspaceSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    workspace_id: int = Depends(get_current_workspace_id),
    client: ClientInfo = Depends(get_client_info),
):
    _require_admin(current_user)
    workspace = db.get(Workspace, workspace_id)

    old, new = workspace.ai_review_scope, payload.ai_review_scope
    if old == new:
        return workspace  # nothing changed, nothing to audit

    workspace.ai_review_scope = new
    log_action(
        db=db,
        ip_address=client.ip_address,
        user_agent=client.user_agent,
        user_id=current_user.id,
        action="WORKSPACE_SETTING_CHANGED",
        entity_type="workspace",
        entity_id=None,  # never the internal workspace id
        severity="medium",
        old_value=old.value,
        new_value=new.value,
        details="Workspace setting changed: ai_review_scope",
    )
    # The setting and its audit entry are committed together.
    db.commit()
    return workspace
