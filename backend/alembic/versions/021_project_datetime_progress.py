"""project datetime fields and progress text

Revision ID: i1j2k3l4m5n6
Revises: h0i1j2k3l4m5
Create Date: 2026-04-01
"""

from alembic import op
import sqlalchemy as sa


revision = "i1j2k3l4m5n6"
down_revision = "h0i1j2k3l4m5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("start_time", sa.DateTime(timezone=True), nullable=True))
    op.add_column("projects", sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("projects", sa.Column("progress_text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "progress_text")
    op.drop_column("projects", "deadline_at")
    op.drop_column("projects", "start_time")

