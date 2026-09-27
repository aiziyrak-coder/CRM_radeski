"""campaign: description and cached AI summary

Revision ID: c7a4e9d2b813
Revises: 5b8e1d2c4f60
Create Date: 2026-09-27 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c7a4e9d2b813"
down_revision: str | None = "5b8e1d2c4f60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("campaigns", sa.Column("description", sa.Text(), nullable=True))
    op.add_column(
        "campaigns",
        sa.Column("ai_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "campaigns", sa.Column("ai_summary_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("campaigns", "ai_summary_at")
    op.drop_column("campaigns", "ai_summary")
    op.drop_column("campaigns", "description")
