from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr


class UserCreate(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    role_id: int


class UserResponse(BaseModel):
    id: int
    full_name: str
    email: EmailStr
    role_id: int
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)