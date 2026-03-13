from datetime import datetime
from pydantic import BaseModel, ConfigDict

from backend.models.enums import RequestType, EnvironmentType, RiskLevel, RequestStatus, ApprovalDecision
from backend.schemas.user import UserResponse, UserShortResponse

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
    creator: UserShortResponse
    assigned_reviewer: UserShortResponse
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ApprovalAction(BaseModel):
    decision_comment: str | None = None

class ChangeRequestUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    request_type: RequestType | None = None
    target_system: str | None = None
    environment: EnvironmentType | None = None
    risk_level: RiskLevel | None = None
    assigned_reviewer_id: int | None = None


class ApprovalHistoryResponse(BaseModel):
    id: int
    reviewer: UserShortResponse
    decision: ApprovalDecision
    decision_comment: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)