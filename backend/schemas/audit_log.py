from datetime import datetime

from pydantic import BaseModel, ConfigDict, model_validator

from backend.schemas.user import UserShortResponse


class AuditLogResponse(BaseModel):
    id: int
    action: str
    entity_type: str
    # Kept for linking (e.g. to /requests/<id>); never the internal workspace id.
    entity_id: int | None = None
    # Readable reference resolved within the current workspace at read time:
    # request title, "Name (email)" for users, workspace slug, or "Audit log".
    entity_label: str | None = None
    details: str | None = None
    severity: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    # Role of the actor when the action happened (NULL for older entries and for
    # failed logins with an unknown email).
    actor_role: str | None = None
    created_at: datetime
    # None when there is no known actor (failed login with an unknown email).
    user: UserShortResponse | None = None

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def hide_internal_workspace_id(self):
        # A workspace's internal integer id never leaves the backend, including for
        # audit rows written before workspace events stopped storing it.
        if self.entity_type == "workspace":
            self.entity_id = None
        return self
