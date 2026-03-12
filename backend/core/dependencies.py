from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from sqlalchemy.orm import Session

from database.db import get_db
from backend.models.user import User
from backend.core.security import SECRET_KEY, ALGORITHM

security = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    token = credentials.credentials

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")

        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")

    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(User).filter(User.id == int(user_id)).first()

    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user


USER_CREATION_RULES = {
    "admin": ["junior", "mid", "senior", "lead", "admin"],
    "lead": ["junior", "mid", "senior"],
    "senior": ["junior"],
    "mid": [],
    "junior": [],
}


def can_create_role(creator_role: str, target_role: str) -> bool:
    return target_role in USER_CREATION_RULES.get(creator_role, [])