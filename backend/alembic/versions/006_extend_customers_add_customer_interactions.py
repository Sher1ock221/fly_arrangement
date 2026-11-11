"""extend customers and add customer_interactions

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-03-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 扩展 customers 表（仅新增不存在的列，兼容已有数据）
    op.add_column("customers", sa.Column("position", sa.String(length=128), nullable=True))
    op.add_column("customers", sa.Column("business_direction", sa.String(length=512), nullable=True))
    op.add_column("customers", sa.Column("notes", sa.Text(), nullable=True))
    op.add_column("customers", sa.Column("acquaintance_source", sa.String(length=256), nullable=True))
    op.add_column(
        "customers",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
    )

    # 客户跟进记录表
    op.create_table(
        "customer_interactions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("meeting_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("talk_summary", sa.Text(), nullable=True),
        sa.Column("cooperation_direction", sa.String(length=512), nullable=True),
        sa.Column("cooperation_intent", sa.String(length=512), nullable=True),
        sa.Column("next_cooperation_plan", sa.String(length=512), nullable=True),
        sa.Column("specific_needs", sa.Text(), nullable=True),
        sa.Column("importance", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.Column("raw_input", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_customer_interactions_customer_id"), "customer_interactions", ["customer_id"], unique=False)
    op.create_index(op.f("ix_customer_interactions_source"), "customer_interactions", ["source"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_customer_interactions_source"), table_name="customer_interactions")
    op.drop_index(op.f("ix_customer_interactions_customer_id"), table_name="customer_interactions")
    op.drop_table("customer_interactions")

    op.drop_column("customers", "updated_at")
    op.drop_column("customers", "acquaintance_source")
    op.drop_column("customers", "notes")
    op.drop_column("customers", "business_direction")
    op.drop_column("customers", "position")
