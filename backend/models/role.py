from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship

from database.db import Base


class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    level = Column(Integer, nullable=False)

    users = relationship("User", back_populates="role")

