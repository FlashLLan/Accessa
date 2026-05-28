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
    current_reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    submitted_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)

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

    current_reviewer = relationship(
        "User",
        back_populates="current_reviews",
        foreign_keys=[current_reviewer_id]
    )

    comments = relationship("Comment", back_populates="change_request", cascade="all, delete-orphan")
    approvals = relationship("Approval", back_populates="change_request", cascade="all, delete-orphan")
    git_context = relationship("GitContext", back_populates="change_request", uselist=False, cascade="all, delete-orphan")
    ai_review_results = relationship("AIReviewResult", back_populates="change_request", cascade="all, delete-orphan")
    review_actions = relationship("ReviewAction", back_populates="change_request", cascade="all, delete-orphan")