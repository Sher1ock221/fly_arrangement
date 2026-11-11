"""phase3: add owner_user_id to projects, customers, conversations, calendar_events

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-03-11

策略：新增 owner_user_id 可空列 -> 回填历史数据归属为最早的管理员用户(id) -> 新建数据由应用层写入
若不存在管理员则回填为最早创建的用户。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # projects
    op.add_column("projects", sa.Column("owner_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_projects_owner_user_id",
        "projects",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_projects_owner_user_id"), "projects", ["owner_user_id"], unique=False)

    # customers
    op.add_column("customers", sa.Column("owner_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_customers_owner_user_id",
        "customers",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_customers_owner_user_id"), "customers", ["owner_user_id"], unique=False)

    # conversations
    op.add_column("conversations", sa.Column("owner_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_conversations_owner_user_id",
        "conversations",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_conversations_owner_user_id"), "conversations", ["owner_user_id"], unique=False)

    # calendar_events
    op.add_column("calendar_events", sa.Column("owner_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_calendar_events_owner_user_id",
        "calendar_events",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_calendar_events_owner_user_id"), "calendar_events", ["owner_user_id"], unique=False)

    # 回填：取最早管理员用户 id；若无管理员则取最早用户 id
    op.execute("""
        WITH first_admin AS (
            SELECT id FROM users WHERE role = 'admin' AND is_active = true ORDER BY id ASC LIMIT 1
        ),
        first_user AS (
            SELECT id FROM users ORDER BY id ASC LIMIT 1
        ),
        fallback AS (
            SELECT COALESCE((SELECT id FROM first_admin), (SELECT id FROM first_user)) AS uid
        )
        UPDATE projects SET owner_user_id = (SELECT uid FROM fallback) WHERE owner_user_id IS NULL;
    """)
    op.execute("""
        WITH first_admin AS (
            SELECT id FROM users WHERE role = 'admin' AND is_active = true ORDER BY id ASC LIMIT 1
        ),
        first_user AS (
            SELECT id FROM users ORDER BY id ASC LIMIT 1
        ),
        fallback AS (
            SELECT COALESCE((SELECT id FROM first_admin), (SELECT id FROM first_user)) AS uid
        )
        UPDATE customers SET owner_user_id = (SELECT uid FROM fallback) WHERE owner_user_id IS NULL;
    """)
    op.execute("""
        WITH first_admin AS (
            SELECT id FROM users WHERE role = 'admin' AND is_active = true ORDER BY id ASC LIMIT 1
        ),
        first_user AS (
            SELECT id FROM users ORDER BY id ASC LIMIT 1
        ),
        fallback AS (
            SELECT COALESCE((SELECT id FROM first_admin), (SELECT id FROM first_user)) AS uid
        )
        UPDATE conversations SET owner_user_id = (SELECT uid FROM fallback) WHERE owner_user_id IS NULL;
    """)
    op.execute("""
        WITH first_admin AS (
            SELECT id FROM users WHERE role = 'admin' AND is_active = true ORDER BY id ASC LIMIT 1
        ),
        first_user AS (
            SELECT id FROM users ORDER BY id ASC LIMIT 1
        ),
        fallback AS (
            SELECT COALESCE((SELECT id FROM first_admin), (SELECT id FROM first_user)) AS uid
        )
        UPDATE calendar_events SET owner_user_id = (SELECT uid FROM fallback) WHERE owner_user_id IS NULL;
    """)


def downgrade() -> None:
    op.drop_index(op.f("ix_calendar_events_owner_user_id"), table_name="calendar_events")
    op.drop_constraint("fk_calendar_events_owner_user_id", "calendar_events", type_="foreignkey")
    op.drop_column("calendar_events", "owner_user_id")

    op.drop_index(op.f("ix_conversations_owner_user_id"), table_name="conversations")
    op.drop_constraint("fk_conversations_owner_user_id", "conversations", type_="foreignkey")
    op.drop_column("conversations", "owner_user_id")

    op.drop_index(op.f("ix_customers_owner_user_id"), table_name="customers")
    op.drop_constraint("fk_customers_owner_user_id", "customers", type_="foreignkey")
    op.drop_column("customers", "owner_user_id")

    op.drop_index(op.f("ix_projects_owner_user_id"), table_name="projects")
    op.drop_constraint("fk_projects_owner_user_id", "projects", type_="foreignkey")
    op.drop_column("projects", "owner_user_id")
