"""users.mfa_locked_until: MFA brute-force lock (SEC-14)

After 10 consecutive wrong codes for an account (across logins) MFA verification
is refused until this time (15 minutes). Cleared by a successful verify or an
admin MFA reset.

Revision ID: 8c5f3a7e1d94
Revises: 6b2d9e4f7a31
Create Date: 2026-10-22 14:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '8c5f3a7e1d94'
down_revision: Union[str, Sequence[str], None] = '6b2d9e4f7a31'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("mfa_locked_until", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "mfa_locked_until")
