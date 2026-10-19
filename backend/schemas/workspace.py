from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class WorkspaceResponse(BaseModel):
    # Only the public id is exposed; the internal integer id never leaves the backend.
    public_id: UUID
    slug: str
    name: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
