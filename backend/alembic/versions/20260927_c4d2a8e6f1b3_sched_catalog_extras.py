"""scheduling/catalog: absence kind, confirmed service duration, catalog sync runs

Revision ID: c4d2a8e6f1b3
Revises: c7a4e9d2b813
Create Date: 2026-09-27 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4d2a8e6f1b3"
down_revision: str | None = "c7a4e9d2b813"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "doctor_absences",
        sa.Column("kind", sa.String(length=10), server_default="other", nullable=False),
    )
    op.add_column(
        "services",
        sa.Column(
            "duration_confirmed", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    # a duration that differs from the sync's 30-minute placeholder, or one an admin saved
    # (audit log), was set on purpose
    op.execute(
        """
        UPDATE services SET duration_confirmed = true
        WHERE duration_min <> 30
           OR id::text IN (
               SELECT entity_id FROM audit_log
               WHERE action = 'catalog.service' AND after ? 'duration_min'
           )
        """
    )
    op.create_table(
        "catalog_sync_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trigger", sa.String(length=10), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("counts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_catalog_sync_runs_started_at"), "catalog_sync_runs", ["started_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_catalog_sync_runs_started_at"), table_name="catalog_sync_runs")
    op.drop_table("catalog_sync_runs")
    op.drop_column("services", "duration_confirmed")
    op.drop_column("doctor_absences", "kind")
