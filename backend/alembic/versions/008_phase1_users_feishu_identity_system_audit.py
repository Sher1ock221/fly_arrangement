"""phase1: users, feishu_identity_pool, system_audit_logs

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-03-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=256), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False, server_default=sa.text("'user'")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)
    op.create_index(op.f("ix_users_role"), "users", ["role"], unique=False)

    op.create_table(
        "feishu_identity_pool",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_key", sa.String(length=128), nullable=True),
        sa.Column("open_id", sa.String(length=128), nullable=True),
        sa.Column("union_id", sa.String(length=128), nullable=True),
        sa.Column("feishu_user_id", sa.String(length=128), nullable=True),
        sa.Column("chat_id", sa.String(length=128), nullable=True),
        sa.Column("message_id", sa.String(length=128), nullable=True),
        sa.Column("sender_name", sa.String(length=256), nullable=True),
        sa.Column("raw_payload", sa.dialects.postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event_id", sa.String(length=128), nullable=True),
        sa.Column("bind_status", sa.String(length=32), nullable=False, server_default=sa.text("'unbound'")),
        sa.Column("bound_user_id", sa.Integer(), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["bound_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_feishu_identity_pool_tenant_open"), "feishu_identity_pool", ["tenant_key", "open_id"], unique=False)
    op.create_index(op.f("ix_feishu_identity_pool_tenant_key"), "feishu_identity_pool", ["tenant_key"], unique=False)
    op.create_index(op.f("ix_feishu_identity_pool_open_id"), "feishu_identity_pool", ["open_id"], unique=False)
    op.create_index(op.f("ix_feishu_identity_pool_union_id"), "feishu_identity_pool", ["union_id"], unique=False)
    op.create_index(op.f("ix_feishu_identity_pool_feishu_user_id"), "feishu_identity_pool", ["feishu_user_id"], unique=False)
    op.create_index(op.f("ix_feishu_identity_pool_chat_id"), "feishu_identity_pool", ["chat_id"], unique=False)
    op.create_index(op.f("ix_feishu_identity_pool_bind_status"), "feishu_identity_pool", ["bind_status"], unique=False)
    op.create_index(op.f("ix_feishu_identity_pool_bound_user_id"), "feishu_identity_pool", ["bound_user_id"], unique=False)

    op.create_table(
        "system_audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_username", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=True),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("metadata_json", sa.dialects.postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_system_audit_logs_action"), "system_audit_logs", ["action"], unique=False)
    op.create_index(op.f("ix_system_audit_logs_actor_user_id"), "system_audit_logs", ["actor_user_id"], unique=False)
    op.create_index(op.f("ix_system_audit_logs_created_at"), "system_audit_logs", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_system_audit_logs_created_at"), table_name="system_audit_logs")
    op.drop_index(op.f("ix_system_audit_logs_actor_user_id"), table_name="system_audit_logs")
    op.drop_index(op.f("ix_system_audit_logs_action"), table_name="system_audit_logs")
    op.drop_table("system_audit_logs")

    op.drop_index(op.f("ix_feishu_identity_pool_bound_user_id"), table_name="feishu_identity_pool")
    op.drop_index(op.f("ix_feishu_identity_pool_bind_status"), table_name="feishu_identity_pool")
    op.drop_index(op.f("ix_feishu_identity_pool_chat_id"), table_name="feishu_identity_pool")
    op.drop_index(op.f("ix_feishu_identity_pool_feishu_user_id"), table_name="feishu_identity_pool")
    op.drop_index(op.f("ix_feishu_identity_pool_union_id"), table_name="feishu_identity_pool")
    op.drop_index(op.f("ix_feishu_identity_pool_open_id"), table_name="feishu_identity_pool")
    op.drop_index(op.f("ix_feishu_identity_pool_tenant_key"), table_name="feishu_identity_pool")
    op.drop_index(op.f("ix_feishu_identity_pool_tenant_open"), table_name="feishu_identity_pool")
    op.drop_table("feishu_identity_pool")

    op.drop_index(op.f("ix_users_role"), table_name="users")
    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.drop_table("users")
