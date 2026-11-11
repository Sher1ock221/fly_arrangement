"""calendar events candidate scheduling fields

Revision ID: h0i1j2k3l4m5
Revises: g9h0i1j2k3l4
Create Date: 2026-04-01
"""

from alembic import op
import sqlalchemy as sa


revision = "h0i1j2k3l4m5"
down_revision = "g9h0i1j2k3l4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("calendar_events", sa.Column("status", sa.String(length=32), server_default=sa.text("'scheduled'"), nullable=False))
    op.add_column("calendar_events", sa.Column("candidate_group_id", sa.String(length=64), nullable=True))
    op.add_column("calendar_events", sa.Column("candidate_policy", sa.String(length=32), nullable=True))
    op.add_column("calendar_events", sa.Column("auto_cancel_others_on_complete", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.create_index("ix_calendar_events_status", "calendar_events", ["status"])
    op.create_index("ix_calendar_events_candidate_group_id", "calendar_events", ["candidate_group_id"])


def downgrade() -> None:
    op.drop_index("ix_calendar_events_candidate_group_id", table_name="calendar_events")
    op.drop_index("ix_calendar_events_status", table_name="calendar_events")
    op.drop_column("calendar_events", "auto_cancel_others_on_complete")
    op.drop_column("calendar_events", "candidate_policy")
    op.drop_column("calendar_events", "candidate_group_id")
    op.drop_column("calendar_events", "status")

