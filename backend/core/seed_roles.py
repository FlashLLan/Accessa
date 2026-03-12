from sqlalchemy.orm import Session

from database.db import SessionLocal
from backend.models.role import Role


def seed_roles():
    db: Session = SessionLocal()

    roles = [
        {"name": "junior", "level": 1},
        {"name": "mid", "level": 2},
        {"name": "senior", "level": 3},
        {"name": "team_lead", "level": 4},
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