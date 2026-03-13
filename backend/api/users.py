from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.db import get_db
from backend.models.user import User
from backend.models.role import Role
from backend.core.dependencies import get_current_user, can_create_role
from backend.core.security import hash_password
from backend.schemas.user import UserCreate, UserResponse, UserShortResponse
from backend.services.audit_service import log_action

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/", response_model=list[UserResponse])
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role.name != "admin":
        raise HTTPException(status_code=403, detail="Only admin can view all users")

    return db.query(User).all()


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/reviewers", response_model=list[UserShortResponse])
def list_reviewers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    reviewers = (
        db.query(User)
        .join(Role)
        .filter(
            User.is_active == True,
            Role.name.in_(["admin", "reviewer"])
        )
        .all()
    )

    return reviewers


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if current_user.role.name != "admin" and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    return user


@router.post("/", response_model=UserResponse)
def create_user(
    user_data: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    role = db.query(Role).filter(Role.id == user_data.role_id).first()
    if not role:
        raise HTTPException(status_code=400, detail="Invalid role_id")

    creator_role_name = current_user.role.name
    target_role_name = role.name

    if not can_create_role(creator_role_name, target_role_name):
        raise HTTPException(
            status_code=403,
            detail=f"Role '{creator_role_name}' cannot create role '{target_role_name}'"
        )

    new_user = User(
        full_name=user_data.full_name,
        email=user_data.email,
        hashed_password=hash_password(user_data.password),
        role_id=user_data.role_id,
        is_active=True
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    log_action(
        db=db,
        user_id=current_user.id,
        action="create_user",
        entity_type="user",
        entity_id=new_user.id,
        details=f"Created user '{new_user.email}' with role_id={new_user.role_id}"
    )
    db.commit()

    return new_user

@router.patch("/{user_id}/deactivate", response_model=UserResponse)
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role.name != "admin":
        raise HTTPException(status_code=403, detail="Only admin can deactivate users")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")

    if not user.is_active:
        raise HTTPException(status_code=400, detail="User is already inactive")

    user.is_active = False
    db.commit()
    db.refresh(user)

    log_action(
        db=db,
        user_id=current_user.id,
        action="deactivate_user",
        entity_type="user",
        entity_id=user.id,
        details=f"Deactivated user '{user.email}'"
    )
    db.commit()

    return user


@router.patch("/{user_id}/reactivate", response_model=UserResponse)
def reactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role.name != "admin":
        raise HTTPException(status_code=403, detail="Only admin can reactivate users")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.is_active:
        raise HTTPException(status_code=400, detail="User is already active")

    user.is_active = True
    db.commit()
    db.refresh(user)

    log_action(
        db=db,
        user_id=current_user.id,
        action="reactivate_user",
        entity_type="user",
        entity_id=user.id,
        details=f"Reactivated user '{user.email}'"
    )
    db.commit()

    return user