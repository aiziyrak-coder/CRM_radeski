"""campaign_ab

Revision ID: 8d57a4c3d0d7
Revises: d7f3593cfa27
Create Date: 2026-09-26 22:27:57.825919
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "8d57a4c3d0d7"
down_revision: str | None = "d7f3593cfa27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("campaigns", sa.Column("script_code_b", sa.String(length=30), nullable=True))


def downgrade() -> None:
    op.drop_column("campaigns", "script_code_b")
