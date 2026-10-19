from sqlalchemy import Column, DateTime, Enum, ForeignKey, ForeignKeyConstraint, Integer, String, Text
from sqlalchemy.orm import relationship

from database.base import Base
from backend.core.timeutils import utc_now
from backend.models.enums import (
    EnvironmentType,
    RequestStatus,
    RequestType,
    RiskLevel,
)


class ChangeRequest(Base):
    __tablename__ = "change_requests"
    __table_args__ = (
        # Composite foreign keys: every user a request points at must belong to the
        # request's own workspace. Enforced by the database, independently of the
        # application code. current_reviewer_id is nullable; with the default
        # MATCH SIMPLE semantics a NULL there skips the check.
        ForeignKeyConstraint(["workspace_id", "created_by"], ["users.workspace_id", "users.id"]),
        ForeignKeyConstraint(["workspace_id", "assigned_reviewer_id"], ["users.workspace_id", "users.id"]),
        ForeignKeyConstraint(["workspace_id", "current_reviewer_id"], ["users.workspace_id", "users.id"]),
    )

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    request_type = Column(Enum(RequestType, name="request_type", native_enum=False, create_constraint=True), nullable=False)
    target_system = Column(String, nullable=False)
    environment = Column(Enum(EnvironmentType, name="environment", native_enum=False, create_constraint=True), nullable=False)
    risk_level = Column(Enum(RiskLevel, name="risk_level", native_enum=False, create_constraint=True), nullable=False)
    status = Column(
        Enum(RequestStatus, name="request_status", native_enum=False, create_constraint=True),
        default=RequestStatus.DRAFT,
        nullable=False,
    )

    created_by = Column(Integer, nullable=False)
    assigned_reviewer_id = Column(Integer, nullable=False)
    current_reviewer_id = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)

    creator = relationship(
        "User",
        back_populates="created_requests",
        primaryjoin="User.id == ChangeRequest.created_by",
        foreign_keys=[created_by],
    )

    assigned_reviewer = relationship(
        "User",
        back_populates="assigned_reviews",
        primaryjoin="User.id == ChangeRequest.assigned_reviewer_id",
        foreign_keys=[assigned_reviewer_id],
    )

    current_reviewer = relationship(
        "User",
        back_populates="current_reviews",
        primaryjoin="User.id == ChangeRequest.current_reviewer_id",
        foreign_keys=[current_reviewer_id],
    )

    comments = relationship("Comment", back_populates="change_request", cascade="all, delete-orphan")
    approvals = relationship("Approval", back_populates="change_request", cascade="all, delete-orphan")
    git_context = relationship("GitContext", back_populates="change_request", uselist=False, cascade="all, delete-orphan")
    ai_review_results = relationship("AIReviewResult", back_populates="change_request", cascade="all, delete-orphan")
    review_actions = relationship("ReviewAction", back_populates="change_request", cascade="all, delete-orphan")
