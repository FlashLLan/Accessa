"""Multi-factor authentication with TOTP (SEC-14).

- POST /auth/mfa/setup    new secret + otpauth URI, only while MFA is not enabled
- POST /auth/mfa/confirm  first valid code enables MFA
- POST /auth/mfa/verify   second login step: mfa_pending token + code -> access token

Codes and secrets are never logged or audited.
"""
import hmac
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt  # PyJWT
from sqlalchemy.orm import Session

from database.db import get_db
from backend.api.auth import issue_access_token
from backend.core import mfa
from backend.core.dependencies import ClientInfo, get_client_info, get_current_user
from backend.core.limiter import limiter
from backend.core.security import ALGORITHM, SECRET_KEY, TOKEN_TYPE_MFA_PENDING
from backend.core.timeutils import utc_now
from backend.models.user import User
from backend.schemas.auth import MfaCodeRequest, MfaSetupResponse, MfaStatusResponse, TokenResponse
from backend.services.audit_service import log_action

router = APIRouter(prefix="/auth/mfa", tags=["MFA"])

# One message for every verify failure: bad/expired/revoked token, wrong, reused
# or malformed code, deactivated account.
MFA_INVALID = "Invalid or expired code"
# Wrong codes allowed with one mfa_pending token before it is revoked.
MAX_FAILED_ATTEMPTS = 5
# Consecutive wrong codes for an account (across logins) that lock MFA
# verification for LOCK_SECONDS. The count is reset only by a successful verify
# or an admin MFA reset, so after a lock expires the next wrong code locks again.
LOCK_AFTER_FAILED_ATTEMPTS = 10
LOCK_SECONDS = 15 * 60

_pending_bearer = HTTPBearer(auto_error=False)


def _locked_user(db: Session, user_id: int) -> User | None:
    # Row lock: two simultaneous requests with the same code cannot both pass the
    # last-used-step check.
    return db.query(User).filter(User.id == user_id).with_for_update().first()


def _about(user: User) -> dict:
    """Common audit fields: the user acts on their own account."""
    return {"user_id": user.id, "entity_type": "user", "entity_id": user.id}


def _matching_step(user: User, code: str) -> int | None:
    secret = mfa.decrypt_secret(user.mfa_secret_encrypted) if user.mfa_secret_encrypted else None
    if secret is None:
        return None
    return mfa.matching_step(secret, code, user.mfa_last_used_step)


# --- enrolment --------------------------------------------------------------------------

