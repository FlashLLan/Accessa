from datetime import datetime
from pydantic import BaseModel, ConfigDict

from backend.models.enums import RequestType, EnvironmentType, RiskLevel, RequestStatus
from backend.schemas.user import UserResponse


class ChangeRequestCreate(BaseModel):
    title: str
    description: str
    request_type: RequestType
    target_system: str
    environment: EnvironmentType
    risk_level: RiskLevel
    assigned_reviewer_id: int


class ChangeRequestResponse(BaseModel):
    id: int
    title: str
    description: str
    request_type: RequestType
    target_system: str
    environment: EnvironmentType
    risk_level: RiskLevel
    status: RequestStatus
    creator: UserResponse
    assigned_reviewer: UserResponse
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ApprovalAction(BaseModel):
    decision_comment: str | None = None