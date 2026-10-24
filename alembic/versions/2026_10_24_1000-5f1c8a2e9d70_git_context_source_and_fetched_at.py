"""git_context.source and fetched_at (FR-21)

- source: GITHUB when commit_hash, changed_files_summary and diff_text were
  fetched from the GitHub pull request at submission; MANUAL when entered by
  the requester (not verified). VARCHAR + CHECK like the other enums.
  Existing rows are MANUAL.
- fetched_at: when the GitHub data was fetched.

Revision ID: 5f1c8a2e9d70
Revises: 8c5f3a7e1d94
Create Date: 2026-10-24 10:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '5f1c8a2e9d70'
down_revision: Union[str, Sequence[str], None] = '8c5f3a7e1d94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("git_context", sa.Column("source", sa.String(6), nullable=False, server_default="MANUAL"))
    op.create_check_constraint(
        op.f("ck_git_context_git_context_source"), "git_context", "source IN ('GITHUB', 'MANUAL')"
    )
    op.add_column("git_context", sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("git_context", "fetched_at")
    op.drop_constraint(op.f("ck_git_context_git_context_source"), "git_context", type_="check")
    op.drop_column("git_context", "source")
