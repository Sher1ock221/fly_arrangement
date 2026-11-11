"""add source to conversations for feishu_private / feishu_group

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-03-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("source", sa.String(length=32), nullable=False, server_default=sa.text("'web'")),
    )
    op.create_index(op.f("ix_conversations_source"), "conversations", ["source"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_conversations_source"), table_name="conversations")
    op.drop_column("conversations", "source")
