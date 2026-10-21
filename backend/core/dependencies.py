from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from sqlalchemy.orm import Session

from database.db import get_db
from backend.models.user import User
from backend.models.change_request import ChangeRequest
from backend.models.audit_log import AuditLog
from backend.models.workspace import Workspace
from backend.core.security import SECRET_KEY, ALGORITHM

security = HTTPBearer()

USER_AGENT_MAX_LENGTH = 512


@dataclass(frozen=True)
class ClientInfo:
    """Who sent the request, as recorded on every audit entry."""
    ip_address: str | None
    user_agent: str | None


def get_client_info(request: Request) -> ClientInfo:
    # request.client.host is the TCP peer address. Behind a reverse proxy or load
    # balancer that is the proxy, not the user: the real client IP must then come
    # from the header set by the *trusted* proxy (e.g. X-Forwarded-For / X-Real-IP,
    # via uvicorn --proxy-headers --forwarded-allow-ips=<proxy ip>). Never take it
    # from a header the client can set directly.
    user_agent = request.headers.get("user-agent")
    return ClientInfo(
        ip_address=request.client.host if request.client else None,
        user_agent=user_agent[:USER_AGENT_MAX_LENGTH] if user_agent else None,
    )

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


# --- Workspace scoping ---------------------------------------------------
# The single place where tenant isolation is applied to queries.
#
# - get_current_workspace_id is the dependency every endpoint uses to learn which
#   workspace it is confined to. It always comes from the authenticated user,
#   never from the request body, path or query string.
# - scoped() is the only way to query a workspace-owned table. Child tables
#   (approvals, comments, review_actions, git_context, ai_review_results) have no
#   workspace_id; they are reached only through a change request loaded with
#   get_request_or_404().
# - Rows from another workspace are invisible: lookups return 404, never 403, so
#   a user cannot even learn that they exist.

TENANT_MODELS = (User, ChangeRequest, AuditLog)


def get_current_workspace_id(current_user: User = Depends(get_current_user)) -> int:
    return current_user.workspace_id


def scoped(db: Session, model, workspace_id: int):
    if model not in TENANT_MODELS:
        raise TypeError(
            f"{model.__name__} has no workspace_id; load it through its change request instead"
        )
    return db.query(model).filter(model.workspace_id == workspace_id)


def get_request_or_404(db: Session, workspace_id: int, request_id: int) -> ChangeRequest:
    cr = scoped(db, ChangeRequest, workspace_id).filter(ChangeRequest.id == request_id).first()
    if not cr:
        raise HTTPException(status_code=404, detail="Change request not found")
    return cr


def get_user_or_404(
    db: Session,
    workspace_id: int,
    user_id: int,
    *,
    active_only: bool = False,
    detail: str = "User not found",
) -> User:
    query = scoped(db, User, workspace_id).filter(User.id == user_id)
    if active_only:
        query = query.filter(User.is_active == True)  # noqa: E712
    user = query.first()
    if not user:
        raise HTTPException(status_code=404, detail=detail)
    return user


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