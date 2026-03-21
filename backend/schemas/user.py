from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr

from backend.schemas.role import RoleResponse


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
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


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
    created_at: datetime
    stats: UserStatsResponse

    model_config = ConfigDict(from_attributes=True)