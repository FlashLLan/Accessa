from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from datetime import datetime

from database.base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False, index=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deactivated_at = Column(DateTime, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    last_login_at = Column(DateTime, nullable=True)

    role = relationship("Role", back_populates="users")
    room = relationship("Room", back_populates="users")

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

    current_reviews = relationship(
        "ChangeRequest",
        back_populates="current_reviewer",
        foreign_keys="ChangeRequest.current_reviewer_id"
    )

    comments = relationship("Comment", back_populates="user")
    approvals = relationship("Approval", back_populates="reviewer")
    audit_logs = relationship("AuditLog", back_populates="user")
    review_actions_as_actor = relationship(
        "ReviewAction",
        back_populates="actor",
        foreign_keys="ReviewAction.actor_id"
    )
    review_actions_as_target = relationship(
        "ReviewAction",
        back_populates="target_reviewer",
        foreign_keys="ReviewAction.target_reviewer_id"
    )