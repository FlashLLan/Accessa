import uuid

from sqlalchemy import Column, DateTime, Integer, String, Uuid, func
from sqlalchemy.orm import relationship

from database.base import Base
from backend.core.timeutils import utc_now

SLUG_MIN_LENGTH = 3
SLUG_MAX_LENGTH = 32


class Workspace(Base):
    """One organisation's isolated tenant.

    `id` is the internal key used for joins and foreign keys; it is never exposed.
    `public_id` is a random UUIDv4 for anything shown outside the system.
    `slug` is the human-readable login address: /w/<slug>.
    """

    __tablename__ = "workspaces"

    id = Column(Integer, primary_key=True, index=True)
    public_id = Column(Uuid, unique=True, nullable=False, default=uuid.uuid4)
    slug = Column(String(SLUG_MAX_LENGTH), unique=True, nullable=False)
    name = Column(String(120), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now())

    users = relationship("User", back_populates="workspace")
