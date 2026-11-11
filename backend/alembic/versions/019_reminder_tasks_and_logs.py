"""reminder_tasks + reminder_logs

Revision ID: g9h0i1j2k3l4
Revises: f18c0dbcl018
Create Date: 2026-04-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "g9h0i1j2k3l4"
down_revision = "f18c0dbcl018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reminder_tasks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=32), server_default=sa.text("'feishu_private'"), nullable=False),
        sa.Column("feishu_open_id", sa.String(length=128), nullable=True),
        sa.Column("tenant_key", sa.String(length=128), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("related_event_id", sa.Integer(), nullable=True),
        sa.Column("related_project_id", sa.Integer(), nullable=True),
        sa.Column("related_customer_id", sa.Integer(), nullable=True),
        sa.Column("reminder_type", sa.String(length=32), nullable=False),
        sa.Column("schedule_rule_json", JSONB(), nullable=True),
        sa.Column("next_trigger_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_trigger_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'active'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["related_event_id"], ["calendar_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["related_project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["related_customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reminder_tasks_owner_user_id", "reminder_tasks", ["owner_user_id"])
    op.create_index("ix_reminder_tasks_channel", "reminder_tasks", ["channel"])
    op.create_index("ix_reminder_tasks_feishu_open_id", "reminder_tasks", ["feishu_open_id"])
    op.create_index("ix_reminder_tasks_tenant_key", "reminder_tasks", ["tenant_key"])
    op.create_index("ix_reminder_tasks_related_event_id", "reminder_tasks", ["related_event_id"])
    op.create_index("ix_reminder_tasks_related_project_id", "reminder_tasks", ["related_project_id"])
    op.create_index("ix_reminder_tasks_related_customer_id", "reminder_tasks", ["related_customer_id"])
    op.create_index("ix_reminder_tasks_reminder_type", "reminder_tasks", ["reminder_type"])
    op.create_index("ix_reminder_tasks_next_trigger_at", "reminder_tasks", ["next_trigger_at"])
    op.create_index("ix_reminder_tasks_status", "reminder_tasks", ["status"])
    op.create_index("ix_reminder_tasks_due", "reminder_tasks", ["status", "is_enabled", "next_trigger_at"])

    op.create_table(
        "reminder_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("reminder_task_id", sa.Integer(), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("feishu_message_id", sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(["reminder_task_id"], ["reminder_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reminder_logs_reminder_task_id", "reminder_logs", ["reminder_task_id"])


def downgrade() -> None:
    op.drop_index("ix_reminder_logs_reminder_task_id", table_name="reminder_logs")
    op.drop_table("reminder_logs")
    op.drop_index("ix_reminder_tasks_due", table_name="reminder_tasks")
    op.drop_index("ix_reminder_tasks_status", table_name="reminder_tasks")
    op.drop_index("ix_reminder_tasks_next_trigger_at", table_name="reminder_tasks")
    op.drop_index("ix_reminder_tasks_reminder_type", table_name="reminder_tasks")
    op.drop_index("ix_reminder_tasks_related_customer_id", table_name="reminder_tasks")
    op.drop_index("ix_reminder_tasks_related_project_id", table_name="reminder_tasks")
    op.drop_index("ix_reminder_tasks_related_event_id", table_name="reminder_tasks")
    op.drop_index("ix_reminder_tasks_tenant_key", table_name="reminder_tasks")
    op.drop_index("ix_reminder_tasks_feishu_open_id", table_name="reminder_tasks")
    op.drop_index("ix_reminder_tasks_channel", table_name="reminder_tasks")
    op.drop_index("ix_reminder_tasks_owner_user_id", table_name="reminder_tasks")
    op.drop_table("reminder_tasks")
