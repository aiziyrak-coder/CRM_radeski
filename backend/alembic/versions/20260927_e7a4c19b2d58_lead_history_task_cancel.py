"""lead stage history, task cancel reason, patient tags index

Revision ID: e7a4c19b2d58
Revises: c4d2a8e6f1b3
Create Date: 2026-09-27 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "e7a4c19b2d58"
down_revision: str | None = "c4d2a8e6f1b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lead_stage_changes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("old_stage", sa.String(length=10), nullable=True),
        sa.Column("new_stage", sa.String(length=10), nullable=False),
        sa.Column("reason", sa.String(length=50), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lead_stage_changes_lead_id", "lead_stage_changes", ["lead_id"])
    op.create_index("ix_lead_stage_changes_created_at", "lead_stage_changes", ["created_at"])
    # existing inquiries start their history with their current stage
    op.execute(
        "INSERT INTO lead_stage_changes (id, lead_id, old_stage, new_stage, reason, user_id, "
        "created_at) SELECT gen_random_uuid(), id, NULL, stage, lost_reason, created_by, "
        "created_at FROM leads"
    )

    op.add_column("tasks", sa.Column("cancel_reason", sa.String(length=255), nullable=True))
    op.create_index("ix_patients_tags", "patients", ["tags"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_index("ix_patients_tags", table_name="patients")
    op.drop_column("tasks", "cancel_reason")
    op.drop_index("ix_lead_stage_changes_created_at", table_name="lead_stage_changes")
    op.drop_index("ix_lead_stage_changes_lead_id", table_name="lead_stage_changes")
    op.drop_table("lead_stage_changes")
