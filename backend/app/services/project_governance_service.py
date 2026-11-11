from __future__ import annotations

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.project_governance import (
    ISSUE_TYPE_VISIBILITY_MISMATCH,
    REPAIR_ACTIVE_STATUSES,
    REPAIR_STATUS_RUNNING,
)
from app.services.repair_queue_sla_service import sla_overdue_cutoff
from app.models.project import Project
from app.models.project_repair_queue import ProjectRepairQueue
from app.services.project_owner_repair_queue_runtime import count_project_owner_repair_queue


async def get_project_governance_summary(db: AsyncSession) -> dict:
    legacy_owner_count = await count_project_owner_repair_queue(db)
    missing_initiator_count = (
        await db.execute(select(func.count(Project.id)).where(Project.initiator_user_id.is_(None)))
    ).scalar_one() or 0
    missing_owner_count = (
        await db.execute(select(func.count(Project.id)).where(Project.owner_user_id.is_(None)))
    ).scalar_one() or 0
    initiator_owner_conflict_count = (
        await db.execute(
            text(
                """
                SELECT COUNT(*) FROM projects p
                LEFT JOIN users u1 ON u1.id = p.initiator_user_id
                LEFT JOIN users u2 ON u2.id = p.owner_user_id
                WHERE (p.initiator_user_id IS NOT NULL AND u1.id IS NULL)
                   OR (p.owner_user_id IS NOT NULL AND u2.id IS NULL)
                """
            )
        )
    ).scalar_one() or 0
    dirty_collaborator_relation_count = (
        await db.execute(
            text(
                """
                SELECT COUNT(*) FROM project_collaborators pc
                LEFT JOIN users u ON u.id = pc.user_id
                LEFT JOIN projects p ON p.id = pc.project_id
                WHERE u.id IS NULL
                   OR p.id IS NULL
                   OR pc.user_id = p.owner_user_id
                   OR pc.user_id = p.initiator_user_id
                """
            )
        )
    ).scalar_one() or 0
    manual_repair_queue_count = (
        await db.execute(
            select(func.count(ProjectRepairQueue.id)).where(
                ProjectRepairQueue.module == "project",
                ProjectRepairQueue.status.in_(list(REPAIR_ACTIVE_STATUSES)),
            )
        )
    ).scalar_one() or 0
    legacy_member_count = legacy_owner_count
    visibility_mismatch_count = (
        await db.execute(
            select(func.count(ProjectRepairQueue.id)).where(
                ProjectRepairQueue.module == "project",
                ProjectRepairQueue.issue_type == ISSUE_TYPE_VISIBILITY_MISMATCH,
                ProjectRepairQueue.status.in_(["pending", "running"]),
            )
        )
    ).scalar_one() or 0
    cutoff = sla_overdue_cutoff()
    overdue_repair_queue_count = (
        await db.execute(
            select(func.count(ProjectRepairQueue.id)).where(
                ProjectRepairQueue.module == "project",
                ProjectRepairQueue.status == REPAIR_STATUS_RUNNING,
                ProjectRepairQueue.started_at.is_not(None),
                ProjectRepairQueue.started_at < cutoff,
            )
        )
    ).scalar_one() or 0
    return {
        "legacy_owner_count": int(legacy_owner_count),
        "legacy_member_count": int(legacy_member_count),
        "missing_initiator_count": int(missing_initiator_count),
        "missing_owner_count": int(missing_owner_count),
        "initiator_owner_conflict_count": int(initiator_owner_conflict_count),
        "dirty_collaborator_relation_count": int(dirty_collaborator_relation_count),
        "visibility_mismatch_count": int(visibility_mismatch_count),
        "manual_repair_queue_count": int(manual_repair_queue_count),
        "overdue_repair_queue_count": int(overdue_repair_queue_count),
    }

