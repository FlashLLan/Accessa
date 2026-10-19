from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from backend.core.limiter import limiter
from database.db import get_db
from backend.models.user import User
from backend.models.role import Role
from backend.schemas.auth import LoginRequest, RoomSignupRequest, TokenResponse
from backend.core.security import verify_password, hash_password, create_access_token
from backend.services.audit_service import log_action
from backend.services.room_service import create_room

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
def login(request: Request, data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=401, detail="Account is inactive")

    if not verify_password(data.password, user.hashed_password):
        log_action(
            db=db,
            user_id=user.id,
            action="LOGIN_FAILED",
            entity_type="user",
            entity_id=user.id,
            severity="medium",
            details=f"Failed login attempt for '{user.email}'",
        )
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user.last_login_at = datetime.utcnow()

    token = create_access_token(data={"sub": str(user.id), "room": user.room.public_id})

    log_action(
        db=db,
        user_id=user.id,
        action="LOGIN_SUCCESS",
        entity_type="user",
        entity_id=user.id,
        severity="low",
        details=f"User '{user.email}' logged in",
    )
    db.commit()

    return {"access_token": token, "token_type": "bearer"}


@router.post("/signup", response_model=TokenResponse)
@limiter.limit("5/minute")
def signup_room(request: Request, data: RoomSignupRequest, db: Session = Depends(get_db)):
    """Register a new room. The person signing up becomes its first sysadmin.

    Everyone else joins a room only when one of its sysadmins creates their account.
    """
    room_name = data.room_name.strip()
    full_name = data.full_name.strip()

    if len(room_name) < 2:
        raise HTTPException(status_code=400, detail="Room name must be at least 2 characters.")
    if not full_name:
        raise HTTPException(status_code=400, detail="Full name cannot be empty.")
    if len(data.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    admin_role = db.query(Role).filter(Role.name == "admin").first()
    if not admin_role:
        raise HTTPException(status_code=500, detail="Default role not configured")

    room = create_room(db, room_name)

    sysadmin = User(
        full_name=full_name,
        email=data.email,
        hashed_password=hash_password(data.password),
        role_id=admin_role.id,
        room_id=room.id,
        is_active=True,
        last_login_at=datetime.utcnow(),
    )
    db.add(sysadmin)
    db.flush()

    log_action(
        db=db,
        user_id=sysadmin.id,
        room_id=room.id,
        action="ROOM_CREATED",
        entity_type="room",
        entity_id=room.id,
        severity="high",
        details=f"Room '{room.name}' ({room.public_id}) created by '{sysadmin.email}'",
    )
    log_action(
        db=db,
        user_id=sysadmin.id,
        room_id=room.id,
        action="USER_CREATED",
        entity_type="user",
        entity_id=sysadmin.id,
        severity="medium",
        details=f"Sysadmin '{sysadmin.email}' created with the room",
    )
    db.commit()

    token = create_access_token(data={"sub": str(sysadmin.id), "room": room.public_id})
    return {"access_token": token, "token_type": "bearer"}
