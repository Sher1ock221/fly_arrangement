"""add initiator_user_id to projects

Revision ID: l4m5n6o7p8q9
Revises: k3l4m5n6o7p8
Create Date: 2026-04-01
"""

from alembic import op
import sqlalchemy as sa


revision = "l4m5n6o7p8q9"
down_revision = "k3l4m5n6o7p8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("initiator_user_id", sa.Integer(), nullable=True))
    op.create_index("ix_projects_initiator_user_id", "projects", ["initiator_user_id"], unique=False)
    op.create_foreign_key(
        "fk_projects_initiator_user_id_users",
        "projects",
        "users",
        ["initiator_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        """
        UPDATE projects
        SET initiator_user_id = owner_user_id
        WHERE initiator_user_id IS NULL;
        """
    )


def downgrade() -> None:
    op.drop_constraint("fk_projects_initiator_user_id_users", "projects", type_="foreignkey")
    op.drop_index("ix_projects_initiator_user_id", table_name="projects")
    op.drop_column("projects", "initiator_user_id")

