from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RoomResponse(BaseModel):
    # Only the public id is exposed; the internal integer id never leaves the backend.
    public_id: str
    name: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
