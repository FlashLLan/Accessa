"""workspaces.ai_review_scope

Workspace setting for the AI review (FR-23): CHANGED_FILES (default) or EXTENDED.
Stored like the other enums: VARCHAR + CHECK on the enum names. Existing
workspaces get CHANGED_FILES.

Revision ID: 7a1e3c9d2b40
Revises: bf5fd76651b0
Create Date: 2026-10-21 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '7a1e3c9d2b40'
down_revision: Union[str, Sequence[str], None] = 'bf5fd76651b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("ai_review_scope", sa.String(13), nullable=False, server_default="CHANGED_FILES"),
    )
    op.create_check_constraint(
        op.f("ck_workspaces_ai_review_scope"),
        "workspaces",
        "ai_review_scope IN ('CHANGED_FILES', 'EXTENDED')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_workspaces_ai_review_scope"), "workspaces", type_="check")
    op.drop_column("workspaces", "ai_review_scope")
