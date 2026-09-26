"""task_rule_fixes

Revision ID: a3c1e7f9b2d4
Revises: 8d57a4c3d0d7
Create Date: 2026-09-26 23:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "a3c1e7f9b2d4"
down_revision: str | None = "8d57a4c3d0d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("no_answer_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "task_attempts",
        sa.Column("automatic", sa.Boolean(), server_default="false", nullable=False),
    )
    # open tasks continue their retry ladder: unanswered attempts since the last answered one
    op.execute(
        """
        UPDATE tasks t SET no_answer_count = sub.n
        FROM (
            SELECT a.task_id, count(*) AS n
            FROM task_attempts a
            WHERE a.outcome = 'no_answer'
              AND a.created_at > coalesce(
                  (SELECT max(b.created_at) FROM task_attempts b
                   WHERE b.task_id = a.task_id AND b.outcome <> 'no_answer'),
                  '-infinity'::timestamptz)
            GROUP BY a.task_id
        ) sub
        WHERE t.id = sub.task_id AND t.status = 'open'
        """
    )
    # TZ 4.5: today's confirmations come first (priority 10 -> 4)
    op.execute(
        "UPDATE tasks SET priority = 4 "
        "WHERE type = 'confirm_visit' AND status = 'open' AND priority = 10"
    )
    # campaigns without a script were always called with the default one; store it explicitly
    op.execute("UPDATE campaigns SET script_code = 'reactivation' WHERE script_code IS NULL")


def downgrade() -> None:
    op.execute(
        "UPDATE tasks SET priority = 10 "
        "WHERE type = 'confirm_visit' AND status = 'open' AND priority = 4"
    )
    op.drop_column("task_attempts", "automatic")
    op.drop_column("tasks", "no_answer_count")
