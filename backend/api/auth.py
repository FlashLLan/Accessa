from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from backend.core.limiter import limiter
from database.db import get_db
from backend.models.user import User
from backend.models.role import Role
from backend.schemas.auth import LoginRequest, WorkspaceSignupRequest, TokenResponse
from backend.core.security import verify_password, hash_password, create_access_token
from backend.services.audit_service import log_action
from backend.services.workspace_service import create_workspace
from backend.core.timeutils import utc_now

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

    user.last_login_at = utc_now()

    token = create_access_token(data={"sub": str(user.id), "workspace": str(user.workspace.public_id)})

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
def signup_workspace(request: Request, data: WorkspaceSignupRequest, db: Session = Depends(get_db)):
    """Register a new workspace. The person signing up becomes its first admin.

    Everyone else joins a workspace only when one of its admins creates their account.
    """
    workspace_name = data.workspace_name.strip()
    workspace_slug = data.workspace_slug.strip().lower()
    full_name = data.full_name.strip()

    if len(workspace_name) < 2:
        raise HTTPException(status_code=400, detail="Workspace name must be at least 2 characters.")
    if not full_name:
        raise HTTPException(status_code=400, detail="Full name cannot be empty.")
    if len(data.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    admin_role = db.query(Role).filter(Role.name == "admin").first()
    if not admin_role:
        raise HTTPException(status_code=500, detail="Default role not configured")

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
        user_id=admin_user.id,
        workspace_id=workspace.id,
        action="WORKSPACE_CREATED",
        entity_type="workspace",
        entity_id=workspace.id,
        severity="high",
        details=f"Workspace '{workspace.name}' ({workspace.slug}) created by '{admin_user.email}'",
    )
    log_action(
        db=db,
        user_id=admin_user.id,
        workspace_id=workspace.id,
        action="USER_CREATED",
        entity_type="user",
        entity_id=admin_user.id,
        severity="medium",
        details=f"Admin '{admin_user.email}' created with the workspace",
    )
    db.commit()

    token = create_access_token(data={"sub": str(admin_user.id), "workspace": str(workspace.public_id)})
    return {"access_token": token, "token_type": "bearer"}
