"""user_totp

Revision ID: d7f3593cfa27
Revises: 85c20af659c9
Create Date: 2026-09-26 22:16:41.618719
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "d7f3593cfa27"
down_revision: str | None = "85c20af659c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("totp_secret", sa.String(length=64), nullable=True))
    op.add_column(
        "users",
        # existing users start without 2FA; admins enrol at their next login
        sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("users", sa.Column("totp_last_step", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "totp_last_step")
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret")
