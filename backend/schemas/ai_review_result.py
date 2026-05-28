from datetime import datetime
from pydantic import BaseModel, ConfigDict


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
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
