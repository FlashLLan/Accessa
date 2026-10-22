"""TOTP (RFC 6238) for multi-factor authentication (SEC-14).

- 6 digits, 30-second time step, ±1 step accepted for clock drift.
- A code is accepted only for a time step later than the last one accepted for
  that user (users.mfa_last_used_step), so a code can never be used twice.
- Secrets are stored encrypted with Fernet; the key MFA_ENCRYPTION_KEY comes from
  the environment and is required at startup, like JWT_SECRET_KEY.
"""
import hmac
import os
import re
import time

import pyotp
from cryptography.fernet import Fernet, InvalidToken

ISSUER = "Accessa"
STEP_SECONDS = 30
DIGITS = 6
VALID_WINDOW = 1  # steps before and after the current one

_key = os.getenv("MFA_ENCRYPTION_KEY")
if not _key:
    raise RuntimeError("MFA_ENCRYPTION_KEY environment variable is not set (see .env.example)")
try:
    _fernet = Fernet(_key)
except (ValueError, TypeError):
    raise RuntimeError("MFA_ENCRYPTION_KEY is not a valid Fernet key (see .env.example)") from None

_CODE = re.compile(rf"^\d{{{DIGITS}}}$")


def now() -> float:
    """Current time; tests replace it to move the clock."""
    return time.time()


def new_secret() -> str:
    return pyotp.random_base32()  # 160 bits, base32


def encrypt_secret(secret: str) -> str:
    return _fernet.encrypt(secret.encode()).decode()


def decrypt_secret(token: str) -> str | None:
    try:
        return _fernet.decrypt(token.encode()).decode()
    except (InvalidToken, ValueError, AttributeError):
        return None


def provisioning_uri(secret: str, account: str) -> str:
    return pyotp.TOTP(secret, digits=DIGITS, interval=STEP_SECONDS).provisioning_uri(
        name=account, issuer_name=ISSUER
    )


def current_step(at: float | None = None) -> int:
    return int((now() if at is None else at) // STEP_SECONDS)


def matching_step(secret: str, code: str, last_used_step: int | None) -> int | None:
    """The time step `code` belongs to, if it is valid now (±VALID_WINDOW) and newer
    than `last_used_step`; otherwise None. Every candidate step is compared, in
    constant time, so timing does not reveal which one matched."""
    if not isinstance(code, str) or not _CODE.match(code):
        return None
    totp = pyotp.TOTP(secret, digits=DIGITS, interval=STEP_SECONDS)
    step_now = current_step()
    match = None
    for step in range(step_now - VALID_WINDOW, step_now + VALID_WINDOW + 1):
        if hmac.compare_digest(totp.generate_otp(step), code):
            match = step
    if match is None or (last_used_step is not None and match <= last_used_step):
        return None
    return match
