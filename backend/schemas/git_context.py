import re
from datetime import datetime
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from backend.services.secret_masking import mask_secrets

_SECRET_PATTERNS = [
    "password=",
    "token=",
    "api_key",
    "private key",
    "begin rsa private key",
    "begin private key",
    "begin openssh private key",
    "-----begin",
]

_URL_MAX = 2000
_SHORT_MAX = 250
_TEXT_MAX = 10_000


def _reject_secrets(value: str | None) -> str | None:
    if value is None:
        return value
    lower = value.lower()
    for pattern in _SECRET_PATTERNS:
        if pattern in lower:
            raise ValueError(
                "Content appears to contain sensitive information. "
                "Do not include secrets, tokens, or private keys."
            )
    return value


def _validate_url(v: str | None) -> str | None:
    if v is None or v.strip() == "":
        return None
    v = v.strip()
    if not re.match(r"^https?://", v, re.IGNORECASE):
        raise ValueError("Must be a valid URL starting with http:// or https://")
    if len(v) > _URL_MAX:
        raise ValueError(f"URL too long (max {_URL_MAX} characters)")
    _reject_secrets(v)
    return v


class GitContextCreate(BaseModel):
    provider: str | None = None
    repository_url: str | None = None
    repository_name: str | None = None
    branch_name: str | None = None
    target_branch: str | None = None
    commit_hash: str | None = None
    pull_request_url: str | None = None  # pull request or merge request URL
    changed_files_summary: str | None = None
    diff_text: str | None = None

    @field_validator("repository_url", "pull_request_url", mode="before")
    @classmethod
    def validate_url_fields(cls, v):
        return _validate_url(v)

    @field_validator("commit_hash", "branch_name", "target_branch", "repository_name", "provider", mode="before")
    @classmethod
    def validate_short_text(cls, v):
        if v is None or v.strip() == "":
            return None
        v = v.strip()
        if len(v) > _SHORT_MAX:
            raise ValueError(f"Value too long (max {_SHORT_MAX} characters)")
        return _reject_secrets(v)

    @field_validator("changed_files_summary", "diff_text", mode="before")
    @classmethod
    def validate_long_text(cls, v):
        if v is None or v.strip() == "":
            return None
        v = v.strip()
        if len(v) > _TEXT_MAX:
            raise ValueError(f"Value too long (max {_TEXT_MAX} characters)")
        # Diffs and file lists are code: hard-coded secret values are masked
        # (replaced by [REDACTED]) instead of rejecting the whole text.
        masked, _ = mask_secrets(v)
        return masked

    def has_any_data(self) -> bool:
        return any(
            getattr(self, f) is not None
            for f in self.__class__.model_fields
        )


class GitContextResponse(BaseModel):
    id: int
    change_request_id: int
    provider: str | None = None
    repository_url: str | None = None
    repository_name: str | None = None
    branch_name: str | None = None
    target_branch: str | None = None
    commit_hash: str | None = None
    pull_request_url: str | None = None  # pull request or merge request URL
    changed_files_summary: str | None = None
    diff_text: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
