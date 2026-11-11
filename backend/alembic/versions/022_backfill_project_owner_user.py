"""backfill project owner_user_id from owner text

Revision ID: j2k3l4m5n6o7
Revises: i1j2k3l4m5n6
Create Date: 2026-04-01
"""

from alembic import op


revision = "j2k3l4m5n6o7"
down_revision = "i1j2k3l4m5n6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 优先按 display_name 精确匹配，再按 username 精确匹配，回填 owner_user_id 与规范化 owner 显示
    op.execute(
        """
        UPDATE projects p
        SET owner_user_id = u.id,
            owner = COALESCE(NULLIF(u.display_name, ''), u.username)
        FROM users u
        WHERE p.owner_user_id IS NULL
          AND p.owner IS NOT NULL
          AND btrim(p.owner) <> ''
          AND u.is_active = true
          AND lower(btrim(p.owner)) = lower(btrim(COALESCE(NULLIF(u.display_name, ''), u.username)));
        """
    )
    op.execute(
        """
        UPDATE projects p
        SET owner_user_id = u.id,
            owner = COALESCE(NULLIF(u.display_name, ''), u.username)
        FROM users u
        WHERE p.owner_user_id IS NULL
          AND p.owner IS NOT NULL
          AND btrim(p.owner) <> ''
          AND u.is_active = true
          AND lower(btrim(p.owner)) = lower(btrim(u.username));
        """
    )


def downgrade() -> None:
    # 数据回填不可逆
    pass

