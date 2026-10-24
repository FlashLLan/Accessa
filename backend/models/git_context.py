from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, Text
from sqlalchemy.orm import relationship

from database.base import Base
from backend.core.timeutils import utc_now
from backend.models.enums import GitContextSource


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
    # Pull request (GitHub) or merge request (GitLab) URL; one field for both.
    pull_request_url = Column(Text, nullable=True)
    changed_files_summary = Column(Text, nullable=True)
    diff_text = Column(Text, nullable=True)
    # Where commit_hash, changed_files_summary and diff_text come from, and when
    # they were fetched (GITHUB: at submission, from the pull request).
    source = Column(
        Enum(GitContextSource, name="git_context_source", native_enum=False, create_constraint=True, length=6),
        nullable=False,
        default=GitContextSource.MANUAL,
        server_default=GitContextSource.MANUAL.name,
    )
    fetched_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    change_request = relationship("ChangeRequest", back_populates="git_context")
