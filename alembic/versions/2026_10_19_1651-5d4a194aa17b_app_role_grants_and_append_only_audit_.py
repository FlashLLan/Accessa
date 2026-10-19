"""app role grants and append-only audit_logs

Privileges of the application role (accessa_app) are set explicitly here, so a
fresh database always ends up in the same state no matter how the role's
default privileges were configured:

- SELECT, INSERT, UPDATE, DELETE on every application table, USAGE/SELECT on
  every sequence;
- audit_logs is append-only: UPDATE, DELETE and TRUNCATE are revoked, leaving
  only SELECT and INSERT, so the application can never rewrite or erase audit
  history;
- no access at all to alembic_version.

The migration fails if accessa_app does not exist, instead of silently leaving
audit_logs writable.

Revision ID: 5d4a194aa17b
Revises: c136c4ce0221
Create Date: 2026-10-19 16:51:59.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '5d4a194aa17b'
down_revision: Union[str, Sequence[str], None] = 'c136c4ce0221'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APP_ROLE = "accessa_app"


def upgrade() -> None:
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                RAISE EXCEPTION 'Role {APP_ROLE} does not exist. Create it first '
                    '(docker/postgres/init/01-roles.sh) so audit_logs can be made append-only.';
            END IF;
        END
        $$;
    """)

    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")

    # Append-only audit log: explicit revoke, not reliance on the grants above.
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON audit_logs FROM {APP_ROLE}")

    # The application never needs to read or change migration state.
    op.execute(f"REVOKE ALL ON alembic_version FROM {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"GRANT UPDATE, DELETE ON audit_logs TO {APP_ROLE}")
