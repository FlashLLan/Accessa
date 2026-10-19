import secrets
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import relationship

from database.db import Base

ROOM_PUBLIC_ID_LENGTH = 12


def generate_room_public_id() -> str:
    """12 random digits from a CSPRNG, never starting with 0 (AWS-account-ID style)."""
    low = 10 ** (ROOM_PUBLIC_ID_LENGTH - 1)
    return str(low + secrets.randbelow(9 * low))


class Room(Base):
    """A tenant. Every tenant-owned row (users, change requests, audit logs) carries room_id.

    `id` is the internal key used for joins and is never exposed by the API.
    `public_id` is the random identifier shown to users.
    """

    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True, index=True)
    public_id = Column(String(ROOM_PUBLIC_ID_LENGTH), unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    users = relationship("User", back_populates="room")
