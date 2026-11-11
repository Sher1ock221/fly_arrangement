"""feishu offline compensation db closure

- feishu_message_events: add next_retry_at for offline replay scheduling
- feishu_sync_state: allow bound_user_id nullable and change unique scope to (chat_id, channel_type)

Revision ID: f18c0dbcl018
Revises: e6f7a8b9c0d1
Create Date: 2026-03-18
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f18c0dbcl018"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    def _index_exists(name: str) -> bool:
        return bool(
            bind.execute(
                sa.text(
                    "select 1 from pg_indexes where schemaname='public' and indexname=:n limit 1"
                ),
                {"n": name},
            ).first()
        )

    def _column_exists(table: str, column: str) -> bool:
        return bool(
            bind.execute(
                sa.text(
                    "select 1 from information_schema.columns where table_schema='public' and table_name=:t and column_name=:c limit 1"
                ),
                {"t": table, "c": column},
            ).first()
        )

    # 1) feishu_message_events.next_retry_at
    if not _column_exists("feishu_message_events", "next_retry_at"):
        op.add_column(
            "feishu_message_events",
            sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        )
    if not _index_exists("ix_feishu_message_events_next_retry_at"):
        op.create_index(
            "ix_feishu_message_events_next_retry_at",
            "feishu_message_events",
            ["next_retry_at"],
            unique=False,
        )

    # 2) feishu_sync_state.bound_user_id nullable (for unbound chat watermarks)
    op.alter_column(
        "feishu_sync_state",
        "bound_user_id",
        existing_type=sa.Integer(),
        nullable=True,
    )

    # 3) unique scope change: drop old unique index and create new one
    if _index_exists("uq_feishu_sync_state_bound_chat_channel"):
        op.drop_index("uq_feishu_sync_state_bound_chat_channel", table_name="feishu_sync_state")
    if not _index_exists("uq_feishu_sync_state_chat_channel"):
        op.create_index(
            "uq_feishu_sync_state_chat_channel",
            "feishu_sync_state",
            ["chat_id", "channel_type"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()

    def _index_exists(name: str) -> bool:
        return bool(
            bind.execute(
                sa.text(
                    "select 1 from pg_indexes where schemaname='public' and indexname=:n limit 1"
                ),
                {"n": name},
            ).first()
        )

    def _column_exists(table: str, column: str) -> bool:
        return bool(
            bind.execute(
                sa.text(
                    "select 1 from information_schema.columns where table_schema='public' and table_name=:t and column_name=:c limit 1"
                ),
                {"t": table, "c": column},
            ).first()
        )

    # revert unique scope
    if _index_exists("uq_feishu_sync_state_chat_channel"):
        op.drop_index("uq_feishu_sync_state_chat_channel", table_name="feishu_sync_state")
    if not _index_exists("uq_feishu_sync_state_bound_chat_channel"):
        op.create_index(
            "uq_feishu_sync_state_bound_chat_channel",
            "feishu_sync_state",
            ["bound_user_id", "chat_id", "channel_type"],
            unique=True,
        )

    # bound_user_id back to non-null
    op.alter_column(
        "feishu_sync_state",
        "bound_user_id",
        existing_type=sa.Integer(),
        nullable=False,
    )

    # drop next_retry_at
    if _index_exists("ix_feishu_message_events_next_retry_at"):
        op.drop_index("ix_feishu_message_events_next_retry_at", table_name="feishu_message_events")
    if _column_exists("feishu_message_events", "next_retry_at"):
        op.drop_column("feishu_message_events", "next_retry_at")

