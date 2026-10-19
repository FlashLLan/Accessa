"""Seed the five global roles. Run after `alembic upgrade head`:  python -m backend.core.seed_roles"""
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy.orm import Session  # noqa: E402

from database.db import SessionLocal  # noqa: E402
import backend.models  # noqa: E402,F401
from backend.models.role import Role  # noqa: E402


def seed_roles():
    db: Session = SessionLocal()

    roles = [
        {"name": "junior", "level": 1},
        {"name": "mid", "level": 2},
        {"name": "senior", "level": 3},
        {"name": "lead", "level": 4},
        {"name": "admin", "level": 5},
    ]

    for role_data in roles:
        existing = db.query(Role).filter(Role.name == role_data["name"]).first()
        if not existing:
            role = Role(**role_data)
            db.add(role)

    db.commit()
    db.close()


if __name__ == "__main__":
    seed_roles()
