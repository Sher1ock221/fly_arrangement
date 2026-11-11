from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import require_admin
from app.constants.project_governance import REPAIR_ACTIVE_STATUSES, REPAIR_STATUS_RUNNING
from app.db.session import get_db
from app.models.project_repair_queue import ProjectRepairQueue
from app.models.user import User
from app.services.project_governance_repair_service import (
    StatusUpdate,
    apply_repair_queue_start,
    apply_repair_queue_status,
)
from app.services.project_governance_service import get_project_governance_summary
from app.services.project_repair_scanner import scan_project_repair_issues
from app.services.repair_queue_cause_service import effective_suspected_cause
from app.services.repair_queue_sla_service import (
    compute_repair_queue_sla_fields,
    sla_overdue_cutoff,
)

router = APIRouter(prefix="/admin/project-governance", tags=["admin-project-governance"])


def _payload_brief(payload: dict[str, Any] | None) -> str:
    if not payload:
        return "—"
    order = ("mismatch_kind", "project_id", "user_id", "reason", "owner_text")
    parts: list[str] = []
    for k in order:
        v = payload.get(k)
        if v is not None and v != "":
            parts.append(f"{k}={v}")
    return "; ".join(parts) if parts else "—"


def _assignee_display_name(assignee_map: dict[int, str], assigned_to_user_id: int | None) -> str | None:
    if assigned_to_user_id is None:
        return None
    if assigned_to_user_id in assignee_map:
        return assignee_map[assigned_to_user_id]
    return f"user_id={assigned_to_user_id}（无用户记录）"


def _repair_queue_item(r: ProjectRepairQueue, assignee_map: dict[int, str], *, now_utc: datetime) -> dict[str, Any]:
    cause = effective_suspected_cause(r.suspected_cause, r.issue_type, r.payload_json)
    disp = _assignee_display_name(assignee_map, r.assigned_to_user_id)
    sla = compute_repair_queue_sla_fields(status=r.status, started_at=r.started_at, now=now_utc)
    return {
        "id": r.id,
        "module": r.module,
        "issue_type": r.issue_type,
        "severity": r.severity,
        "target_type": r.target_type,
        "target_id": r.target_id,
        "payload_json": r.payload_json,
        "payload_brief": _payload_brief(r.payload_json if isinstance(r.payload_json, dict) else None),
        "suspected_cause": cause,
        "resolution_note": r.resolution_note,
        "assigned_to_user_id": r.assigned_to_user_id,
        "assigned_to_user_display_name": disp,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "reviewed_by_user_id": r.reviewed_by_user_id,
        "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
        "status_updated_at": r.status_updated_at.isoformat() if r.status_updated_at else None,
        "status": r.status,
        "detected_at": r.detected_at.isoformat() if r.detected_at else None,
        "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        **sla,
    }


async def _assignee_map_for_rows(db: AsyncSession, rows: list[ProjectRepairQueue]) -> dict[int, str]:
    ids = {int(r.assigned_to_user_id) for r in rows if r.assigned_to_user_id is not None}
    if not ids:
        return {}
    res = await db.execute(select(User).where(User.id.in_(list(ids))))
    out: dict[int, str] = {}
    for u in res.scalars().all():
        out[int(u.id)] = (u.display_name or u.username or str(u.id)).strip() or str(u.id)
    return out


class RepairQueueStatusBody(BaseModel):
    status: StatusUpdate
    resolution_note: str | None = Field(default=None, max_length=4000)


@router.get("/summary")
async def governance_summary(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return {"ok": True, **(await get_project_governance_summary(db))}


@router.get("/repair-queue")
async def governance_repair_queue(
    issue_type: str | None = Query(None),
    status: str | None = Query(None),
    severity: str | None = Query(None),
    active_only: bool | None = Query(
        None,
        description="为 true 时仅返回 pending+running（未结项），与单独指定 status 互斥时以本参数为准",
    ),
    overdue_only: bool | None = Query(
        None,
        description="为 true 时仅返回 running 且已超过默认 SLA 的条目",
    ),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # 筛选优先级：overdue_only 与 active_only/status 协同时，overdue_only 优先收窄为「已超时的 running」
    # （仍为活跃子集）；此时不再应用 active_only 的 pending+running 并集，避免把 pending 混入。
    now_utc = datetime.now(timezone.utc)
    stmt = select(ProjectRepairQueue).where(ProjectRepairQueue.module == "project").order_by(ProjectRepairQueue.detected_at.desc())
    if issue_type:
        stmt = stmt.where(ProjectRepairQueue.issue_type == issue_type)
    if overdue_only:
        cutoff = sla_overdue_cutoff(now_utc)
        stmt = stmt.where(
            ProjectRepairQueue.status == REPAIR_STATUS_RUNNING,
            ProjectRepairQueue.started_at.is_not(None),
            ProjectRepairQueue.started_at < cutoff,
        )
    elif active_only:
        stmt = stmt.where(ProjectRepairQueue.status.in_(list(REPAIR_ACTIVE_STATUSES)))
    elif status:
        stmt = stmt.where(ProjectRepairQueue.status == status)
    if severity:
        stmt = stmt.where(ProjectRepairQueue.severity == severity)
    rows = list((await db.execute(stmt)).scalars().all())
    amap = await _assignee_map_for_rows(db, rows)
    return {"ok": True, "items": [_repair_queue_item(r, amap, now_utc=now_utc) for r in rows]}


@router.post("/repair-queue/{queue_id}/start")
async def governance_repair_queue_start(
    queue_id: int,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await apply_repair_queue_start(db, queue_id=queue_id, actor=current_user, request=request)
    await db.commit()
    await db.refresh(row)
    amap = await _assignee_map_for_rows(db, [row])
    return {"ok": True, "item": _repair_queue_item(row, amap, now_utc=datetime.now(timezone.utc))}


@router.post("/repair-queue/{queue_id}/status")
async def governance_repair_queue_status(
    queue_id: int,
    body: RepairQueueStatusBody,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await apply_repair_queue_status(
        db,
        queue_id=queue_id,
        body_status=body.status,
        resolution_note=body.resolution_note,
        actor=current_user,
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    amap = await _assignee_map_for_rows(db, [row])
    return {"ok": True, "item": _repair_queue_item(row, amap, now_utc=datetime.now(timezone.utc))}


@router.post("/scan")
async def governance_scan(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await scan_project_repair_issues(db)
    await db.commit()
    return {"ok": True, **result}
