"""messaging_telephony_idempotency

Revision ID: 8269a4f0f9fa
Revises: a3c1e7f9b2d4
Create Date: 2026-09-26 23:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8269a4f0f9fa"
down_revision: str | None = "a3c1e7f9b2d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # messages: claim time of the sender worker; provider ids stored once per chat and direction
    op.add_column("messages", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))
    # webhook retries stored before this revision: keep the rows, drop the repeated provider id
    op.execute(
        """
        UPDATE messages SET external_id = NULL
        WHERE id IN (
            SELECT id FROM (
                SELECT id, row_number() OVER (
                    PARTITION BY conversation_id, direction, external_id ORDER BY created_at, id
                ) AS n
                FROM messages WHERE external_id IS NOT NULL
            ) dup
            WHERE dup.n > 1
        )
        """
    )
    # Telegram Business message ids are now stored with a "b" prefix (the bot chat and the
    # business chat share one conversation and their numbers can collide); older incoming
    # messages of business chats get it too, so a new bot message isn't taken for a repeat
    op.execute(
        """
        UPDATE messages m SET external_id = 'b' || m.external_id
        FROM conversations c
        WHERE m.conversation_id = c.id
          AND c.channel = 'telegram' AND c.business_connection_id IS NOT NULL
          AND m.direction = 'in' AND m.external_id IS NOT NULL
          AND m.external_id NOT LIKE 'b%'
        """
    )
    op.create_index(
        "uq_messages_external",
        "messages",
        ["conversation_id", "direction", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )

    # calls: phone is E.164 only; whatever the PBX reported is kept in caller_raw
    op.add_column("calls", sa.Column("caller_raw", sa.String(length=64), nullable=True))
    op.execute("UPDATE calls SET caller_raw = phone WHERE phone IS NOT NULL")
    op.execute("UPDATE calls SET phone = NULL WHERE phone !~ '^\\+998[1-9][0-9]{8}$'")


def downgrade() -> None:
    op.execute("UPDATE calls SET phone = left(caller_raw, 32) WHERE phone IS NULL")
    op.drop_column("calls", "caller_raw")
    op.drop_index("uq_messages_external", table_name="messages")
    op.drop_column("messages", "claimed_at")
