"""ai_analysis

Revision ID: 5fd813a39caa
Revises: bce488780a7b
Create Date: 2026-09-26 21:36:20.232699
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "5fd813a39caa"
down_revision: str | None = "bce488780a7b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_digests",
        sa.Column("period_from", sa.Date(), nullable=False),
        sa.Column("period_to", sa.Date(), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "qa_criteria",
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name_uz", sa.String(length=255), nullable=False),
        sa.Column("name_ru", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "call_analyses",
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "transcribing",
                "analyzing",
                "ready",
                "failed",
                "skipped",
                name="analysisstatus",
                native_enum=False,
                length=15,
            ),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("stt_model", sa.String(length=64), nullable=True),
        sa.Column("llm_model", sa.String(length=64), nullable=True),
        sa.Column("prompt_version", sa.String(length=20), nullable=True),
        sa.Column("transcript", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("language", sa.String(length=10), nullable=True),
        sa.Column("conversation_type", sa.String(length=30), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("criteria", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("violations", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("red_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("has_red_flags", sa.Boolean(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("suggested_outcome", sa.String(length=20), nullable=True),
        sa.Column("suggested_reason", sa.String(length=50), nullable=True),
        sa.Column("extracted", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("questions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("objections", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "review",
            sa.Enum("confirmed", "corrected", name="reviewstatus", native_enum=False, length=10),
            nullable=True,
        ),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("corrections", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("flags_reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("flags_reviewed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["call_id"], ["calls.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["flags_reviewed_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("call_id"),
    )
    op.create_index(
        op.f("ix_call_analyses_has_red_flags"), "call_analyses", ["has_red_flags"], unique=False
    )
    op.create_index(op.f("ix_call_analyses_score"), "call_analyses", ["score"], unique=False)
    op.create_index(op.f("ix_call_analyses_status"), "call_analyses", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_call_analyses_status"), table_name="call_analyses")
    op.drop_index(op.f("ix_call_analyses_score"), table_name="call_analyses")
    op.drop_index(op.f("ix_call_analyses_has_red_flags"), table_name="call_analyses")
    op.drop_table("call_analyses")
    op.drop_table("qa_criteria")
    op.drop_table("ai_digests")
