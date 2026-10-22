from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, false, func, true
from sqlalchemy.orm import relationship

from database.base import Base
from backend.core.timeutils import utc_now


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # Email is unique per workspace, not globally: the same address may exist
        # in two workspaces as two unrelated accounts.
        UniqueConstraint("workspace_id", "email"),
        # Target for the composite foreign keys on change_requests, which make it
        # impossible at the database level to reference a user from another workspace.
        UniqueConstraint("workspace_id", "id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False)
    full_name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    must_change_password = Column(Boolean, nullable=False, default=False, server_default=false())
    mfa_enabled = Column(Boolean, nullable=False, default=False, server_default=false())
    # TOTP secret, Fernet-encrypted with MFA_ENCRYPTION_KEY. Set by /auth/mfa/setup;
    # mfa_enabled becomes true only after /auth/mfa/confirm.
    mfa_secret_encrypted = Column(String, nullable=True)
    # Last accepted TOTP time step: a code for this step or an earlier one is rejected (no reuse).
    mfa_last_used_step = Column(BigInteger, nullable=True)
    # The one valid mfa_pending token (its jti); clearing it invalidates that token
    # (after 5 wrong codes with it, a newer login, or an MFA reset).
    mfa_pending_jti = Column(String(64), nullable=True)
    # Consecutive wrong codes for the account, across logins. Reset only by a
    # successful verify or an admin MFA reset. At 10 the account is locked.
    mfa_failed_attempts = Column(Integer, nullable=False, default=0, server_default="0")
    # Until then MFA verification is refused (same generic error, even for a right code).
    mfa_locked_until = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default=true())
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now, server_default=func.now())
    deactivated_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)

    role = relationship("Role", back_populates="users")
    workspace = relationship("Workspace", back_populates="users")

    created_requests = relationship(
        "ChangeRequest",
        back_populates="creator",
        primaryjoin="User.id == ChangeRequest.created_by",
        foreign_keys="ChangeRequest.created_by",
    )

    assigned_reviews = relationship(
        "ChangeRequest",
        back_populates="assigned_reviewer",
        primaryjoin="User.id == ChangeRequest.assigned_reviewer_id",
        foreign_keys="ChangeRequest.assigned_reviewer_id",
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
