from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from backend.core.limiter import limiter
from backend.core.dependencies import ClientInfo, get_client_info
from database.db import get_db
from backend.models.user import User
from backend.models.role import Role
from backend.models.workspace import Workspace
from backend.schemas.auth import LoginRequest, WorkspaceSignupRequest, TokenResponse
import secrets

from backend.core.security import verify_password, hash_password, create_access_token, create_mfa_pending_token
from backend.services.audit_service import log_action
from backend.services.workspace_service import (
    create_workspace,
    get_workspace_by_slug,
    normalize_slug,
    slug_error,
)
from backend.core.timeutils import utc_now

router = APIRouter(prefix="/auth", tags=["Authentication"])

INVALID_CREDENTIALS = "Invalid credentials"

# Verified against when the account does not exist, so a login for an unknown
# email costs the same bcrypt work as a wrong password and response timing does
# not reveal which accounts exist.
_DUMMY_PASSWORD_HASH = hash_password("accessa-dummy-password-for-timing")


def _token_claims(user: User) -> dict:
    # The workspace is identified by its public UUID; internal integer ids stay out of tokens.
    return {"sub": str(user.id), "workspace": str(user.workspace.public_id)}


def issue_access_token(user: User) -> str:
    return create_access_token(data=_token_claims(user))


def issue_mfa_pending_token(user: User) -> str:
    """Password was correct and MFA is enabled: a 5-minute token for /auth/mfa/verify
    only. A new one replaces (revokes) any earlier one and resets the wrong-code count."""
    jti = secrets.token_urlsafe(24)
    user.mfa_pending_jti = jti
    user.mfa_failed_attempts = 0
    return create_mfa_pending_token(_token_claims(user), jti)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
def login(
    request: Request,
    data: LoginRequest,
    db: Session = Depends(get_db),
    client: ClientInfo = Depends(get_client_info),
):
    """Workspace-scoped login.

    Every failure (unknown workspace, unknown email, wrong password, inactive
    account) returns the same 401, so the endpoint cannot be used to discover
    which workspaces or accounts exist or are disabled.
    """
    invalid = HTTPException(status_code=401, detail=INVALID_CREDENTIALS)

    workspace = get_workspace_by_slug(db, data.workspace_slug)
    if not workspace:
        # No workspace to record the attempt in, so nothing is logged.
        verify_password(data.password, _DUMMY_PASSWORD_HASH)
        raise invalid

    user = (
        db.query(User)
        .filter(User.workspace_id == workspace.id, User.email == data.email)
        .first()
    )

    password_ok = verify_password(data.password, user.hashed_password if user else _DUMMY_PASSWORD_HASH)

    if not user or not password_ok or not user.is_active:
        if not user:
            reason = "unknown email"
        elif not password_ok:
            reason = "wrong password"
        else:
            reason = "inactive account"

        log_action(
            db=db,
            ip_address=client.ip_address,
            user_agent=client.user_agent,
            user_id=user.id if user else None,
            workspace_id=workspace.id,
            action="LOGIN_FAILED",
            entity_type="user" if user else "workspace",
            # Workspace events never carry the internal workspace id.
            entity_id=user.id if user else None,
            severity="medium",
            details=(
                f"Failed login ({reason})"
                if user
                else f"Failed login: unknown email (workspace '{workspace.slug}')"
            ),
        )
        db.commit()
        raise invalid

    if user.mfa_enabled:
        # Second factor still missing: no access token yet, and no LOGIN_SUCCESS
        # until /auth/mfa/verify accepts the code.
        mfa_token = issue_mfa_pending_token(user)
        db.commit()
        return {"access_token": None, "token_type": "bearer", "mfa_required": True, "mfa_token": mfa_token}

    user.last_login_at = utc_now()

    log_action(
        db=db,
        ip_address=client.ip_address,
        user_agent=client.user_agent,
        user_id=user.id,
        workspace_id=workspace.id,
        action="LOGIN_SUCCESS",
        entity_type="user",
        entity_id=user.id,
        severity="low",
        details="User logged in",
    )
    db.commit()

    return {
        "access_token": issue_access_token(user),
        "token_type": "bearer",
        "must_change_password": user.must_change_password,
    }


@router.post("/signup", response_model=TokenResponse)
@limiter.limit("5/minute")
def signup_workspace(
    request: Request,
    data: WorkspaceSignupRequest,
    db: Session = Depends(get_db),
    client: ClientInfo = Depends(get_client_info),
):
    """Register a new workspace. The person signing up becomes its first admin.

    This endpoint can only ever create a *new* workspace: it never adds a user to
    an existing one and never takes a role or workspace id from the client.
    Everyone else joins a workspace only when one of its admins creates their account.
    """
    workspace_name = data.workspace_name.strip()
    workspace_slug = normalize_slug(data.workspace_slug)
    full_name = data.full_name.strip()

    if not 2 <= len(workspace_name) <= 120:
        raise HTTPException(status_code=400, detail="Workspace name must be 2-120 characters.")
    problem = slug_error(workspace_slug)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    if not full_name:
        raise HTTPException(status_code=400, detail="Full name cannot be empty.")
    if len(data.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    taken = HTTPException(status_code=409, detail="This workspace address is already taken.")
    if db.query(Workspace.id).filter(Workspace.slug == workspace_slug).first():
        raise taken

    admin_role = db.query(Role).filter(Role.name == "admin").first()
    if not admin_role:
        raise HTTPException(status_code=500, detail="Default role not configured")

    # Workspace, admin and both audit entries are committed together or not at all.
    try:
        workspace = create_workspace(db, workspace_name, workspace_slug)

        admin_user = User(
            full_name=full_name,
            email=data.email,
            hashed_password=hash_password(data.password),
            role_id=admin_role.id,
            workspace_id=workspace.id,
            is_active=True,
            last_login_at=utc_now(),
        )
        db.add(admin_user)
        db.flush()

        log_action(
            db=db,
            ip_address=client.ip_address,
            user_agent=client.user_agent,
            user_id=admin_user.id,
            workspace_id=workspace.id,
            action="WORKSPACE_CREATED",
            entity_type="workspace",
            entity_id=None,
            severity="high",
            details=f"Workspace created: slug '{workspace.slug}', public_id {workspace.public_id}",
        )
        log_action(
            db=db,
            ip_address=client.ip_address,
            user_agent=client.user_agent,
            user_id=admin_user.id,
            workspace_id=workspace.id,
            action="USER_CREATED",
            entity_type="user",
            entity_id=admin_user.id,
            severity="medium",
            details="Workspace admin created at sign-up",
        )
        db.commit()
    except IntegrityError:
        # Lost a race for the same slug between the check above and the insert.
        db.rollback()
        raise taken

    return {"access_token": issue_access_token(admin_user), "token_type": "bearer", "must_change_password": False}
