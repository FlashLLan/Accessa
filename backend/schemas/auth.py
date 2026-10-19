from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: str
    password: str


class WorkspaceSignupRequest(BaseModel):
    """Creates a new workspace and its first admin."""
    workspace_name: str = Field(min_length=2, max_length=120)
    workspace_slug: str = Field(min_length=3, max_length=32)
    full_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
