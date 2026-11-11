"""init schema

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2025-03-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # customers 无外键，先建
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("origin", sa.String(length=256), nullable=True),
        sa.Column("company", sa.String(length=256), nullable=True),
        sa.Column("profile", sa.Text(), nullable=True),
        sa.Column("contact", sa.String(length=512), nullable=True),
        sa.Column("future_direction", sa.Text(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_customers_company"), "customers", ["company"], unique=False)
    op.create_index(op.f("ix_customers_name"), "customers", ["name"], unique=False)

    # projects 依赖 customers
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_no", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("deadline", sa.Date(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("goal", sa.String(length=1024), nullable=True),
        sa.Column("owner", sa.String(length=128), nullable=True),
        sa.Column("update_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requirements", sa.Text(), nullable=True),
        sa.Column("customer_name", sa.String(length=256), nullable=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_projects_customer_id"), "projects", ["customer_id"], unique=False)
    op.create_index(op.f("ix_projects_name"), "projects", ["name"], unique=False)
    op.create_index(op.f("ix_projects_project_no"), "projects", ["project_no"], unique=True)
    op.create_index(op.f("ix_projects_status"), "projects", ["status"], unique=False)

    # calendar_events 依赖 projects
    op.create_table(
        "calendar_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False, server_default=sa.text("'event'")),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_calendar_events_project_id"), "calendar_events", ["project_id"], unique=False)
    op.create_index(op.f("ix_calendar_events_type"), "calendar_events", ["type"], unique=False)

    # system_logs
    op.create_table(
        "system_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("module", sa.String(length=128), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("stack_trace", sa.Text(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_system_logs_level"), "system_logs", ["level"], unique=False)
    op.create_index(op.f("ix_system_logs_module"), "system_logs", ["module"], unique=False)
    op.create_index(op.f("ix_system_logs_request_id"), "system_logs", ["request_id"], unique=False)
    op.create_index(op.f("ix_system_logs_timestamp"), "system_logs", ["timestamp"], unique=False)

    # chat_records
    op.create_table(
        "chat_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_message", sa.Text(), nullable=False),
        sa.Column("ai_response", sa.Text(), nullable=False),
        sa.Column("tool_calls", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("session_id", sa.String(length=100), nullable=True),
        sa.Column("intent", sa.String(length=100), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chat_records_session_id"), "chat_records", ["session_id"], unique=False)
    op.create_index(op.f("ix_chat_records_timestamp"), "chat_records", ["timestamp"], unique=False)

    # ai_configs
    op.create_table(
        "ai_configs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("base_url", sa.String(length=512), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("temperature", sa.Float(), nullable=False, server_default=sa.text("0.2")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # audit_logs
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("old_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("operator", sa.String(length=100), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_logs_target_id"), "audit_logs", ["target_id"], unique=False)
    op.create_index(op.f("ix_audit_logs_target_type"), "audit_logs", ["target_type"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_logs_target_type"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_target_id"), table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("ai_configs")
    op.drop_index(op.f("ix_chat_records_timestamp"), table_name="chat_records")
    op.drop_index(op.f("ix_chat_records_session_id"), table_name="chat_records")
    op.drop_table("chat_records")
    op.drop_index(op.f("ix_system_logs_timestamp"), table_name="system_logs")
    op.drop_index(op.f("ix_system_logs_request_id"), table_name="system_logs")
    op.drop_index(op.f("ix_system_logs_module"), table_name="system_logs")
    op.drop_index(op.f("ix_system_logs_level"), table_name="system_logs")
    op.drop_table("system_logs")
    op.drop_index(op.f("ix_calendar_events_type"), table_name="calendar_events")
    op.drop_index(op.f("ix_calendar_events_project_id"), table_name="calendar_events")
    op.drop_table("calendar_events")
    op.drop_index(op.f("ix_projects_status"), table_name="projects")
    op.drop_index(op.f("ix_projects_project_no"), table_name="projects")
    op.drop_index(op.f("ix_projects_name"), table_name="projects")
    op.drop_index(op.f("ix_projects_customer_id"), table_name="projects")
    op.drop_table("projects")
    op.drop_index(op.f("ix_customers_name"), table_name="customers")
    op.drop_index(op.f("ix_customers_company"), table_name="customers")
    op.drop_table("customers")