@router.post("/setup", response_model=MfaSetupResponse)
def setup_mfa(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate a new secret. MFA stays disabled until /confirm accepts a code.
    Calling it again before confirming replaces the secret."""
    if current_user.mfa_enabled:
        raise HTTPException(status_code=409, detail="MFA is already enabled")

    secret = mfa.new_secret()
    current_user.mfa_secret_encrypted = mfa.encrypt_secret(secret)
    current_user.mfa_last_used_step = None
    db.commit()

    return {"otpauth_uri": mfa.provisioning_uri(secret, current_user.email), "secret": secret}


@router.post("/confirm", response_model=MfaStatusResponse)
@limiter.limit("5/minute")
def confirm_mfa(
    request: Request,
    data: MfaCodeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    client: ClientInfo = Depends(get_client_info),
):
    if current_user.mfa_enabled:
        raise HTTPException(status_code=409, detail="MFA is already enabled")
    if not current_user.mfa_secret_encrypted:
        raise HTTPException(status_code=400, detail="Start MFA setup first")

    user = _locked_user(db, current_user.id)
    step = _matching_step(user, data.code)
    if step is None:
        log_action(db=db, ip_address=client.ip_address, user_agent=client.user_agent, **_about(user), action="MFA_FAILED", severity="medium",
                   details="Wrong MFA code during enrolment")
        db.commit()
        raise HTTPException(status_code=400, detail=MFA_INVALID)

    user.mfa_enabled = True
    user.mfa_last_used_step = step
    log_action(db=db, ip_address=client.ip_address, user_agent=client.user_agent, **_about(user), action="MFA_ENROLLED", severity="medium",
               details="MFA enrolled (TOTP)")
    db.commit()
    return {"mfa_enabled": True}


# --- second login step ----------------------------------------------------------------------

@router.post("/verify", response_model=TokenResponse)
@limiter.limit("5/minute")
def verify_mfa(
    request: Request,
    data: MfaCodeRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(_pending_bearer),
    db: Session = Depends(get_db),
    client: ClientInfo = Depends(get_client_info),
):
    """Takes the mfa_pending token (Authorization: Bearer) and the 6-digit code.
    Accepts only mfa_pending tokens; access tokens are refused here and pending
    tokens everywhere else."""
    invalid = HTTPException(status_code=401, detail=MFA_INVALID)
    if credentials is None:
        raise invalid
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != TOKEN_TYPE_MFA_PENDING:
            raise invalid
        user_id = int(payload["sub"])
        token_workspace = UUID(payload["workspace"])
        jti = str(payload["jti"])
        failures_at_issue = int(payload.get("fa0", 0))
    except (jwt.PyJWTError, KeyError, TypeError, ValueError, AttributeError):
        raise invalid

    user = _locked_user(db, user_id)
    if user is None or user.workspace.public_id != token_workspace:
        raise invalid

    if (
        not user.is_active
        or not user.mfa_enabled
        or user.mfa_pending_jti is None
        or not hmac.compare_digest(user.mfa_pending_jti, jti)
    ):
        # A revoked (5 wrong codes, newer login, MFA reset) or otherwise unusable token.
        log_action(db=db, ip_address=client.ip_address, user_agent=client.user_agent, **_about(user), action="MFA_FAILED", severity="medium",
                   details="MFA attempt with an invalid sign-in token")
        db.commit()
        raise invalid

    now = mfa.now()
    if user.mfa_locked_until is not None and user.mfa_locked_until.timestamp() > now:
        # Locked: refused without looking at the code, with the same generic error.
        log_action(db=db, ip_address=client.ip_address, user_agent=client.user_agent, **_about(user),
                   action="MFA_FAILED", severity="medium",
                   details="MFA verification refused: account locked after repeated wrong codes")
        db.commit()
        raise invalid

    step = _matching_step(user, data.code)
    if step is None:
        user.mfa_failed_attempts += 1
        token_failures = max(1, user.mfa_failed_attempts - failures_at_issue)  # wrong codes with this token
        locked = user.mfa_failed_attempts >= LOCK_AFTER_FAILED_ATTEMPTS
        revoked = locked or token_failures >= MAX_FAILED_ATTEMPTS
        if revoked:
            user.mfa_pending_jti = None
        if locked:
            user.mfa_locked_until = datetime.fromtimestamp(now + LOCK_SECONDS, tz=timezone.utc)
        log_action(
            db=db, ip_address=client.ip_address, user_agent=client.user_agent, **_about(user), action="MFA_FAILED",
            severity="high" if revoked else "medium",
            details=f"Wrong MFA code at login ({token_failures} of {MAX_FAILED_ATTEMPTS} for this sign-in, "
                    f"{user.mfa_failed_attempts} in a row for the account)"
            + ("; sign-in attempt invalidated" if revoked else ""),
        )
        if locked:
            log_action(
                db=db, ip_address=client.ip_address, user_agent=client.user_agent, **_about(user),
                action="MFA_LOCKED", severity="high",
                details=f"MFA verification locked for {LOCK_SECONDS // 60} minutes after "
                        f"{user.mfa_failed_attempts} consecutive wrong codes",
            )
        db.commit()
        raise invalid

    user.mfa_last_used_step = step
    user.mfa_pending_jti = None
    user.mfa_failed_attempts = 0
    user.mfa_locked_until = None
    user.last_login_at = utc_now()
    log_action(db=db, ip_address=client.ip_address, user_agent=client.user_agent, **_about(user), action="MFA_VERIFIED", severity="low",
               details="MFA code accepted at login")
    log_action(db=db, ip_address=client.ip_address, user_agent=client.user_agent, **_about(user), action="LOGIN_SUCCESS", severity="low",
               details="User logged in (password and MFA)")
    db.commit()

    return {
        "access_token": issue_access_token(user),
        "token_type": "bearer",
        "must_change_password": user.must_change_password,
    }
