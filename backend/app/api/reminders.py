"""提醒计划 API：按有效用户隔离。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.effective_user import EffectiveUserContext, get_effective_user_context
from app.services.reminder_service import (
    cancel_reminder_task_service,
    list_reminder_tasks_service,
    update_reminder_task_service,
)

router = APIRouter(prefix="/reminders", tags=["reminders"])


class ReminderUpdateBody(BaseModel):
    title: str | None = None
    content: str | None = None
    end_at: str | None = None
    is_enabled: bool | None = None
    schedule_rule: dict[str, Any] | None = None
    status: str | None = Field(None, description="active 或 paused")


@router.get("", response_model=list[dict])
async def list_reminders(
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    out = await list_reminder_tasks_service(
        db, operator_user_id=ctx.effective_user_id, status_filter=status
    )
    if not out.get("success"):
        raise HTTPException(status_code=400, detail=out.get("error", "查询失败"))
    return out.get("result") or []


@router.patch("/{task_id}", response_model=dict)
async def update_reminder(
    task_id: int,
    body: ReminderUpdateBody,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    out = await update_reminder_task_service(
        db,
        operator_user_id=ctx.effective_user_id,
        task_id=task_id,
        title=body.title,
        content=body.content,
        end_at=body.end_at,
        is_enabled=body.is_enabled,
        schedule_rule=body.schedule_rule,
        status=body.status,
    )
    if not out.get("success"):
        raise HTTPException(status_code=400, detail=out.get("error", "更新失败"))
    return out.get("result") or {}


@router.post("/{task_id}/cancel", response_model=dict)
async def cancel_reminder(
    task_id: int,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    out = await cancel_reminder_task_service(
        db, operator_user_id=ctx.effective_user_id, task_id=task_id
    )
    if not out.get("success"):
        raise HTTPException(status_code=400, detail=out.get("error", "取消失败"))
    return out.get("result") or {}
