from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import relationship

from database.base import Base


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
    created_at = Column(DateTime, default=datetime.utcnow)

    change_request = relationship("ChangeRequest", back_populates="ai_review_results")
