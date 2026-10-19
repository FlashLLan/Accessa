from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from sqlalchemy.orm import Session

from database.db import get_db
from backend.models.user import User
from backend.models.change_request import ChangeRequest
from backend.models.workspace import Workspace
from backend.core.security import SECRET_KEY, ALGORITHM

security = HTTPBearer()

# Error code returned (403) while the account still has an initial password set by
# an admin. The frontend detects it and redirects to the change-password page.
PASSWORD_CHANGE_REQUIRED = "password_change_required"

# The only routes reachable before that change: read my profile, change my password.
_ALLOWED_BEFORE_PASSWORD_CHANGE = {
    ("GET", "/users/me"),
    ("PUT", "/users/me/password"),
}


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    invalid_token = HTTPException(status_code=401, detail="Invalid token")
    token = credentials.credentials

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
        token_workspace = UUID(payload["workspace"])
    except (JWTError, KeyError, TypeError, ValueError, AttributeError):
        raise invalid_token

    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # The token is bound to the workspace it was issued for (by public UUID).
    workspace = db.query(Workspace).filter(Workspace.public_id == token_workspace).first()
    if workspace is None or workspace.id != user.workspace_id:
        raise invalid_token

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Inactive user")

    # Role and flags are read from the database on every request, so changes made
    # by an admin take effect immediately, not when the token expires.
    if user.must_change_password:
        route = request.scope.get("route")
        if (request.method, getattr(route, "path", None)) not in _ALLOWED_BEFORE_PASSWORD_CHANGE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": PASSWORD_CHANGE_REQUIRED,
                    "message": "You must change your password before continuing.",
                },
            )

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