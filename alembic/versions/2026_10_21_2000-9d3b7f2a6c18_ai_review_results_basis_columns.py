"""ai_review_results: what each AI review was based on

- reviewed_commit: the pull request's head SHA the files were read at
- review_scope: CHANGED_FILES or EXTENDED, chosen by the reviewer per review
  (VARCHAR + CHECK like the other enums)
- files_reviewed / files_skipped: JSONB lists ({path, source} / {path, reason})
- changed_files_total: the PR's changed files according to GitHub
- input_truncated: the total input size limit was hit
- secrets_masked: number of distinct hard-coded secret values masked before sending

Existing results (the old stub) keep NULL / false / 0.

Revision ID: 9d3b7f2a6c18
Revises: 2c4f8e1a9b63
Create Date: 2026-10-21 20:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '9d3b7f2a6c18'
down_revision: Union[str, Sequence[str], None] = '2c4f8e1a9b63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ai_review_results", sa.Column("reviewed_commit", sa.String(40), nullable=True))
    op.add_column("ai_review_results", sa.Column("review_scope", sa.String(13), nullable=True))
    op.create_check_constraint(
        op.f("ck_ai_review_results_ai_review_scope"),
        "ai_review_results",
        "review_scope IN ('CHANGED_FILES', 'EXTENDED')",
    )
    op.add_column("ai_review_results", sa.Column("files_reviewed", postgresql.JSONB(), nullable=True))
    op.add_column("ai_review_results", sa.Column("files_skipped", postgresql.JSONB(), nullable=True))
    op.add_column("ai_review_results", sa.Column("changed_files_total", sa.Integer(), nullable=True))
    op.add_column("ai_review_results",
                  sa.Column("input_truncated", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("ai_review_results",
                  sa.Column("secrets_masked", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    for column in ("secrets_masked", "input_truncated", "changed_files_total", "files_skipped", "files_reviewed"):
        op.drop_column("ai_review_results", column)
    op.drop_constraint(op.f("ck_ai_review_results_ai_review_scope"), "ai_review_results", type_="check")
    op.drop_column("ai_review_results", "review_scope")
    op.drop_column("ai_review_results", "reviewed_commit")
