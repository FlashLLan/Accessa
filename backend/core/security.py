import os
from datetime import timedelta

import bcrypt
import jwt  # PyJWT

from backend.core.timeutils import utc_now

SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("JWT_SECRET_KEY environment variable is not set")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
MFA_PENDING_TOKEN_EXPIRE_MINUTES = 5

# Every token carries a "type". get_current_user accepts only ACCESS tokens; an
# MFA_PENDING token (password checked, code not yet) is accepted only by
# POST /auth/mfa/verify.
TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_MFA_PENDING = "mfa_pending"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(data: dict):
    """`data` must contain `sub` (user id) and `workspace` (the workspace's public UUID)."""
    to_encode = data.copy()
    expire = utc_now() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "type": TOKEN_TYPE_ACCESS})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_mfa_pending_token(data: dict, jti: str) -> str:
    """Short-lived token after a correct password, for an account with MFA enabled.
    `jti` must match users.mfa_pending_jti; clearing that column revokes the token."""
    to_encode = data.copy()
    expire = utc_now() + timedelta(minutes=MFA_PENDING_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "type": TOKEN_TYPE_MFA_PENDING, "jti": jti})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
