"""users: TOTP replay protection and mfa_pending state (SEC-14)

- mfa_last_used_step: last accepted TOTP time step; a code for that step or an
  earlier one is rejected, so no code can be used twice.
- mfa_pending_jti: id of the one valid mfa_pending token (issued after a correct
  password); clearing it revokes that token.
- mfa_failed_attempts: wrong codes for the current mfa_pending token; at 5 the
  token is revoked.

mfa_enabled and mfa_secret_encrypted already exist (initial schema).

Revision ID: 6b2d9e4f7a31
Revises: 4e6a1c8b5d27
Create Date: 2026-10-22 09:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '6b2d9e4f7a31'
down_revision: Union[str, Sequence[str], None] = '4e6a1c8b5d27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("mfa_last_used_step", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("mfa_pending_jti", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("mfa_failed_attempts", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("users", "mfa_failed_attempts")
    op.drop_column("users", "mfa_pending_jti")
    op.drop_column("users", "mfa_last_used_step")
