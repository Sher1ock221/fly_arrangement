"""add feishu tables and chat/audit fields

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feishu_users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("open_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=True),
        sa.Column("union_id", sa.String(length=128), nullable=True),
        sa.Column("name", sa.String(length=256), nullable=True),
        sa.Column("avatar_url", sa.String(length=1024), nullable=True),
        sa.Column("tenant_key", sa.String(length=128), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_feishu_users_open_id"), "feishu_users", ["open_id"], unique=True)
    op.create_index(op.f("ix_feishu_users_user_id"), "feishu_users", ["user_id"], unique=False)
    op.create_index(op.f("ix_feishu_users_union_id"), "feishu_users", ["union_id"], unique=False)

    op.create_table(
        "feishu_conversations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("feishu_open_id", sa.String(length=128), nullable=False),
        sa.Column("feishu_chat_id", sa.String(length=128), nullable=True),
        sa.Column("conversation_type", sa.String(length=32), nullable=False),
        sa.Column("source_conversation_id", sa.Integer(), nullable=True),
        sa.Column("last_message_id", sa.String(length=128), nullable=True),
        sa.Column("title", sa.String(length=256), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["source_conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_feishu_conversations_feishu_open_id"), "feishu_conversations", ["feishu_open_id"], unique=False)
    op.create_index(op.f("ix_feishu_conversations_feishu_chat_id"), "feishu_conversations", ["feishu_chat_id"], unique=False)
    op.create_index(op.f("ix_feishu_conversations_conversation_type"), "feishu_conversations", ["conversation_type"], unique=False)
    op.create_index(op.f("ix_feishu_conversations_source_conversation_id"), "feishu_conversations", ["source_conversation_id"], unique=False)
    op.create_index(
        "uq_feishu_conversations_p2p",
        "feishu_conversations",
        ["feishu_open_id", "conversation_type"],
        unique=True,
        postgresql_where=sa.text("conversation_type = 'p2p'"),
    )
    op.create_index(
        "uq_feishu_conversations_group_user",
        "feishu_conversations",
        ["feishu_chat_id", "feishu_open_id", "conversation_type"],
        unique=True,
        postgresql_where=sa.text("conversation_type = 'group_at'"),
    )

    op.create_table(
        "feishu_message_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=True),
        sa.Column("message_id", sa.String(length=128), nullable=True),
        sa.Column("chat_id", sa.String(length=128), nullable=True),
        sa.Column("open_id", sa.String(length=128), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("message_type", sa.String(length=32), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("process_status", sa.String(length=32), nullable=False, server_default=sa.text("'received'")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("response_message_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_feishu_message_events_event_id"), "feishu_message_events", ["event_id"], unique=True)
    op.create_index(op.f("ix_feishu_message_events_message_id"), "feishu_message_events", ["message_id"], unique=True)
    op.create_index(op.f("ix_feishu_message_events_chat_id"), "feishu_message_events", ["chat_id"], unique=False)
    op.create_index(op.f("ix_feishu_message_events_open_id"), "feishu_message_events", ["open_id"], unique=False)
    op.create_index(op.f("ix_feishu_message_events_process_status"), "feishu_message_events", ["process_status"], unique=False)

    op.create_table(
        "feishu_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("token_type", sa.String(length=64), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("expire_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_feishu_tokens_token_type"), "feishu_tokens", ["token_type"], unique=True)
    op.create_index(op.f("ix_feishu_tokens_expire_at"), "feishu_tokens", ["expire_at"], unique=False)

    op.add_column("chat_records", sa.Column("channel", sa.String(length=32), nullable=False, server_default=sa.text("'web'")))
    op.add_column("chat_records", sa.Column("external_user_id", sa.String(length=128), nullable=True))
    op.add_column("chat_records", sa.Column("external_chat_id", sa.String(length=128), nullable=True))
    op.add_column("chat_records", sa.Column("source_conversation_id", sa.Integer(), nullable=True))
    op.add_column("chat_records", sa.Column("external_message_id", sa.String(length=128), nullable=True))
    op.create_foreign_key(
        "fk_chat_records_source_conversation_id_conversations",
        "chat_records",
        "conversations",
        ["source_conversation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_chat_records_channel"), "chat_records", ["channel"], unique=False)
    op.create_index(op.f("ix_chat_records_external_user_id"), "chat_records", ["external_user_id"], unique=False)
    op.create_index(op.f("ix_chat_records_external_chat_id"), "chat_records", ["external_chat_id"], unique=False)
    op.create_index(op.f("ix_chat_records_source_conversation_id"), "chat_records", ["source_conversation_id"], unique=False)
    op.create_index(op.f("ix_chat_records_external_message_id"), "chat_records", ["external_message_id"], unique=False)

    op.add_column("audit_logs", sa.Column("operator_source", sa.String(length=32), nullable=False, server_default=sa.text("'system'")))
    op.add_column("audit_logs", sa.Column("operator_external_id", sa.String(length=128), nullable=True))
    op.create_index(op.f("ix_audit_logs_operator_external_id"), "audit_logs", ["operator_external_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_logs_operator_external_id"), table_name="audit_logs")
    op.drop_column("audit_logs", "operator_external_id")
    op.drop_column("audit_logs", "operator_source")

    op.drop_index(op.f("ix_chat_records_external_message_id"), table_name="chat_records")
    op.drop_index(op.f("ix_chat_records_source_conversation_id"), table_name="chat_records")
    op.drop_index(op.f("ix_chat_records_external_chat_id"), table_name="chat_records")
    op.drop_index(op.f("ix_chat_records_external_user_id"), table_name="chat_records")
    op.drop_index(op.f("ix_chat_records_channel"), table_name="chat_records")
    op.drop_constraint(
        "fk_chat_records_source_conversation_id_conversations",
        "chat_records",
        type_="foreignkey",
    )
    op.drop_column("chat_records", "external_message_id")
    op.drop_column("chat_records", "source_conversation_id")
    op.drop_column("chat_records", "external_chat_id")
    op.drop_column("chat_records", "external_user_id")
    op.drop_column("chat_records", "channel")

    op.drop_index(op.f("ix_feishu_tokens_expire_at"), table_name="feishu_tokens")
    op.drop_index(op.f("ix_feishu_tokens_token_type"), table_name="feishu_tokens")
    op.drop_table("feishu_tokens")

    op.drop_index(op.f("ix_feishu_message_events_process_status"), table_name="feishu_message_events")
    op.drop_index(op.f("ix_feishu_message_events_open_id"), table_name="feishu_message_events")
    op.drop_index(op.f("ix_feishu_message_events_chat_id"), table_name="feishu_message_events")
    op.drop_index(op.f("ix_feishu_message_events_message_id"), table_name="feishu_message_events")
    op.drop_index(op.f("ix_feishu_message_events_event_id"), table_name="feishu_message_events")
    op.drop_table("feishu_message_events")

    op.drop_index("uq_feishu_conversations_group_user", table_name="feishu_conversations")
    op.drop_index("uq_feishu_conversations_p2p", table_name="feishu_conversations")
    op.drop_index(op.f("ix_feishu_conversations_source_conversation_id"), table_name="feishu_conversations")
    op.drop_index(op.f("ix_feishu_conversations_conversation_type"), table_name="feishu_conversations")
    op.drop_index(op.f("ix_feishu_conversations_feishu_chat_id"), table_name="feishu_conversations")
    op.drop_index(op.f("ix_feishu_conversations_feishu_open_id"), table_name="feishu_conversations")
    op.drop_table("feishu_conversations")

    op.drop_index(op.f("ix_feishu_users_union_id"), table_name="feishu_users")
    op.drop_index(op.f("ix_feishu_users_user_id"), table_name="feishu_users")
    op.drop_index(op.f("ix_feishu_users_open_id"), table_name="feishu_users")
    op.drop_table("feishu_users")
