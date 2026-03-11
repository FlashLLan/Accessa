from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from datetime import datetime

from database.db import Base

#A quick note: Comment, Approval, and AuditLog don’t exist yet, but
#SQLAlchemy can handle string references as long as those models are imported before table creation.

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    role = relationship("Role", back_populates="users")

    created_requests = relationship(
        "ChangeRequest",
        back_populates="creator",
        foreign_keys="ChangeRequest.created_by"
    )

    assigned_reviews = relationship(
        "ChangeRequest",
        back_populates="assigned_reviewer",
        foreign_keys="ChangeRequest.assigned_reviewer_id"
    )

    comments = relationship("Comment", back_populates="user")
    approvals = relationship("Approval", back_populates="reviewer")
    audit_logs = relationship("AuditLog", back_populates="user")