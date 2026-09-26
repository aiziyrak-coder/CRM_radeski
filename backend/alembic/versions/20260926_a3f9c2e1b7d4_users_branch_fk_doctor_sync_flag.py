"""users branch fk, doctor sync flag

Revision ID: a3f9c2e1b7d4
Revises: 8269a4f0f9fa
Create Date: 2026-09-26 23:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "a3f9c2e1b7d4"
down_revision: str | None = "8269a4f0f9fa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "doctors",
        sa.Column("deactivated_by_sync", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # branch ids were never validated before; drop dangling ones so the FK can be created
    op.execute(
        "UPDATE users SET branch_id = NULL "
        "WHERE branch_id IS NOT NULL AND branch_id NOT IN (SELECT id FROM branches)"
    )
    op.create_foreign_key(
        "users_branch_id_fkey", "users", "branches", ["branch_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint("users_branch_id_fkey", "users", type_="foreignkey")
    op.drop_column("doctors", "deactivated_by_sync")
