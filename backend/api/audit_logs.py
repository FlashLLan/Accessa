from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from database.db import get_db
from backend.models.audit_log import AuditLog
from backend.models.change_request import ChangeRequest
from backend.models.user import User
from backend.models.workspace import Workspace
from backend.core.dependencies import get_current_user, get_current_workspace_id, scoped, ClientInfo, get_client_info
from backend.schemas.audit_log import AuditLogResponse
from backend.services.audit_service import log_action

router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])


def _entity_labels(db: Session, workspace_id: int, logs: list[AuditLog]) -> dict[tuple[str, int | None], str]:
    """Readable references for the entities in `logs`, resolved at read time and only
    within the current workspace. Names and e-mails are looked up here; the audit
    rows themselves never store them."""
    user_ids = {log.entity_id for log in logs if log.entity_type == "user" and log.entity_id is not None}
    request_ids = {log.entity_id for log in logs if log.entity_type == "change_request" and log.entity_id is not None}

    labels: dict[tuple[str, int | None], str] = {}
    if user_ids:
        for user in scoped(db, User, workspace_id).filter(User.id.in_(user_ids)):
            labels[("user", user.id)] = f"{user.full_name} ({user.email})"
    if request_ids:
        for cr in scoped(db, ChangeRequest, workspace_id).filter(ChangeRequest.id.in_(request_ids)):
            labels[("change_request", cr.id)] = cr.title
    return labels


def _entity_label(log: AuditLog, labels: dict, workspace: Workspace) -> str | None:
    if log.entity_type == "workspace":
        return workspace.slug
    if log.entity_type == "audit_log":
        return "Audit log"
    return labels.get((log.entity_type, log.entity_id))


@router.get("/", response_model=list[AuditLogResponse])
def list_audit_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    workspace_id: int = Depends(get_current_workspace_id),
    client: ClientInfo = Depends(get_client_info),
):
    if current_user.role.name != "admin":
        raise HTTPException(status_code=403, detail="Only admin can view audit logs")

    logs = (
        scoped(db, AuditLog, workspace_id)
        .options(joinedload(AuditLog.user).joinedload(User.role))
        .order_by(AuditLog.created_at.desc())
        .all()
    )

    workspace = db.get(Workspace, workspace_id)
    labels = _entity_labels(db, workspace_id, logs)
    response = [
        AuditLogResponse.model_validate(log).model_copy(
            update={"entity_label": _entity_label(log, labels, workspace)}
        )
        for log in logs
    ]

    log_action(
        db=db,
        ip_address=client.ip_address,
        user_agent=client.user_agent,
        user_id=current_user.id,
        action="AUDIT_VIEWED",
        entity_type="audit_log",
        entity_id=None,  # the audit log as a whole; there is no single row to link to
        severity="low",
        details=f"Admin viewed audit log ({len(logs)} entries)",
    )
    db.commit()

    return response
