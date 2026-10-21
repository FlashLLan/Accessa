from datetime import datetime
from pydantic import BaseModel, ConfigDict

from backend.models.enums import AIReviewScope


class AIReviewTrigger(BaseModel):
    # Chosen by the reviewer for this review; the body may be omitted entirely.
    scope: AIReviewScope = AIReviewScope.CHANGED_FILES


class ReviewedFile(BaseModel):
    path: str
    source: str  # changed, related, config


class SkippedFile(BaseModel):
    path: str
    reason: str  # removed, binary, too_large, size_limit, unavailable


class AIReviewResultResponse(BaseModel):
    id: int
    change_request_id: int
    summary: str | None = None
    suggested_risk_level: str | None = None
    recommended_reviewer_role: str | None = None
    impact_area: str | None = None
    red_flags: str | None = None
    verification_checklist: str | None = None
    improvement_suggestions: str | None = None
    model_name: str | None = None
    prompt_version: str | None = None
    reviewed_commit: str | None = None
    review_scope: AIReviewScope | None = None
    files_reviewed: list[ReviewedFile] | None = None
    files_skipped: list[SkippedFile] | None = None
    changed_files_total: int | None = None
    input_truncated: bool = False
    secrets_masked: int = 0
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
