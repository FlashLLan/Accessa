from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database.db import get_db
from backend.models.user import User
from backend.models.role import Role
from backend.core.dependencies import get_current_user, can_create_role, workspace_users
from backend.core.security import hash_password, verify_password
from backend.services.audit_service import log_action
from backend.core.timeutils import utc_now
from sqlalchemy import func
from backend.models.change_request import ChangeRequest
from backend.models.approval import Approval
from backend.models.enums import RequestStatus, ApprovalDecision, ReviewActionType
from backend.models.comment import Comment
from backend.models.review_action import ReviewAction
from backend.models.audit_log import AuditLog
from backend.schemas.user import (
    UserCreate,
    UserResponse,
    UserShortResponse,
    UserRoleUpdate,
    UserDetailsResponse,
    UserUpdateMe,
    PasswordChangeRequest,
    UserMeStatsResponse,
    UserMeResponse,
)

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/", response_model=list[UserResponse])
def list_users(
    search: str | None = Query(None),
    role: str | None = Query(None),
    status: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role.name != "admin":
        raise HTTPException(status_code=403, detail="Only admin can view all users")

    query = workspace_users(db, current_user).join(Role)

    if search:
        term = f"%{search.lower()}%"
        query = query.filter(
            func.lower(User.full_name).like(term) |
            func.lower(User.email).like(term)
        )

    if role:
        query = query.filter(Role.name == role)

    if status == "active":
        query = query.filter(User.is_active == True)
    elif status == "inactive":
        query = query.filter(User.is_active == False)

    return query.all()


@router.get("/me", response_model=UserMeResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/reviewers", response_model=list[UserShortResponse])
def list_reviewers(
    requester_role: str | None = Query(None),
    risk_level: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    from backend.services.approval_service import get_allowed_approver_roles

    if requester_role and risk_level:
        eligible_roles = get_allowed_approver_roles(requester_role, risk_level)
        if not eligible_roles:
            return []
        role_filter = Role.name.in_(eligible_roles)
    else:
        role_filter = Role.name.in_(["mid", "senior", "lead"])

    reviewers = (
        workspace_users(db, current_user)
        .join(Role)
        .filter(
            User.is_active == True,
            User.id != current_user.id,
            role_filter,
        )
        .all()
    )

    return reviewers


@router.put("/me", response_model=UserResponse)
def update_me(
    payload: UserUpdateMe,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    full_name = payload.full_name.strip()
    if not full_name:
        raise HTTPException(status_code=400, detail="Full name cannot be empty.")

    existing = workspace_users(db, current_user).filter(
        func.lower(User.full_name) == full_name.lower(),
        User.id != current_user.id,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="This name is already taken by another user.")

    old_name = current_user.full_name
    current_user.full_name = full_name
    current_user.updated_at = utc_now()
    db.commit()
    db.refresh(current_user)

    log_action(
        db=db,
        user_id=current_user.id,
        action="PROFILE_UPDATED",
        entity_type="user",
        entity_id=current_user.id,
        severity="low",
        details="Updated full_name",
        old_value=old_name,
        new_value=current_user.full_name,
    )
    db.commit()

    return current_user


@router.put("/me/password", status_code=200)
def change_my_password(
    payload: PasswordChangeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")

    if len(payload.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters.")

    if payload.new_password != payload.confirm_password:
        raise HTTPException(status_code=400, detail="New password and confirmation do not match.")

    if verify_password(payload.new_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="New password must be different from the current password.")

    current_user.hashed_password = hash_password(payload.new_password)
    current_user.updated_at = utc_now()
    db.commit()

    log_action(
        db=db,
        user_id=current_user.id,
        action="PASSWORD_CHANGED",
        entity_type="user",
        entity_id=current_user.id,
        severity="high",
        details="User changed their own password",
    )
    db.commit()

    return {"message": "Password changed successfully."}


@router.get("/me/stats", response_model=UserMeStatsResponse)
def get_my_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    uid = current_user.id

    requests_created = (
        db.query(func.count(ChangeRequest.id))
        .filter(ChangeRequest.created_by == uid)
        .scalar() or 0
    )

    pending_requests = (
        db.query(func.count(ChangeRequest.id))
        .filter(
            ChangeRequest.created_by == uid,
            ChangeRequest.status.in_([
                RequestStatus.PENDING_REVIEW,
                RequestStatus.ESCALATED,
                RequestStatus.DELEGATED,
            ]),
        )
        .scalar() or 0
    )

    approved_requests = (
        db.query(func.count(ChangeRequest.id))
        .filter(ChangeRequest.created_by == uid, ChangeRequest.status == RequestStatus.APPROVED)
        .scalar() or 0
    )

    rejected_requests = (
        db.query(func.count(ChangeRequest.id))
        .filter(ChangeRequest.created_by == uid, ChangeRequest.status == RequestStatus.REJECTED)
        .scalar() or 0
    )

    comments_written = (
        db.query(func.count(Comment.id))
        .filter(Comment.user_id == uid)
        .scalar() or 0
    )

    requests_reviewed = (
        db.query(func.count(Approval.id))
        .filter(Approval.reviewer_id == uid)
        .scalar() or 0
    )

    approved_decisions = (
        db.query(func.count(Approval.id))
        .filter(Approval.reviewer_id == uid, Approval.decision == ApprovalDecision.APPROVED)
        .scalar() or 0
    )

    rejected_decisions = (
        db.query(func.count(Approval.id))
        .filter(Approval.reviewer_id == uid, Approval.decision == ApprovalDecision.REJECTED)
        .scalar() or 0
    )

    delegations_performed = (
        db.query(func.count(ReviewAction.id))
        .filter(ReviewAction.actor_id == uid, ReviewAction.action_type == ReviewActionType.DELEGATE)
        .scalar() or 0
    )

    escalations_performed = (
        db.query(func.count(ReviewAction.id))
        .filter(ReviewAction.actor_id == uid, ReviewAction.action_type == ReviewActionType.ESCALATE)
        .scalar() or 0
    )

    users_created = None
    users_deactivated = None
    role_changes_performed = None
    admin_actions_logged = None

    if current_user.role.name == "admin":
        users_created = (
            db.query(func.count(User.id))
            .filter(User.created_by == uid)
            .scalar() or 0
        )
        users_deactivated = (
            db.query(func.count(AuditLog.id))
            .filter(AuditLog.user_id == uid, AuditLog.action == "deactivate_user")
            .scalar() or 0
        )
        role_changes_performed = (
            db.query(func.count(AuditLog.id))
            .filter(AuditLog.user_id == uid, AuditLog.action == "update_user_role")
            .scalar() or 0
        )
        admin_actions_logged = (
            db.query(func.count(AuditLog.id))
            .filter(AuditLog.user_id == uid)
            .scalar() or 0
        )

    return UserMeStatsResponse(
        requests_created=requests_created,
        pending_requests=pending_requests,
        approved_requests=approved_requests,
        rejected_requests=rejected_requests,
        comments_written=comments_written,
        requests_reviewed=requests_reviewed,
        approved_decisions=approved_decisions,
        rejected_decisions=rejected_decisions,
        delegations_performed=delegations_performed,
        escalations_performed=escalations_performed,
        users_created=users_created,
        users_deactivated=users_deactivated,
        role_changes_performed=role_changes_performed,
        admin_actions_logged=admin_actions_logged,
    )


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    user = workspace_users(db, current_user).filter(User.id == user_id).first()

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
    if len(user_data.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    existing_name = workspace_users(db, current_user).filter(
        func.lower(User.full_name) == user_data.full_name.strip().lower()
    ).first()
    if existing_name:
        raise HTTPException(status_code=400, detail="A user with this name already exists.")

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
        workspace_id=current_user.workspace_id,
        created_by=current_user.id,
        is_active=True
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    log_action(
        db=db,
        user_id=current_user.id,
        action="USER_CREATED",
        entity_type="user",
        entity_id=new_user.id,
        severity="medium",
        details=f"Created user '{new_user.email}'"
    )
    log_action(
        db=db,
        user_id=current_user.id,
        action="ROLE_ASSIGNED",
        entity_type="user",
        entity_id=new_user.id,
        severity="medium",
        details=f"Assigned role '{new_user.role_id}' to '{new_user.email}'"
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

    user = workspace_users(db, current_user).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")

    if not user.is_active:
        raise HTTPException(status_code=400, detail="User is already inactive")

    user.is_active = False
    user.deactivated_at = utc_now()
    db.commit()
    db.refresh(user)

    log_action(
        db=db,
        user_id=current_user.id,
        action="USER_DEACTIVATED",
        entity_type="user",
        entity_id=user.id,
        severity="high",
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

    user = workspace_users(db, current_user).filter(User.id == user_id).first()
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
        action="USER_REACTIVATED",
        entity_type="user",
        entity_id=user.id,
        severity="high",
        details=f"Reactivated user '{user.email}'"
    )
    db.commit()

    return user

@router.patch("/{user_id}/role", response_model=UserResponse)
def update_user_role(
    user_id: int,
    payload: UserRoleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role.name != "admin":
        raise HTTPException(status_code=403, detail="Only admin can change user roles")

    user = workspace_users(db, current_user).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot change your own role")

    new_role = db.query(Role).filter(Role.id == payload.role_id).first()
    if not new_role:
        raise HTTPException(status_code=400, detail="Invalid role_id")

    old_role_name = user.role.name

    if old_role_name == new_role.name:
        raise HTTPException(status_code=400, detail="User already has this role")

    user.role_id = new_role.id
    db.commit()
    db.refresh(user)

    log_action(
        db=db,
        user_id=current_user.id,
        action="ROLE_CHANGED",
        entity_type="user",
        entity_id=user.id,
        severity="high",
        details=f"Changed role for '{user.email}' from '{old_role_name}' to '{new_role.name}'"
    )
    db.commit()

    return user

@router.get("/{user_id}/details", response_model=UserDetailsResponse)
def get_user_details(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role.name != "admin":
        raise HTTPException(status_code=403, detail="Only admin can view user details")

    user = workspace_users(db, current_user).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    total_requests_created = (
        db.query(func.count(ChangeRequest.id))
        .filter(ChangeRequest.created_by == user.id)
        .scalar()
    )

    total_requests_approved = (
        db.query(func.count(Approval.id))
        .filter(
            Approval.reviewer_id == user.id,
            Approval.decision == ApprovalDecision.APPROVED
        )
        .scalar()
    )

    total_requests_rejected = (
        db.query(func.count(Approval.id))
        .filter(
            Approval.reviewer_id == user.id,
            Approval.decision == ApprovalDecision.REJECTED
        )
        .scalar()
    )

    return {
        "id": user.id,
        "full_name": user.full_name,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": user.created_at,
        "stats": {
            "total_requests_created": total_requests_created or 0,
            "total_requests_approved": total_requests_approved or 0,
            "total_requests_rejected": total_requests_rejected or 0,
        },
    }