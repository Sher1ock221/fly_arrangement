"""Add collaboration tables: collaborator + activity (project_updates, customer_followups, calendar_event_comments)

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-03-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "a2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 共享关系表 ──

    op.create_table(
        "project_collaborators",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_collaborator"),
    )
    op.create_index("ix_project_collaborators_project_id", "project_collaborators", ["project_id"])
    op.create_index("ix_project_collaborators_user_id", "project_collaborators", ["user_id"])

    op.create_table(
        "customer_collaborators",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_id", "user_id", name="uq_customer_collaborator"),
    )
    op.create_index("ix_customer_collaborators_customer_id", "customer_collaborators", ["customer_id"])
    op.create_index("ix_customer_collaborators_user_id", "customer_collaborators", ["user_id"])

    op.create_table(
        "calendar_event_collaborators",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("calendar_event_id", sa.Integer(), sa.ForeignKey("calendar_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("calendar_event_id", "user_id", name="uq_calendar_event_collaborator"),
    )
    op.create_index("ix_calendar_event_collaborators_calendar_event_id", "calendar_event_collaborators", ["calendar_event_id"])
    op.create_index("ix_calendar_event_collaborators_user_id", "calendar_event_collaborators", ["user_id"])

    # ── 附属协作数据表 ──

    op.create_table(
        "project_updates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("update_type", sa.String(32), nullable=False, server_default="note"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_project_updates_project_id", "project_updates", ["project_id"])
    op.create_index("ix_project_updates_author_user_id", "project_updates", ["author_user_id"])

    op.create_table(
        "customer_followups",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_customer_followups_customer_id", "customer_followups", ["customer_id"])
    op.create_index("ix_customer_followups_author_user_id", "customer_followups", ["author_user_id"])

    op.create_table(
        "calendar_event_comments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("calendar_event_id", sa.Integer(), sa.ForeignKey("calendar_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_calendar_event_comments_calendar_event_id", "calendar_event_comments", ["calendar_event_id"])
    op.create_index("ix_calendar_event_comments_author_user_id", "calendar_event_comments", ["author_user_id"])


def downgrade() -> None:
    op.drop_table("calendar_event_comments")
    op.drop_table("customer_followups")
    op.drop_table("project_updates")
    op.drop_table("calendar_event_collaborators")
    op.drop_table("customer_collaborators")
    op.drop_table("project_collaborators")
