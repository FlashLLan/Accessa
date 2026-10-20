"""trim statuses and review action types, merge PR/MR url, users NOT NULL

- change_requests.status: ESCALATED, DELEGATED, CLOSED and CANCELLED are removed
  (escalation and delegation are review actions, not statuses). The enum is
  VARCHAR + CHECK (native_enum=False), so the CHECK constraint is replaced.
- review_actions.action_type: only ESCALATE and DELEGATE remain (CHECK replaced,
  column narrowed to VARCHAR(8)); from_status and to_status are dropped;
  target_reviewer_id becomes NOT NULL (every escalation/delegation has a target).
- git_context: merge_request_url is merged into pull_request_url and dropped.
- users: is_active, created_at and updated_at become NOT NULL, after a backfill.

The upgrade refuses to run if existing rows would lose meaning (a request in a
removed status, a review action of a removed type or without a target, or a Git
context with two different URLs) instead of guessing a mapping.

Revision ID: c5ee582f5a9e
Revises: 5d4a194aa17b
Create Date: 2026-10-21 00:06:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c5ee582f5a9e'
down_revision: Union[str, Sequence[str], None] = '5d4a194aa17b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STATUSES = ["DRAFT", "PENDING_REVIEW", "APPROVED", "REJECTED", "APPLIED"]
OLD_STATUSES = STATUSES + ["ESCALATED", "DELEGATED", "CLOSED", "CANCELLED"]
ACTION_TYPES = ["DELEGATE", "ESCALATE"]
OLD_ACTION_TYPES = [
    "APPROVE", "REJECT", "DELEGATE", "ESCALATE", "COMMENT", "ASSIGN", "RETURN_FOR_CHANGES", "START_REVIEW",
]


def _in_list(column: str, values: list[str]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _refuse_if(sql_count: str, message: str) -> None:
    op.execute(f"""
        DO $$
        DECLARE n bigint;
        BEGIN
            SELECT ({sql_count}) INTO n;
            IF n > 0 THEN
                RAISE EXCEPTION '%: % row(s). Resolve them before upgrading.', '{message}', n;
            END IF;
        END
        $$;
    """)


def upgrade() -> None:
    # --- preconditions: never silently re-map or lose data ---------------------
    _refuse_if(
        f"SELECT count(*) FROM change_requests WHERE NOT {_in_list('status', STATUSES)}",
        "change_requests with a removed status (ESCALATED/DELEGATED/CLOSED/CANCELLED)",
    )
    _refuse_if(
        f"SELECT count(*) FROM review_actions WHERE NOT {_in_list('action_type', ACTION_TYPES)}",
        "review_actions with a removed action type",
    )
    _refuse_if(
        "SELECT count(*) FROM review_actions WHERE target_reviewer_id IS NULL",
        "review_actions without target_reviewer_id",
    )
    _refuse_if(
        "SELECT count(*) FROM git_context WHERE pull_request_url IS NOT NULL "
        "AND merge_request_url IS NOT NULL AND pull_request_url <> merge_request_url",
        "git_context rows with different pull_request_url and merge_request_url",
    )

    # --- change_requests.status ------------------------------------------------
    op.drop_constraint(op.f("ck_change_requests_request_status"), "change_requests", type_="check")
    op.create_check_constraint(op.f("ck_change_requests_request_status"), "change_requests", _in_list("status", STATUSES))

    # --- review_actions ----------------------------------------------------------
    op.drop_constraint(op.f("ck_review_actions_review_action_type"), "review_actions", type_="check")
    op.alter_column(
        "review_actions", "action_type",
        existing_type=sa.String(length=18), type_=sa.String(length=8), existing_nullable=False,
    )
    op.create_check_constraint(
        op.f("ck_review_actions_review_action_type"), "review_actions", _in_list("action_type", ACTION_TYPES)
    )
    op.drop_column("review_actions", "from_status")
    op.drop_column("review_actions", "to_status")
    op.alter_column("review_actions", "target_reviewer_id", existing_type=sa.Integer(), nullable=False)

    # --- git_context: one URL column for pull and merge requests ----------------
    op.execute(
        "UPDATE git_context SET pull_request_url = merge_request_url "
        "WHERE pull_request_url IS NULL AND merge_request_url IS NOT NULL"
    )
    op.drop_column("git_context", "merge_request_url")

    # --- users: backfill, then NOT NULL ----------------------------------------
    # A NULL is_active is treated as inactive by the application today (login and
    # get_current_user check `not user.is_active`), so it is backfilled as false to
    # keep those accounts exactly as locked as they are now.
    op.execute("UPDATE users SET is_active = false WHERE is_active IS NULL")
    op.execute("UPDATE users SET created_at = COALESCE(updated_at, now()) WHERE created_at IS NULL")
    op.execute("UPDATE users SET updated_at = created_at WHERE updated_at IS NULL")
    op.alter_column("users", "is_active", existing_type=sa.Boolean(), nullable=False, server_default=sa.text("true"))
    op.alter_column(
        "users", "created_at", existing_type=sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
    )
    op.alter_column(
        "users", "updated_at", existing_type=sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
    )


def downgrade() -> None:
    op.alter_column("users", "updated_at", existing_type=sa.DateTime(timezone=True), nullable=True, server_default=None)
    op.alter_column("users", "created_at", existing_type=sa.DateTime(timezone=True), nullable=True, server_default=None)
    op.alter_column("users", "is_active", existing_type=sa.Boolean(), nullable=True, server_default=None)

    # The merged URLs stay in pull_request_url; merge_request_url comes back empty.
    op.add_column("git_context", sa.Column("merge_request_url", sa.Text(), nullable=True))

    op.alter_column("review_actions", "target_reviewer_id", existing_type=sa.Integer(), nullable=True)
    op.add_column("review_actions", sa.Column("to_status", sa.Text(), nullable=True))
    op.add_column("review_actions", sa.Column("from_status", sa.Text(), nullable=True))
    op.drop_constraint(op.f("ck_review_actions_review_action_type"), "review_actions", type_="check")
    op.alter_column(
        "review_actions", "action_type",
        existing_type=sa.String(length=8), type_=sa.String(length=18), existing_nullable=False,
    )
    op.create_check_constraint(
        op.f("ck_review_actions_review_action_type"), "review_actions", _in_list("action_type", OLD_ACTION_TYPES)
    )

    op.drop_constraint(op.f("ck_change_requests_request_status"), "change_requests", type_="check")
    op.create_check_constraint(
        op.f("ck_change_requests_request_status"), "change_requests", _in_list("status", OLD_STATUSES)
    )
