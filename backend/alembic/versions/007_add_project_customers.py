"""add project_customers table and migrate projects.customer_id

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-03-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_customers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "customer_id", name="uq_project_customers_project_customer"),
    )
    op.create_index(op.f("ix_project_customers_project_id"), "project_customers", ["project_id"], unique=False)
    op.create_index(op.f("ix_project_customers_customer_id"), "project_customers", ["customer_id"], unique=False)

    # 将现有 projects.customer_id 迁移到 project_customers（有 customer_id 的项目插入一条关联）
    op.execute(
        """
        INSERT INTO project_customers (project_id, customer_id)
        SELECT id, customer_id FROM projects
        WHERE customer_id IS NOT NULL
        ON CONFLICT (project_id, customer_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_project_customers_customer_id"), table_name="project_customers")
    op.drop_index(op.f("ix_project_customers_project_id"), table_name="project_customers")
    op.drop_table("project_customers")
