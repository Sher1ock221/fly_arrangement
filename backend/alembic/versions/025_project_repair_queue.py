"""create project repair queue table

Revision ID: m5n6o7p8q9r0
Revises: l4m5n6o7p8q9
Create Date: 2026-04-01
"""

from alembic import op
import sqlalchemy as sa


revision = "m5n6o7p8q9r0"
down_revision = "l4m5n6o7p8q9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_repair_queue",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("module", sa.String(length=32), nullable=False, server_default="project"),
        sa.Column("issue_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="medium"),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.text("now()")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.text("now()")),
        sa.UniqueConstraint("module", "issue_type", "target_type", "target_id", "status", name="uq_project_repair_active_issue"),
    )
    op.create_index("ix_project_repair_queue_module", "project_repair_queue", ["module"])
    op.create_index("ix_project_repair_queue_issue_type", "project_repair_queue", ["issue_type"])
    op.create_index("ix_project_repair_queue_severity", "project_repair_queue", ["severity"])
    op.create_index("ix_project_repair_queue_target_type", "project_repair_queue", ["target_type"])
    op.create_index("ix_project_repair_queue_target_id", "project_repair_queue", ["target_id"])
    op.create_index("ix_project_repair_queue_status", "project_repair_queue", ["status"])


def downgrade() -> None:
    op.drop_index("ix_project_repair_queue_status", table_name="project_repair_queue")
    op.drop_index("ix_project_repair_queue_target_id", table_name="project_repair_queue")
    op.drop_index("ix_project_repair_queue_target_type", table_name="project_repair_queue")
    op.drop_index("ix_project_repair_queue_severity", table_name="project_repair_queue")
    op.drop_index("ix_project_repair_queue_issue_type", table_name="project_repair_queue")
    op.drop_index("ix_project_repair_queue_module", table_name="project_repair_queue")
    op.drop_table("project_repair_queue")

