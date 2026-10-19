from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: str
    password: str


class RoomSignupRequest(BaseModel):
    """Creates a new room and its first sysadmin."""
    room_name: str = Field(min_length=2, max_length=100)
    full_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
