from pydantic import BaseModel, EmailStr, Field


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
    # None when MFA is still required: then mfa_token is set instead, and the
    # access token comes from POST /auth/mfa/verify.
    access_token: str | None = None
    token_type: str
    must_change_password: bool = False
    mfa_required: bool = False
    mfa_token: str | None = None


class MfaCodeRequest(BaseModel):
    # Validated in the endpoint, so a malformed code gets the same error as a wrong one.
    code: str = Field(default="", max_length=32)


class MfaSetupResponse(BaseModel):
    otpauth_uri: str
    secret: str  # for manual entry; returned only while MFA is not yet enabled


class MfaStatusResponse(BaseModel):
    mfa_enabled: bool
