from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.db import get_db
from backend.models.audit_log import AuditLog
from backend.models.user import User
from backend.core.dependencies import get_current_user
from backend.schemas.audit_log import AuditLogResponse
from backend.services.audit_service import log_action

router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])


@router.get("/", response_model=list[AuditLogResponse])
def list_audit_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role.name != "admin":
        raise HTTPException(status_code=403, detail="Only admin can view audit logs")

    logs = db.query(AuditLog).order_by(AuditLog.created_at.desc()).all()

    log_action(
        db=db,
        user_id=current_user.id,
        action="AUDIT_VIEWED",
        entity_type="audit_log",
        entity_id=current_user.id,
        severity="low",
        details=f"Admin viewed audit log ({len(logs)} entries)",
    )
    db.commit()

    return logs