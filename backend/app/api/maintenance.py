"""
管理员数据维护 API：数据概况、日志清理、归属修复、批量删除。
仅管理员可访问，所有危险操作需二次确认并写审计日志。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import require_admin
from app.db.session import get_db
from app.models import (
    CalendarEvent,
    ChatRecord,
    Conversation,
    Customer,
    FeishuMessageEvent,
    Project,
    SystemLog,
)
from app.models.system_audit_log import SystemAuditLog
from app.models.project_customer import ProjectCustomer
from app.schemas.admin import (
    DeleteMaintenanceRequest,
    LogsClearRequest,
    ReassignDataRequest,
)
from app.services.audit_log_service import write_audit_log
from app.services.auth_service import get_user_by_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/maintenance", tags=["admin"])

RESOURCE_TYPES = ("projects", "customers", "calendar_events", "conversations")


def _parse_iso_datetime(s: str | None):
    if not s or not s.strip():
        return None
    try:
        return datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------- A. 数据概况 ----------
@router.get("/summary")
async def maintenance_summary(
    current_user: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """数据维护概况：各表总数、无归属数量、日志条数。"""
    project_count = int((await db.execute(select(func.count(Project.id)))).scalar_one())
    customer_count = int((await db.execute(select(func.count(Customer.id)))).scalar_one())
    calendar_event_count = int((await db.execute(select(func.count(CalendarEvent.id)))).scalar_one())
    conversation_count = int((await db.execute(select(func.count(Conversation.id)))).scalar_one())
    null_owner_project = int(
        (await db.execute(select(func.count(Project.id)).where(Project.owner_user_id.is_(None)))).scalar_one()
    )
    null_owner_customer = int(
        (await db.execute(select(func.count(Customer.id)).where(Customer.owner_user_id.is_(None)))).scalar_one()
    )
    null_owner_calendar_event = int(
        (await db.execute(select(func.count(CalendarEvent.id)).where(CalendarEvent.owner_user_id.is_(None)))).scalar_one()
    )
    null_owner_conversation = int(
        (await db.execute(select(func.count(Conversation.id)).where(Conversation.owner_user_id.is_(None)))).scalar_one()
    )
    chat_log_count = int((await db.execute(select(func.count(ChatRecord.id)))).scalar_one())
    system_log_count = int((await db.execute(select(func.count(SystemLog.id)))).scalar_one())
    audit_log_count = int((await db.execute(select(func.count(SystemAuditLog.id)))).scalar_one())
    feishu_event_count = int((await db.execute(select(func.count(FeishuMessageEvent.id)))).scalar_one())

    logger.info("admin.maintenance: viewed summary by user_id=%s", current_user.id)

    return {
        "ok": True,
        "project_count": project_count,
        "customer_count": customer_count,
        "calendar_event_count": calendar_event_count,
        "conversation_count": conversation_count,
        "null_owner_project_count": null_owner_project,
        "null_owner_customer_count": null_owner_customer,
        "null_owner_calendar_event_count": null_owner_calendar_event,
        "null_owner_conversation_count": null_owner_conversation,
        "chat_log_count": chat_log_count,
        "system_log_count": system_log_count,
        "audit_log_count": audit_log_count,
        "feishu_event_count": feishu_event_count,
    }


# ---------- B. 日志清理 ----------
@router.post("/logs/clear")
async def maintenance_logs_clear(
    body: LogsClearRequest,
    request: Request,
    current_user: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """按 scope 清理日志，需正确输入确认词。"""
    try:
        body.validate_confirm()
    except ValueError as e:
        logger.warning("admin.maintenance: invalid confirm_text scope=%s", body.scope)
        raise HTTPException(status_code=400, detail=str(e))

    scope = body.scope.strip().lower()
    deleted_count = 0

    if scope == "chat":
        r = await db.execute(delete(ChatRecord))
        deleted_count = int(getattr(r, "rowcount", 0) or 0)
    elif scope == "system":
        r = await db.execute(delete(SystemLog))
        deleted_count = int(getattr(r, "rowcount", 0) or 0)
    elif scope == "audit":
        r = await db.execute(delete(SystemAuditLog))
        deleted_count = int(getattr(r, "rowcount", 0) or 0)
    elif scope == "feishu":
        r = await db.execute(delete(FeishuMessageEvent))
        deleted_count = int(getattr(r, "rowcount", 0) or 0)
    elif scope == "all":
        r1 = await db.execute(delete(ChatRecord))
        r2 = await db.execute(delete(SystemLog))
        r3 = await db.execute(delete(SystemAuditLog))
        r4 = await db.execute(delete(FeishuMessageEvent))
        deleted_count = (
            int(getattr(r1, "rowcount", 0) or 0)
            + int(getattr(r2, "rowcount", 0) or 0)
            + int(getattr(r3, "rowcount", 0) or 0)
            + int(getattr(r4, "rowcount", 0) or 0)
        )
    else:
        raise HTTPException(status_code=400, detail="scope 必须为 chat / system / audit / feishu / all")

    await db.flush()

    await write_audit_log(
        db,
        action="admin_clear_logs",
        actor_user_id=current_user.id,
        actor_username=current_user.username,
        target_type="maintenance",
        target_id="logs",
        detail=f"clear logs scope={scope} deleted_count={deleted_count}",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata_json={"scope": scope, "deleted_count": deleted_count},
    )
    logger.info("admin.maintenance: clear logs scope=%s deleted_count=%s by user_id=%s", scope, deleted_count, current_user.id)

    return {"ok": True, "scope": scope, "deleted_count": deleted_count}


# ---------- C. 归属修复 ----------
@router.post("/data/reassign")
async def maintenance_data_reassign(
    body: ReassignDataRequest,
    request: Request,
    current_user: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """批量将无归属（或按条件）数据归属到指定用户。"""
    try:
        body.validate_confirm()
    except ValueError as e:
        logger.warning("admin.maintenance: invalid reassign confirm_text")
        raise HTTPException(status_code=400, detail=str(e))

    if body.resource_type not in RESOURCE_TYPES:
        raise HTTPException(status_code=400, detail="resource_type 必须为 projects / customers / calendar_events / conversations")

    target = await get_user_by_id(db, body.target_user_id)
    if not target or not target.is_active:
        raise HTTPException(status_code=400, detail="目标用户不存在或已禁用")

    before_dt = _parse_iso_datetime(body.before_datetime)
    updated_count = 0

    if body.resource_type == "projects":
        stmt = select(Project)
        if body.only_null_owner:
            stmt = stmt.where(Project.owner_user_id.is_(None))
        if before_dt:
            stmt = stmt.where(Project.created_at.isnot(None), Project.created_at <= before_dt)
        result = await db.execute(stmt)
        for row in result.scalars().all():
            row.owner_user_id = body.target_user_id
            updated_count += 1
    elif body.resource_type == "customers":
        stmt = select(Customer)
        if body.only_null_owner:
            stmt = stmt.where(Customer.owner_user_id.is_(None))
        if before_dt:
            stmt = stmt.where(Customer.created_at.isnot(None), Customer.created_at <= before_dt)
        result = await db.execute(stmt)
        for row in result.scalars().all():
            row.owner_user_id = body.target_user_id
            updated_count += 1
    elif body.resource_type == "calendar_events":
        stmt = select(CalendarEvent)
        if body.only_null_owner:
            stmt = stmt.where(CalendarEvent.owner_user_id.is_(None))
        if before_dt:
            stmt = stmt.where(CalendarEvent.created_at.isnot(None), CalendarEvent.created_at <= before_dt)
        result = await db.execute(stmt)
        for row in result.scalars().all():
            row.owner_user_id = body.target_user_id
            updated_count += 1
    elif body.resource_type == "conversations":
        stmt = select(Conversation)
        if body.only_null_owner:
            stmt = stmt.where(Conversation.owner_user_id.is_(None))
        if before_dt:
            stmt = stmt.where(Conversation.created_at <= before_dt)
        result = await db.execute(stmt)
        for row in result.scalars().all():
            row.owner_user_id = body.target_user_id
            updated_count += 1

    await db.flush()

    await write_audit_log(
        db,
        action="admin_reassign_data",
        actor_user_id=current_user.id,
        actor_username=current_user.username,
        target_type="maintenance",
        target_id=body.resource_type,
        detail=f"reassign resource_type={body.resource_type} target_user_id={body.target_user_id} updated_count={updated_count}",
        ip_address=request.client.host if request.client else None,
        metadata_json={
            "resource_type": body.resource_type,
            "target_user_id": body.target_user_id,
            "only_null_owner": body.only_null_owner,
            "updated_count": updated_count,
        },
    )
    logger.info(
        "admin.maintenance: reassign resource_type=%s target_user_id=%s updated_count=%s",
        body.resource_type,
        body.target_user_id,
        updated_count,
    )

    return {"ok": True, "resource_type": body.resource_type, "updated_count": updated_count}


# ---------- D. 批量删除 ----------
@router.post("/data/delete")
async def maintenance_data_delete(
    body: DeleteMaintenanceRequest,
    request: Request,
    current_user: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """按条件批量删除数据（无归属 / 指定用户 / 指定 ID 列表）。"""
    try:
        body.validate_confirm()
    except ValueError as e:
        logger.warning("admin.maintenance: invalid delete confirm_text")
        raise HTTPException(status_code=400, detail=str(e))

    if body.resource_type not in RESOURCE_TYPES:
        raise HTTPException(status_code=400, detail="resource_type 必须为 projects / customers / calendar_events / conversations")

    mode = body.mode.strip().lower()
    if mode not in ("null_owner", "by_user", "by_ids"):
        raise HTTPException(status_code=400, detail="mode 必须为 null_owner / by_user / by_ids")

    if mode == "by_user" and not body.target_user_id:
        raise HTTPException(status_code=400, detail="mode=by_user 时需提供 target_user_id")
    if mode == "by_ids" and (not body.ids or len(body.ids) == 0):
        raise HTTPException(status_code=400, detail="mode=by_ids 时需提供 ids 列表")

    before_dt = _parse_iso_datetime(body.before_datetime)
    deleted_count = 0

    try:
        if body.resource_type == "projects":
            stmt = select(Project)
            if mode == "null_owner":
                stmt = stmt.where(Project.owner_user_id.is_(None))
            elif mode == "by_user":
                stmt = stmt.where(Project.owner_user_id == body.target_user_id)
            else:
                stmt = stmt.where(Project.id.in_(body.ids or []))
            if before_dt:
                stmt = stmt.where(Project.created_at.isnot(None), Project.created_at <= before_dt)
            result = await db.execute(stmt)
            for row in result.scalars().all():
                await db.execute(delete(ProjectCustomer).where(ProjectCustomer.project_id == row.id))
                await db.delete(row)
                deleted_count += 1

        elif body.resource_type == "customers":
            stmt = select(Customer)
            if mode == "null_owner":
                stmt = stmt.where(Customer.owner_user_id.is_(None))
            elif mode == "by_user":
                stmt = stmt.where(Customer.owner_user_id == body.target_user_id)
            else:
                stmt = stmt.where(Customer.id.in_(body.ids or []))
            if before_dt:
                stmt = stmt.where(Customer.created_at.isnot(None), Customer.created_at <= before_dt)
            result = await db.execute(stmt)
            for row in result.scalars().all():
                await db.delete(row)
                deleted_count += 1

        elif body.resource_type == "calendar_events":
            stmt = select(CalendarEvent)
            if mode == "null_owner":
                stmt = stmt.where(CalendarEvent.owner_user_id.is_(None))
            elif mode == "by_user":
                stmt = stmt.where(CalendarEvent.owner_user_id == body.target_user_id)
            else:
                stmt = stmt.where(CalendarEvent.id.in_(body.ids or []))
            if before_dt:
                stmt = stmt.where(CalendarEvent.created_at.isnot(None), CalendarEvent.created_at <= before_dt)
            result = await db.execute(stmt)
            for row in result.scalars().all():
                await db.delete(row)
                deleted_count += 1

        elif body.resource_type == "conversations":
            stmt = select(Conversation)
            if mode == "null_owner":
                stmt = stmt.where(Conversation.owner_user_id.is_(None))
            elif mode == "by_user":
                stmt = stmt.where(Conversation.owner_user_id == body.target_user_id)
            else:
                stmt = stmt.where(Conversation.id.in_(body.ids or []))
            if before_dt:
                stmt = stmt.where(Conversation.created_at <= before_dt)
            result = await db.execute(stmt)
            for row in result.scalars().all():
                await db.delete(row)
                deleted_count += 1
    except Exception as e:
        logger.exception("admin.maintenance: delete failed resource_type=%s mode=%s", body.resource_type, mode)
        raise HTTPException(status_code=500, detail=f"删除失败，可能存在关联约束：{e!s}")

    await db.flush()

    await write_audit_log(
        db,
        action="admin_delete_maintenance_data",
        actor_user_id=current_user.id,
        actor_username=current_user.username,
        target_type="maintenance",
        target_id=body.resource_type,
        detail=f"delete resource_type={body.resource_type} mode={mode} deleted_count={deleted_count}",
        ip_address=request.client.host if request.client else None,
        metadata_json={
            "resource_type": body.resource_type,
            "mode": mode,
            "target_user_id": body.target_user_id,
            "deleted_count": deleted_count,
        },
    )
    logger.info(
        "admin.maintenance: delete resource_type=%s mode=%s deleted_count=%s",
        body.resource_type,
        mode,
        deleted_count,
    )

    return {"ok": True, "resource_type": body.resource_type, "mode": mode, "deleted_count": deleted_count}
