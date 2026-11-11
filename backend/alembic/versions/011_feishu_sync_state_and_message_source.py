"""feishu_sync_state and feishu_message_events.source for history sync

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-03-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "feishu_message_events",
        sa.Column(
            "source",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'webhook'"),
        ),
    )
    op.create_index(
        op.f("ix_feishu_message_events_source"),
        "feishu_message_events",
        ["source"],
        unique=False,
    )

    op.create_table(
        "feishu_sync_state",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("bound_user_id", sa.Integer(), nullable=False),
        sa.Column("tenant_key", sa.String(length=128), nullable=True),
        sa.Column("open_id", sa.String(length=128), nullable=True),
        sa.Column("chat_id", sa.String(length=128), nullable=True),
        sa.Column(
            "channel_type",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'feishu_private'"),
        ),
        sa.Column("last_synced_message_id", sa.String(length=128), nullable=True),
        sa.Column("last_synced_message_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_processed_message_id", sa.String(length=128), nullable=True),
        sa.Column("last_processed_message_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["bound_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_feishu_sync_state_bound_user_id"),
        "feishu_sync_state",
        ["bound_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_feishu_sync_state_tenant_key"),
        "feishu_sync_state",
        ["tenant_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_feishu_sync_state_open_id"),
        "feishu_sync_state",
        ["open_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_feishu_sync_state_chat_id"),
        "feishu_sync_state",
        ["chat_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_feishu_sync_state_channel_type"),
        "feishu_sync_state",
        ["channel_type"],
        unique=False,
    )
    op.create_index(
        "ix_feishu_sync_state_bound_chat",
        "feishu_sync_state",
        ["bound_user_id", "chat_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_feishu_sync_state_bound_chat", table_name="feishu_sync_state")
    op.drop_index(op.f("ix_feishu_sync_state_channel_type"), table_name="feishu_sync_state")
    op.drop_index(op.f("ix_feishu_sync_state_chat_id"), table_name="feishu_sync_state")
    op.drop_index(op.f("ix_feishu_sync_state_open_id"), table_name="feishu_sync_state")
    op.drop_index(op.f("ix_feishu_sync_state_tenant_key"), table_name="feishu_sync_state")
    op.drop_index(op.f("ix_feishu_sync_state_bound_user_id"), table_name="feishu_sync_state")
    op.drop_table("feishu_sync_state")

    op.drop_index(op.f("ix_feishu_message_events_source"), table_name="feishu_message_events")
    op.drop_column("feishu_message_events", "source")
