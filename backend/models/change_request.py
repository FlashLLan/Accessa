from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from database.db import Base
from backend.models.enums import (
    EnvironmentType,
    RequestStatus,
    RequestType,
    RiskLevel,
)


class ChangeRequest(Base):
    __tablename__ = "change_requests"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    request_type = Column(Enum(RequestType), nullable=False)
    target_system = Column(String, nullable=False)
    environment = Column(Enum(EnvironmentType), nullable=False)
    risk_level = Column(Enum(RiskLevel), nullable=False)
    status = Column(Enum(RequestStatus), default=RequestStatus.DRAFT, nullable=False)

    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    assigned_reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    creator = relationship(
        "User",
        back_populates="created_requests",
        foreign_keys=[created_by]
    )

    assigned_reviewer = relationship(
        "User",
        back_populates="assigned_reviews",
        foreign_keys=[assigned_reviewer_id]
    )

    comments = relationship("Comment", back_populates="change_request", cascade="all, delete-orphan")
    approvals = relationship("Approval", back_populates="change_request", cascade="all, delete-orphan")