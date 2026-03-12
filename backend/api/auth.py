from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.db import get_db
from backend.models.user import User
from backend.schemas.auth import LoginRequest, TokenResponse
from backend.core.security import verify_password, create_access_token
from backend.services.audit_service import log_action
router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):

    user = db.query(User).filter(User.email == data.email).first()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(
        data={"sub": str(user.id)}
    )

    log_action(
        db=db,
        user_id=user.id,
        action="login",
        entity_type="user",
        entity_id=user.id,
        details=f"User '{user.email}' logged in"
    )
    db.commit()

    return {
        "access_token": token,
        "token_type": "bearer"
    }