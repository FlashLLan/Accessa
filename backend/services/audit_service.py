from sqlalchemy.orm import Session

from backend.models.audit_log import AuditLog
from backend.models.user import User


def log_action(
    db: Session,
    user_id: int | None,
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
    workspace_id: int | None = None,
):
    """Add an audit entry to the session. Never commits: the caller commits the
    state change and its audit entry together in one db.commit(), so either both
    are stored or neither is."""
    # Every audit entry belongs to the actor's workspace so one workspace can never read another's trail.
    # user_id may be None (failed login for an unknown email); workspace_id must then be given.
    if workspace_id is None:
        if user_id is None:
            raise ValueError("log_action needs workspace_id when user_id is None")
        workspace_id = db.get(User, user_id).workspace_id

    log_entry = AuditLog(
        user_id=user_id,
        workspace_id=workspace_id,
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
