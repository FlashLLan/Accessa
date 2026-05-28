from datetime import datetime
from pydantic import BaseModel, ConfigDict

from backend.models.enums import ReviewActionType
from backend.schemas.user import UserShortResponse


class ReviewActionCreate(BaseModel):
    action_type: ReviewActionType
    target_reviewer_id: int | None = None
    comment: str | None = None


class ReviewActionResponse(BaseModel):
    id: int
    change_request_id: int
    actor: UserShortResponse
    action_type: ReviewActionType
    target_reviewer: UserShortResponse | None = None
    from_status: str | None = None
    to_status: str | None = None
    comment: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
