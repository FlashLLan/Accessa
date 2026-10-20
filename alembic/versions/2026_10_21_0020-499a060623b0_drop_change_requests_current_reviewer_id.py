"""drop change_requests.current_reviewer_id

Only the assigned reviewer may decide a request, and escalation/delegation move
assigned_reviewer_id to the new reviewer, so current_reviewer_id is redundant.

Before the column is dropped, any request whose current_reviewer_id names a
different user than assigned_reviewer_id is reassigned to that current reviewer:
that user held the request, so they keep it. Both columns had composite foreign
keys to users (workspace_id, id), so the new value is always a user of the same
workspace.

Revision ID: 499a060623b0
Revises: c5ee582f5a9e
Create Date: 2026-10-21 00:20:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '499a060623b0'
down_revision: Union[str, Sequence[str], None] = 'c5ee582f5a9e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FK_NAME = "fk_change_requests_workspace_id_current_reviewer_id_users"


def upgrade() -> None:
    op.execute(
        "UPDATE change_requests SET assigned_reviewer_id = current_reviewer_id "
        "WHERE current_reviewer_id IS NOT NULL AND current_reviewer_id <> assigned_reviewer_id"
    )
    op.drop_constraint(op.f(FK_NAME), "change_requests", type_="foreignkey")
    op.drop_column("change_requests", "current_reviewer_id")


def downgrade() -> None:
    op.add_column("change_requests", sa.Column("current_reviewer_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f(FK_NAME), "change_requests", "users",
        ["workspace_id", "current_reviewer_id"], ["workspace_id", "id"],
    )
    # Requests that were escalated or delegated had current = assigned reviewer.
    op.execute(
        "UPDATE change_requests cr SET current_reviewer_id = cr.assigned_reviewer_id "
        "WHERE EXISTS (SELECT 1 FROM review_actions ra WHERE ra.change_request_id = cr.id)"
    )
