from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.db import get_db
from backend.models.user import User
from backend.models.role import Role
from backend.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from backend.core.security import verify_password, hash_password, create_access_token
from backend.services.audit_service import log_action

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(data.password, user.hashed_password):
        log_action(
            db=db,
            user_id=user.id,
            action="failed_login",
            entity_type="user",
            entity_id=user.id,
            severity="warning",
            details=f"Failed login attempt for '{user.email}'",
        )
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user.last_login_at = datetime.utcnow()

    token = create_access_token(data={"sub": str(user.id)})

    log_action(
        db=db,
        user_id=user.id,
        action="login",
        entity_type="user",
        entity_id=user.id,
        details=f"User '{user.email}' logged in",
    )
    db.commit()

    return {"access_token": token, "token_type": "bearer"}


@router.post("/register", response_model=TokenResponse)
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    junior_role = db.query(Role).filter(Role.name == "junior").first()
    if not junior_role:
        raise HTTPException(status_code=500, detail="Default role not configured")

    new_user = User(
        full_name=data.full_name,
        email=data.email,
        hashed_password=hash_password(data.password),
        role_id=junior_role.id,
        is_active=True,
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    log_action(
        db=db,
        user_id=new_user.id,
        action="register",
        entity_type="user",
        entity_id=new_user.id,
        details=f"User '{new_user.email}' self-registered",
    )
    db.commit()

    token = create_access_token(data={"sub": str(new_user.id)})
    return {"access_token": token, "token_type": "bearer"}
