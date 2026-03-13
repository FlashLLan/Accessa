from pydantic import BaseModel, ConfigDict


class RoleResponse(BaseModel):
    id: int
    name: str
    level: int

    model_config = ConfigDict(from_attributes=True)