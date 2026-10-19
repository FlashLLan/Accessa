from sqlalchemy.orm import Session

from database.db import SessionLocal, engine, Base
import backend.models
from backend.models.role import Role
from backend.models.user import User
from backend.core.security import hash_password
from backend.services.room_service import create_room


def seed_admin():
    Base.metadata.create_all(bind=engine)

    db: Session = SessionLocal()

    admin_role = db.query(Role).filter(Role.name == "admin").first()
    if not admin_role:
        print("Admin role not found. Run seed_roles first.")
        db.close()
        return

    existing_user = db.query(User).filter(User.email == "admin@test.com").first()
    if not existing_user:
        room = create_room(db, "Demo Room")
        admin_user = User(
            full_name="Admin User",
            email="admin@test.com",
            hashed_password=hash_password("123456"),
            role_id=admin_role.id,
            room_id=room.id,
            is_active=True
        )
        db.add(admin_user)
        db.commit()
        print(f"Admin user created in room '{room.name}' (ID {room.public_id}).")
    else:
        print("Admin user already exists.")

    db.close()


if __name__ == "__main__":
    seed_admin()