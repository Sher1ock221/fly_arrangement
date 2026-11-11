"""repair queue: root cause + workflow fields

Revision ID: n6o7p8q9r0s1
Revises: m5n6o7p8q9r0
Create Date: 2026-04-02
"""

from alembic import op
import sqlalchemy as sa


revision = "n6o7p8q9r0s1"
down_revision = "m5n6o7p8q9r0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("project_repair_queue", sa.Column("suspected_cause", sa.String(length=64), nullable=True))
    op.add_column("project_repair_queue", sa.Column("resolution_note", sa.Text(), nullable=True))
    op.add_column("project_repair_queue", sa.Column("assigned_to_user_id", sa.Integer(), nullable=True))
    op.add_column("project_repair_queue", sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True))
    op.add_column("project_repair_queue", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("project_repair_queue", sa.Column("status_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_project_repair_queue_assigned_to_user",
        "project_repair_queue",
        "users",
        ["assigned_to_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_project_repair_queue_reviewed_by_user",
        "project_repair_queue",
        "users",
        ["reviewed_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_project_repair_queue_reviewed_by_user", "project_repair_queue", type_="foreignkey")
    op.drop_constraint("fk_project_repair_queue_assigned_to_user", "project_repair_queue", type_="foreignkey")
    op.drop_column("project_repair_queue", "status_updated_at")
    op.drop_column("project_repair_queue", "reviewed_at")
    op.drop_column("project_repair_queue", "reviewed_by_user_id")
    op.drop_column("project_repair_queue", "assigned_to_user_id")
    op.drop_column("project_repair_queue", "resolution_note")
    op.drop_column("project_repair_queue", "suspected_cause")
