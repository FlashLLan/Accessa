from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from database.base import Base
from backend.core.timeutils import utc_now


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    # Nullable so a failed login for an unknown email can still be recorded.
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # Role of the actor at the time of the action (not looked up later). NULL when
    # there is no known actor. Audit rows never store names or e-mail addresses.
    actor_role = Column(String, nullable=True)
    action = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)
    # NULL for workspace events: the workspace is identified by slug/public_id in
    # details, never by its internal id.
    entity_id = Column(Integer, nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    # Deliberately no foreign key: audit records must outlive what they reference.
    request_id = Column(Integer, nullable=True)
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    severity = Column(String, nullable=True)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)

    user = relationship("User", back_populates="audit_logs")