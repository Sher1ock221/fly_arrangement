"""feishu_sync_state: add identity_pool_id, union_id and spec indexes

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-03-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "feishu_sync_state",
        sa.Column("identity_pool_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "feishu_sync_state",
        sa.Column("union_id", sa.String(length=128), nullable=True),
    )
    op.create_foreign_key(
        "fk_feishu_sync_state_identity_pool_id",
        "feishu_sync_state",
        "feishu_identity_pool",
        ["identity_pool_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_feishu_sync_state_identity_pool_id"),
        "feishu_sync_state",
        ["identity_pool_id"],
        unique=False,
    )
    op.create_index(
        "ix_feishu_sync_state_tenant_open",
        "feishu_sync_state",
        ["tenant_key", "open_id"],
        unique=False,
    )
    op.create_index(
        "ix_feishu_sync_state_enabled",
        "feishu_sync_state",
        ["is_enabled"],
        unique=False,
    )
    op.drop_index("ix_feishu_sync_state_bound_chat", table_name="feishu_sync_state")
    op.create_index(
        "uq_feishu_sync_state_bound_chat_channel",
        "feishu_sync_state",
        ["bound_user_id", "chat_id", "channel_type"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_feishu_sync_state_bound_chat_channel", table_name="feishu_sync_state")
    op.create_index(
        "ix_feishu_sync_state_bound_chat",
        "feishu_sync_state",
        ["bound_user_id", "chat_id"],
        unique=True,
    )
    op.drop_index(op.f("ix_feishu_sync_state_enabled"), table_name="feishu_sync_state")
    op.drop_index("ix_feishu_sync_state_tenant_open", table_name="feishu_sync_state")
    op.drop_index(op.f("ix_feishu_sync_state_identity_pool_id"), table_name="feishu_sync_state")
    op.drop_constraint(
        "fk_feishu_sync_state_identity_pool_id",
        "feishu_sync_state",
        type_="foreignkey",
    )
    op.drop_column("feishu_sync_state", "union_id")
    op.drop_column("feishu_sync_state", "identity_pool_id")
