from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr

from backend.schemas.role import RoleResponse
from backend.schemas.workspace import WorkspaceResponse


class UserCreate(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    role_id: int

class UserRoleUpdate(BaseModel):
    role_id: int


class UserResponse(BaseModel):
    id: int
    full_name: str
    email: EmailStr
    role: RoleResponse
    is_active: bool
    # Whether MFA is enrolled; the secret itself is never part of any response.
    mfa_enabled: bool = False
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserMeResponse(UserResponse):
    workspace: WorkspaceResponse
    must_change_password: bool
    # Requests in this workspace waiting for this user's decision (assigned
    # reviewer, pending review). Drives the "Review" navigation item.
    pending_reviews_count: int = 0


class UserShortResponse(BaseModel):
    id: int
    full_name: str
    email: EmailStr
    role: RoleResponse

    model_config = ConfigDict(from_attributes=True)


class UserStatsResponse(BaseModel):
    total_requests_created: int
    total_requests_approved: int
    total_requests_rejected: int


class UserDetailsResponse(BaseModel):
    id: int
    full_name: str
    email: EmailStr
    role: RoleResponse
    is_active: bool
    mfa_enabled: bool = False  # never the secret
    created_at: datetime
    stats: UserStatsResponse

    model_config = ConfigDict(from_attributes=True)


class UserUpdateMe(BaseModel):
    full_name: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str


class UserMeStatsResponse(BaseModel):
    # All users — requests
    requests_created: int
    pending_requests: int
    approved_requests: int
    rejected_requests: int
    comments_written: int
    # All users — reviews
    requests_reviewed: int
    approved_decisions: int
    rejected_decisions: int
    delegations_performed: int
    escalations_performed: int
    # Admins only (None for non-admins)
    users_created: Optional[int]
    users_deactivated: Optional[int]
    role_changes_performed: Optional[int]
    admin_actions_logged: Optional[int]