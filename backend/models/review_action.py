from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, Text
from sqlalchemy.orm import relationship

from database.db import Base
from backend.models.enums import ReviewActionType


class ReviewAction(Base):
    __tablename__ = "review_actions"

    id = Column(Integer, primary_key=True, index=True)
    change_request_id = Column(Integer, ForeignKey("change_requests.id"), nullable=False)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    action_type = Column(Enum(ReviewActionType), nullable=False)
    target_reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    from_status = Column(Text, nullable=True)
    to_status = Column(Text, nullable=True)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    change_request = relationship("ChangeRequest", back_populates="review_actions")
    actor = relationship("User", back_populates="review_actions_as_actor", foreign_keys=[actor_id])
    target_reviewer = relationship("User", back_populates="review_actions_as_target", foreign_keys=[target_reviewer_id])
