from datetime import datetime
from pydantic import BaseModel, ConfigDict


class GitContextCreate(BaseModel):
    provider: str | None = None
    repository_url: str | None = None
    repository_name: str | None = None
    branch_name: str | None = None
    target_branch: str | None = None
    commit_hash: str | None = None
    pull_request_url: str | None = None
    merge_request_url: str | None = None
    changed_files_summary: str | None = None
    diff_text: str | None = None


class GitContextResponse(BaseModel):
    id: int
    change_request_id: int
    provider: str | None = None
    repository_url: str | None = None
    repository_name: str | None = None
    branch_name: str | None = None
    target_branch: str | None = None
    commit_hash: str | None = None
    pull_request_url: str | None = None
    merge_request_url: str | None = None
    changed_files_summary: str | None = None
    diff_text: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
