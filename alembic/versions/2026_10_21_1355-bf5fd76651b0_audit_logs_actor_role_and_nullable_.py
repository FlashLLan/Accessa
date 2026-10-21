"""audit_logs actor_role and nullable entity_id

- actor_role: the acting user's role name at the moment of the action, so an
  entry keeps the role the actor had then, even after a later role change.
  NULL when there is no known actor (failed login with an unknown email).
- entity_id becomes nullable: workspace events no longer store the workspace's
  internal integer id; they identify the workspace by slug/public_id in details.

Existing audit rows are not updated: actor_role stays NULL for them.

Revision ID: bf5fd76651b0
Revises: 499a060623b0
Create Date: 2026-10-21 13:55:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'bf5fd76651b0'
down_revision: Union[str, Sequence[str], None] = '499a060623b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("actor_role", sa.String(), nullable=True))
    op.alter_column("audit_logs", "entity_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    # entity_id was NOT NULL before; workspace events written since have none.
    op.execute("UPDATE audit_logs SET entity_id = 0 WHERE entity_id IS NULL")
    op.alter_column("audit_logs", "entity_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("audit_logs", "actor_role")
