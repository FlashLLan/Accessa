from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import relationship

from database.base import Base
from backend.core.timeutils import utc_now


class GitContext(Base):
    __tablename__ = "git_context"

    id = Column(Integer, primary_key=True, index=True)
    change_request_id = Column(Integer, ForeignKey("change_requests.id"), nullable=False, unique=True)
    provider = Column(Text, nullable=True)
    repository_url = Column(Text, nullable=True)
    repository_name = Column(Text, nullable=True)
    branch_name = Column(Text, nullable=True)
    target_branch = Column(Text, nullable=True)
    commit_hash = Column(Text, nullable=True)
    pull_request_url = Column(Text, nullable=True)
    merge_request_url = Column(Text, nullable=True)
    changed_files_summary = Column(Text, nullable=True)
    diff_text = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    change_request = relationship("ChangeRequest", back_populates="git_context")
