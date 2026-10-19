from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from sqlalchemy.orm import Session

from database.db import get_db
from backend.models.user import User
from backend.models.change_request import ChangeRequest
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
        token_workspace = payload.get("workspace")

        if user_id is None or token_workspace is None:
            raise HTTPException(status_code=401, detail="Invalid token")

    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(User).filter(User.id == int(user_id)).first()

    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # The token is bound to the workspace it was issued for.
    if user.workspace is None or str(user.workspace.public_id) != token_workspace:
        raise HTTPException(status_code=401, detail="Invalid token")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Inactive user")

    return user


# --- Tenant scoping ------------------------------------------------------
# Every query for tenant-owned data must start from one of these helpers.
# The workspace always comes from the authenticated user, never from client input.
# Rows that belong to another workspace are simply invisible (callers return 404,
# not 403), so their existence is never revealed.

def workspace_users(db: Session, current_user: User):
    return db.query(User).filter(User.workspace_id == current_user.workspace_id)


def workspace_requests(db: Session, current_user: User):
    return db.query(ChangeRequest).filter(ChangeRequest.workspace_id == current_user.workspace_id)


def get_workspace_request_or_404(db: Session, request_id: int, current_user: User) -> ChangeRequest:
    cr = workspace_requests(db, current_user).filter(ChangeRequest.id == request_id).first()
    if not cr:
        raise HTTPException(status_code=404, detail="Change request not found")
    return cr


# Only the system administrator may create user accounts. Non-admin roles have no creation rights.
USER_CREATION_RULES = {
    "admin": ["junior", "mid", "senior", "lead", "admin"],
    "lead": [],
    "senior": [],
    "mid": [],
    "junior": [],
}


def can_create_role(creator_role: str, target_role: str) -> bool:
    return target_role in USER_CREATION_RULES.get(creator_role, [])