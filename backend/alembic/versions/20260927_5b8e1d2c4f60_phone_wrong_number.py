"""patient phone: wrong number flag

Revision ID: 5b8e1d2c4f60
Revises: a3f9c2e1b7d4
Create Date: 2026-09-27 10:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "5b8e1d2c4f60"
down_revision: str | None = "a3f9c2e1b7d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "patient_phones", sa.Column("wrong_number_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("patient_phones", "wrong_number_at")
