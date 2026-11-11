"""chat_records: add incoming_message_id and feishu unique constraint

Revision ID: a2b3c4d5e6f7
Revises: f2a3b4c5d6e7
Create Date: 2026-03-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_records",
        sa.Column("incoming_message_id", sa.String(length=128), nullable=True),
    )
    op.create_index(
        op.f("ix_chat_records_incoming_message_id"),
        "chat_records",
        ["incoming_message_id"],
        unique=False,
    )
    # 飞书同一条用户消息只允许一条 ChatRecord（幂等）
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute(
            sa.text(
                "CREATE UNIQUE INDEX uq_chat_records_feishu_incoming ON chat_records (channel, incoming_message_id) "
                "WHERE channel = 'feishu' AND incoming_message_id IS NOT NULL"
            )
        )
    elif conn.dialect.name == "sqlite":
        op.execute(
            sa.text(
                "CREATE UNIQUE INDEX uq_chat_records_feishu_incoming ON chat_records (channel, incoming_message_id) "
                "WHERE channel = 'feishu' AND incoming_message_id IS NOT NULL"
            )
        )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name in ("postgresql", "sqlite"):
        op.drop_index("uq_chat_records_feishu_incoming", table_name="chat_records")
    op.drop_index(op.f("ix_chat_records_incoming_message_id"), table_name="chat_records")
    op.drop_column("chat_records", "incoming_message_id")
