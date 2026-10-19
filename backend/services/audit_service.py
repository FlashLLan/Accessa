from sqlalchemy.orm import Session

from backend.models.audit_log import AuditLog
from backend.models.user import User


def log_action(
    db: Session,
    user_id: int,
    action: str,
    entity_type: str,
    entity_id: int,
    details: str | None = None,
    request_id: int | None = None,
    severity: str | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    room_id: int | None = None,
):
    # Every audit entry belongs to the actor's room so one room can never read another's trail.
    if room_id is None:
        room_id = db.get(User, user_id).room_id

    log_entry = AuditLog(
        user_id=user_id,
        room_id=room_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
        request_id=request_id,
        severity=severity,
        old_value=old_value,
        new_value=new_value,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(log_entry)
