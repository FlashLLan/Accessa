from datetime import datetime
from pydantic import BaseModel, ConfigDict

from backend.schemas.user import UserShortResponse


class AuditLogResponse(BaseModel):
    id: int
    action: str
    entity_type: str
    entity_id: int
    details: str | None = None
    created_at: datetime
    user: UserShortResponse

    model_config = ConfigDict(from_attributes=True)