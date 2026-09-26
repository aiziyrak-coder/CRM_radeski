"""telephony

Revision ID: bce488780a7b
Revises: 9327585693d6
Create Date: 2026-09-26 21:03:11.876507
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "bce488780a7b"
down_revision: str | None = "9327585693d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "calls",
        sa.Column("pbx_id", sa.String(length=64), nullable=False),
        sa.Column(
            "direction",
            sa.Enum("in", "out", name="calldirection", native_enum=False, length=5),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "ringing",
                "answered",
                "missed",
                "abandoned",
                "after_hours",
                "no_answer",
                "busy",
                "failed",
                name="callstatus",
                native_enum=False,
                length=15,
            ),
            nullable=False,
        ),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("patient_id", sa.Uuid(), nullable=True),
        sa.Column("lead_id", sa.Uuid(), nullable=True),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("extension", sa.String(length=10), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("wait_seconds", sa.Integer(), nullable=True),
        sa.Column("talk_seconds", sa.Integer(), nullable=True),
        sa.Column("callback_requested", sa.Boolean(), nullable=False),
        sa.Column("recording", sa.String(length=100), nullable=True),
        sa.Column(
            "recording_status",
            sa.Enum(
                "pending",
                "ready",
                "missing",
                "failed",
                name="recordingstatus",
                native_enum=False,
                length=10,
            ),
            nullable=True,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.id"],
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pbx_id"),
    )
    op.create_index(op.f("ix_calls_direction"), "calls", ["direction"], unique=False)
    op.create_index(op.f("ix_calls_patient_id"), "calls", ["patient_id"], unique=False)
    op.create_index(op.f("ix_calls_phone"), "calls", ["phone"], unique=False)
    op.create_index(op.f("ix_calls_started_at"), "calls", ["started_at"], unique=False)
    op.create_index(op.f("ix_calls_status"), "calls", ["status"], unique=False)
    op.create_index(op.f("ix_calls_user_id"), "calls", ["user_id"], unique=False)
    op.add_column("users", sa.Column("sip_extension", sa.String(length=10), nullable=True))
    op.create_unique_constraint("users_sip_extension_key", "users", ["sip_extension"])


def downgrade() -> None:
    op.drop_constraint("users_sip_extension_key", "users", type_="unique")
    op.drop_column("users", "sip_extension")
    op.drop_index(op.f("ix_calls_user_id"), table_name="calls")
    op.drop_index(op.f("ix_calls_status"), table_name="calls")
    op.drop_index(op.f("ix_calls_started_at"), table_name="calls")
    op.drop_index(op.f("ix_calls_phone"), table_name="calls")
    op.drop_index(op.f("ix_calls_patient_id"), table_name="calls")
    op.drop_index(op.f("ix_calls_direction"), table_name="calls")
    op.drop_table("calls")
