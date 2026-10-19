from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    workspace_slug: str
    email: str
    password: str


class WorkspaceSignupRequest(BaseModel):
    """Creates a new workspace and its first admin.

    Deliberately has no role or workspace-id field; any such keys in the request
    body are ignored, so sign-up can only ever create a new workspace.
    """
    workspace_name: str
    workspace_slug: str
    full_name: str
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    must_change_password: bool = False
