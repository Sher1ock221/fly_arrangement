"""create project owner repair queue

Revision ID: k3l4m5n6o7p8
Revises: j2k3l4m5n6o7
Create Date: 2026-04-01
"""

from alembic import op


revision = "k3l4m5n6o7p8"
down_revision = "j2k3l4m5n6o7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS project_owner_repair_queue (
            project_id INTEGER PRIMARY KEY,
            owner_text VARCHAR(128),
            reason VARCHAR(128) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        """
        INSERT INTO project_owner_repair_queue (project_id, owner_text, reason)
        SELECT p.id, p.owner, 'owner_user_id_unresolved'
        FROM projects p
        WHERE p.owner_user_id IS NULL
        ON CONFLICT (project_id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS project_owner_repair_queue;")

