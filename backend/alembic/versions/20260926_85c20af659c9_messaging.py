"""messaging

Revision ID: 85c20af659c9
Revises: 5fd813a39caa
Create Date: 2026-09-26 21:59:39.610742
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "85c20af659c9"
down_revision: str | None = "5fd813a39caa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "message_templates",
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("language", sa.String(length=5), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", "language"),
    )
    op.create_table(
        "conversations",
        sa.Column(
            "channel",
            sa.Enum("telegram", "instagram", "sms", name="channel", native_enum=False, length=10),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=16), nullable=True),
        sa.Column("patient_id", sa.Uuid(), nullable=True),
        sa.Column("lead_id", sa.Uuid(), nullable=True),
        sa.Column("business_connection_id", sa.String(length=64), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unread", sa.Integer(), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("channel", "external_id"),
    )
    op.create_index(op.f("ix_conversations_channel"), "conversations", ["channel"], unique=False)
    op.create_index(
        op.f("ix_conversations_last_message_at"), "conversations", ["last_message_at"], unique=False
    )
    op.create_index(
        op.f("ix_conversations_patient_id"), "conversations", ["patient_id"], unique=False
    )
    op.create_table(
        "messages",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column(
            "direction",
            sa.Enum("in", "out", name="direction", native_enum=False, length=5),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "received",
                "queued",
                "sent",
                "delivered",
                "failed",
                name="messagestatus",
                native_enum=False,
                length=10,
            ),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(length=100), nullable=True),
        sa.Column("template_code", sa.String(length=40), nullable=True),
        sa.Column("ai_draft", sa.Boolean(), nullable=False),
        sa.Column("sent_by", sa.Uuid(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=100), nullable=True),
        sa.Column("send_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["sent_by"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key"),
    )
    op.create_index(
        op.f("ix_messages_conversation_id"), "messages", ["conversation_id"], unique=False
    )
    op.create_index(op.f("ix_messages_external_id"), "messages", ["external_id"], unique=False)
    op.create_index(op.f("ix_messages_status"), "messages", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_messages_status"), table_name="messages")
    op.drop_index(op.f("ix_messages_external_id"), table_name="messages")
    op.drop_index(op.f("ix_messages_conversation_id"), table_name="messages")
    op.drop_table("messages")
    op.drop_index(op.f("ix_conversations_patient_id"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_last_message_at"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_channel"), table_name="conversations")
    op.drop_table("conversations")
    op.drop_table("message_templates")
