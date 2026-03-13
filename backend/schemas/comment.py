from datetime import datetime
from pydantic import BaseModel, ConfigDict

from backend.schemas.user import UserShortResponse


class CommentCreate(BaseModel):
    comment_text: str


class CommentResponse(BaseModel):
    id: int
    comment_text: str
    created_at: datetime
    user: UserShortResponse

    model_config = ConfigDict(from_attributes=True)