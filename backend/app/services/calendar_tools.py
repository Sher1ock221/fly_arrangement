"""AI 日历工具：供 Agent 查询、创建、更新、删除日程。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.calendar_event import CalendarEventCreate, CalendarEventUpdate
from app.services.calendar_service import create_event, delete_event, get_events, update_event


def _parse_iso(s: str | None) -> datetime | None:
    if not s or not s.strip():
        return None
    s = s.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _parse_bool(v: Any) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        t = v.strip().lower()
        if t in ("true", "1", "yes", "y"):
            return True
        if t in ("false", "0", "no", "n"):
            return False
    return None


async def get_calendar_events(
    db: AsyncSession,
    start: str | None = None,
    end: str | None = None,
    project_id: int | None = None,
    owner_user_id: int | None = None,
) -> dict[str, Any]:
    """查询日程列表。owner_user_id 有值时仅返回该用户的日程（飞书等按发言人隔离）。"""
    if owner_user_id is None:
        return {"success": True, "result": [], "execution_summary": "需要用户身份才能查看日程"}
    start_dt = _parse_iso(start)
    end_dt = _parse_iso(end)
    rows = await get_events(db, owner_user_id=owner_user_id, start=start_dt, end=end_dt, project_id=project_id)
    data = [
        {
            "id": r.id,
            "title": r.title,
            "description": r.description,
            "start_time": r.start_time.isoformat() if r.start_time else None,
            "end_time": r.end_time.isoformat() if r.end_time else None,
            "type": r.type,
            "project_id": r.project_id,
        }
        for r in rows
    ]
    return {
        "success": True,
        "result": data,
        "execution_summary": f"共 {len(data)} 条日程",
    }


async def create_calendar_event(
    db: AsyncSession,
    title: str,
    start_time: str,
    end_time: str,
    description: str | None = None,
    type: str = "event",
    project_id: int | None = None,
    status: str | None = None,
    candidate_group_id: str | None = None,
    candidate_policy: str | None = None,
    auto_cancel_others_on_complete: bool | None = None,
    owner_user_id: int | None = None,
) -> dict[str, Any]:
    """创建日程。owner_user_id 有值时归属该用户（飞书等按发言人隔离）。"""
    if owner_user_id is None:
        return {"success": False, "error": "需要用户身份才能创建日程", "execution_summary": "需要用户身份才能创建日程"}
    st = _parse_iso(start_time)
    et = _parse_iso(end_time)
    if not st or not et:
        return {"success": False, "error": "start_time 与 end_time 必填且为 ISO 格式", "execution_summary": "时间格式错误"}
    if et <= st:
        return {"success": False, "error": "end_time 必须晚于 start_time", "execution_summary": "时间范围错误"}
    body = CalendarEventCreate(
        title=title.strip() or "未命名",
        description=description,
        start_time=st,
        end_time=et,
        type=type if type in ("event", "project", "meeting", "task") else "event",
        project_id=project_id,
        status=status if status in ("scheduled", "confirmed", "completed", "cancelled") else "scheduled",
        candidate_group_id=candidate_group_id,
        candidate_policy=candidate_policy,
        auto_cancel_others_on_complete=bool(auto_cancel_others_on_complete),
    )
    orm = await create_event(db, body, owner_user_id=owner_user_id)
    return {
        "success": True,
        "result": {"id": orm.id, "title": orm.title, "start_time": orm.start_time.isoformat(), "end_time": orm.end_time.isoformat()},
        "execution_summary": f"已创建日程 [{orm.title}]",
    }


async def update_calendar_event(
    db: AsyncSession,
    event_id: int,
    title: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    description: str | None = None,
    type: str | None = None,
    project_id: int | None = None,
    status: str | None = None,
    candidate_group_id: str | None = None,
    candidate_policy: str | None = None,
    auto_cancel_others_on_complete: bool | None = None,
    owner_user_id: int | None = None,
) -> dict[str, Any]:
    """更新日程。owner_user_id 有值时校验归属。"""
    data = {}
    if title is not None:
        data["title"] = title.strip() or "未命名"
    if start_time is not None:
        st = _parse_iso(start_time)
        if st is None:
            return {"success": False, "error": "start_time 格式错误", "execution_summary": "时间格式错误"}
        data["start_time"] = st
    if end_time is not None:
        et = _parse_iso(end_time)
        if et is None:
            return {"success": False, "error": "end_time 格式错误", "execution_summary": "时间格式错误"}
        data["end_time"] = et
    if description is not None:
        data["description"] = description
    if type is not None and type in ("event", "project", "meeting", "task"):
        data["type"] = type
    if project_id is not None:
        data["project_id"] = project_id
    if status is not None and status in ("scheduled", "confirmed", "completed", "cancelled"):
        data["status"] = status
    if candidate_group_id is not None:
        data["candidate_group_id"] = candidate_group_id
    if candidate_policy is not None:
        data["candidate_policy"] = candidate_policy
    parsed_bool = _parse_bool(auto_cancel_others_on_complete)
    if parsed_bool is not None:
        data["auto_cancel_others_on_complete"] = parsed_bool
    if not data:
        return {"success": False, "error": "无有效更新字段", "execution_summary": "无更新"}
    body = CalendarEventUpdate(**data)
    orm = await update_event(db, event_id, body, owner_user_id=owner_user_id)
    if orm is None:
        return {"success": False, "error": "日程不存在", "execution_summary": "日程不存在"}
    return {
        "success": True,
        "result": {"id": orm.id, "title": orm.title},
        "execution_summary": f"已更新日程 [{orm.title}]",
    }


async def delete_calendar_event(db: AsyncSession, event_id: int, *, owner_user_id: int | None = None) -> dict[str, Any]:
    """删除日程。owner_user_id 有值时校验归属。"""
    ok = await delete_event(db, event_id, owner_user_id=owner_user_id)
    if not ok:
        return {"success": False, "error": "日程不存在", "execution_summary": "日程不存在"}
    return {"success": True, "execution_summary": "已删除该日程"}
