from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, Text
from sqlalchemy.orm import relationship

from database.db import Base
from backend.models.enums import ApprovalDecision


class Approval(Base):
    __tablename__ = "approvals"

    id = Column(Integer, primary_key=True, index=True)
    change_request_id = Column(Integer, ForeignKey("change_requests.id"), nullable=False)
    reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    decision = Column(Enum(ApprovalDecision), nullable=False)
    decision_comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    change_request = relationship("ChangeRequest", back_populates="approvals")
    reviewer = relationship("User", back_populates="approvals")