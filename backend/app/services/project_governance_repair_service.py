"""项目治理 repair queue：状态变更与审计。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.project_governance import (
    AUDIT_REPAIR_QUEUE_FALSE_POSITIVE,
    AUDIT_REPAIR_QUEUE_IGNORED,
    AUDIT_REPAIR_QUEUE_RESOLVED,
    AUDIT_REPAIR_QUEUE_STARTED,
    REPAIR_ACTIVE_STATUSES,
    REPAIR_ADMIN_SETTABLE_TERMINAL,
    REPAIR_STATUS_FALSE_POSITIVE,
    REPAIR_STATUS_IGNORED,
    REPAIR_STATUS_PENDING,
    REPAIR_STATUS_RESOLVED,
    REPAIR_STATUS_RUNNING,
)
from app.models.project_repair_queue import ProjectRepairQueue
from app.models.user import User
from app.services.audit_log_service import write_audit_log

logger = logging.getLogger(__name__)

StatusUpdate = Literal["resolved", "ignored", "false_positive"]

_STATUS_MAP: dict[StatusUpdate, tuple[str, str]] = {
    "resolved": (REPAIR_STATUS_RESOLVED, AUDIT_REPAIR_QUEUE_RESOLVED),
    "ignored": (REPAIR_STATUS_IGNORED, AUDIT_REPAIR_QUEUE_IGNORED),
    "false_positive": (REPAIR_STATUS_FALSE_POSITIVE, AUDIT_REPAIR_QUEUE_FALSE_POSITIVE),
}


async def apply_repair_queue_start(
    db: AsyncSession,
    *,
    queue_id: int,
    actor: User,
    request: Request | None = None,
) -> ProjectRepairQueue:
    """pending -> running：指派当前管理员并记录开始时间。与 scanner 去重协同：running 与 pending 同等占用「活跃槽位」。"""
    row = await db.get(ProjectRepairQueue, queue_id)
    if row is None or row.module != "project":
        raise HTTPException(status_code=404, detail="repair queue 条目不存在")

    if row.status != REPAIR_STATUS_PENDING:
        raise HTTPException(
            status_code=400,
            detail="仅 pending 状态可开始处理；已在处理中或已关闭的条目请使用对应操作",
        )

    now = datetime.now(timezone.utc)
    prev = row.status
    row.status = REPAIR_STATUS_RUNNING
    row.assigned_to_user_id = int(actor.id)
    row.started_at = now
    row.status_updated_at = now
    row.updated_at = now

    await write_audit_log(
        db,
        action=AUDIT_REPAIR_QUEUE_STARTED,
        actor_user_id=int(actor.id),
        actor_username=actor.username,
        target_type="project_repair_queue",
        target_id=str(queue_id),
        detail=(
            f"repair_queue_id={queue_id} previous_status={prev} new_status={REPAIR_STATUS_RUNNING} "
            f"assigned_to_user_id={actor.id}"
        ),
        ip_address=request.client.host if request and request.client else None,
        user_agent=request.headers.get("user-agent") if request else None,
        metadata_json={
            "queue_id": queue_id,
            "issue_type": row.issue_type,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "assigned_to_user_id": int(actor.id),
            "previous_status": prev,
            "new_status": REPAIR_STATUS_RUNNING,
        },
    )
    logger.info(
        "repair_queue_started queue_id=%s actor_user_id=%s new_status=%s assigned_to_user_id=%s",
        queue_id,
        actor.id,
        REPAIR_STATUS_RUNNING,
        actor.id,
    )
    await db.flush()
    return row


async def apply_repair_queue_status(
    db: AsyncSession,
    *,
    queue_id: int,
    body_status: StatusUpdate,
    resolution_note: str | None,
    actor: User,
    request: Request | None = None,
) -> ProjectRepairQueue:
    row = await db.get(ProjectRepairQueue, queue_id)
    if row is None or row.module != "project":
        raise HTTPException(status_code=404, detail="repair queue 条目不存在")

    if row.status not in REPAIR_ACTIVE_STATUSES:
        raise HTTPException(status_code=400, detail="仅可对 pending 或 running 状态的条目执行关闭操作")

    next_status, audit_action = _STATUS_MAP[body_status]
    if next_status not in REPAIR_ADMIN_SETTABLE_TERMINAL:
        raise HTTPException(status_code=400, detail="无效的状态目标")

    prev_status = row.status
    now = datetime.now(timezone.utc)
    row.status = next_status
    if resolution_note is not None:
        row.resolution_note = resolution_note.strip() or None
    row.reviewed_by_user_id = int(actor.id)
    row.reviewed_at = now
    row.status_updated_at = now
    row.updated_at = now
    if next_status == REPAIR_STATUS_RESOLVED:
        row.resolved_at = now
    else:
        row.resolved_at = None

    note_preview = (row.resolution_note or "")[:200]
    detail = f"repair_queue_id={queue_id} status={next_status} note={note_preview!r}"
    await write_audit_log(
        db,
        action=audit_action,
        actor_user_id=int(actor.id),
        actor_username=actor.username,
        target_type="project_repair_queue",
        target_id=str(queue_id),
        detail=detail,
        ip_address=request.client.host if request and request.client else None,
        user_agent=request.headers.get("user-agent") if request else None,
        metadata_json={
            "issue_type": row.issue_type,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "resolution_note": row.resolution_note,
            "previous_status": prev_status,
            "assigned_to_user_id": row.assigned_to_user_id,
            "started_at": row.started_at.isoformat() if row.started_at else None,
        },
    )
    logger.info(
        "repair_queue status_change action=%s queue_id=%s actor_id=%s new_status=%s note_len=%s",
        audit_action,
        queue_id,
        actor.id,
        next_status,
        len(row.resolution_note) if row.resolution_note else 0,
    )
    await db.flush()
    return row
