"""Seed the default workspace and its admin. Run after seed_roles:  python -m backend.core.seed_admin"""
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy.orm import Session  # noqa: E402

from database.db import SessionLocal  # noqa: E402
import backend.models  # noqa: E402,F401
from backend.models.role import Role  # noqa: E402
from backend.models.user import User  # noqa: E402
from backend.models.workspace import Workspace  # noqa: E402
from backend.core.security import hash_password  # noqa: E402
from backend.services.workspace_service import create_workspace  # noqa: E402

DEFAULT_WORKSPACE_NAME = "Default workspace"
DEFAULT_WORKSPACE_SLUG = "default"


def seed_admin():
    db: Session = SessionLocal()

    admin_role = db.query(Role).filter(Role.name == "admin").first()
    if not admin_role:
        print("Admin role not found. Run seed_roles first.")
        db.close()
        return

    workspace = db.query(Workspace).filter(Workspace.slug == DEFAULT_WORKSPACE_SLUG).first()
    if not workspace:
        workspace = create_workspace(db, DEFAULT_WORKSPACE_NAME, DEFAULT_WORKSPACE_SLUG)
        print(f"Workspace '{workspace.name}' created (slug '{workspace.slug}').")

    existing_user = (
        db.query(User)
        .filter(User.workspace_id == workspace.id, User.email == "admin@test.com")
        .first()
    )
    if not existing_user:
        admin_user = User(
            full_name="Admin User",
            email="admin@test.com",
            hashed_password=hash_password("123456"),
            role_id=admin_role.id,
            workspace_id=workspace.id,
            is_active=True
        )
        db.add(admin_user)
        print(f"Admin user created in workspace '{workspace.slug}'.")
    else:
        print("Admin user already exists.")

    db.commit()
    db.close()


if __name__ == "__main__":
    seed_admin()
