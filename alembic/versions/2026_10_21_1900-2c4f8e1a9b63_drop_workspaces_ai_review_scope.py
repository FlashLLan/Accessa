"""drop workspaces.ai_review_scope

The AI review scope is no longer a workspace setting: the reviewer chooses it for
each AI review. Revision 7a1e3c9d2b40 had already been applied, so the column is
dropped here instead of editing that migration.

Revision ID: 2c4f8e1a9b63
Revises: 7a1e3c9d2b40
Create Date: 2026-10-21 19:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '2c4f8e1a9b63'
down_revision: Union[str, Sequence[str], None] = '7a1e3c9d2b40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_workspaces_ai_review_scope"), "workspaces", type_="check")
    op.drop_column("workspaces", "ai_review_scope")


def downgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("ai_review_scope", sa.String(13), nullable=False, server_default="CHANGED_FILES"),
    )
    op.create_check_constraint(
        op.f("ck_workspaces_ai_review_scope"),
        "workspaces",
        "ai_review_scope IN ('CHANGED_FILES', 'EXTENDED')",
    )
