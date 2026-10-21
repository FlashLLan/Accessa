from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from database.base import Base
from backend.core.timeutils import utc_now
from backend.models.enums import AIReviewScope


class AIReviewResult(Base):
    __tablename__ = "ai_review_results"

    id = Column(Integer, primary_key=True, index=True)
    change_request_id = Column(Integer, ForeignKey("change_requests.id"), nullable=False)
    summary = Column(Text, nullable=True)
    suggested_risk_level = Column(Text, nullable=True)
    recommended_reviewer_role = Column(Text, nullable=True)
    impact_area = Column(Text, nullable=True)
    red_flags = Column(Text, nullable=True)             # JSON array string
    verification_checklist = Column(Text, nullable=True)  # JSON array string
    improvement_suggestions = Column(Text, nullable=True) # JSON array string
    model_name = Column(Text, nullable=True)
    prompt_version = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    # What the review was based on. NULL / defaults for results stored before
    # the real AI review existed.
    reviewed_commit = Column(String(40), nullable=True)   # PR head SHA the files were read at
    review_scope = Column(
        Enum(AIReviewScope, name="ai_review_scope", native_enum=False, create_constraint=True, length=13),
        nullable=True,
    )
    files_reviewed = Column(JSONB, nullable=True)        # [{"path", "source": changed|related|config}]
    files_skipped = Column(JSONB, nullable=True)         # [{"path", "reason"}]
    changed_files_total = Column(Integer, nullable=True)  # PR's changed files according to GitHub
    input_truncated = Column(Boolean, nullable=False, default=False, server_default="false")
    secrets_masked = Column(Integer, nullable=False, default=0, server_default="0")
    # Role of the reviewer who generated it, at that moment (never a name or e-mail).
    generated_by_role = Column(String, nullable=True)

    change_request = relationship("ChangeRequest", back_populates="ai_review_results")
