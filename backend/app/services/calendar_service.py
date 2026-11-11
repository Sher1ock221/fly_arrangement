"""日历日程服务：查询、创建、更新、删除。按 owner_user_id 隔离（含 collaborator 可见性）。"""
from datetime import datetime, timezone

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.calendar_event import CalendarEvent
from app.models.collaboration import CalendarEventCollaborator
from app.schemas.calendar_event import CalendarEventCreate, CalendarEventUpdate


async def get_events(
    db: AsyncSession,
    *,
    owner_user_id: int,
    start: datetime | None = None,
    end: datetime | None = None,
    project_id: int | None = None,
) -> list[CalendarEvent]:
    """查询日程；返回用户 own 或 collaborate 的日程。可选按时间范围、project_id 筛选。"""
    collab_exists = exists().where(
        CalendarEventCollaborator.calendar_event_id == CalendarEvent.id,
        CalendarEventCollaborator.user_id == owner_user_id,
    )
    stmt = (
        select(CalendarEvent)
        .where(or_(CalendarEvent.owner_user_id == owner_user_id, collab_exists))
        .order_by(CalendarEvent.start_time.asc())
    )
    if start is not None:
        stmt = stmt.where(CalendarEvent.end_time >= start)
    if end is not None:
        stmt = stmt.where(CalendarEvent.start_time <= end)
    if project_id is not None:
        stmt = stmt.where(CalendarEvent.project_id == project_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def create_event(
    db: AsyncSession, body: CalendarEventCreate, *, owner_user_id: int
) -> CalendarEvent:
    """创建日程。"""
    orm = CalendarEvent(
        title=body.title,
        description=body.description,
        start_time=body.start_time,
        end_time=body.end_time,
        type=body.type,
        project_id=body.project_id,
        status=body.status,
        candidate_group_id=body.candidate_group_id,
        candidate_policy=body.candidate_policy,
        auto_cancel_others_on_complete=body.auto_cancel_others_on_complete,
        owner_user_id=owner_user_id,
    )
    db.add(orm)
    await db.flush()
    await db.refresh(orm)
    return orm


async def update_event(
    db: AsyncSession, event_id: int, body: CalendarEventUpdate, *, owner_user_id: int | None = None
) -> CalendarEvent | None:
    """更新日程。若传 owner_user_id 则校验归属。"""
    orm = await db.get(CalendarEvent, event_id)
    if orm is None:
        return None
    if owner_user_id is not None and orm.owner_user_id != owner_user_id:
        return None  # 归属不符，由调用方视为 404
    data = body.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(orm, key, value)
    if (
        body.status in ("completed", "confirmed")
        and orm.auto_cancel_others_on_complete
        and orm.candidate_group_id
    ):
        result = await db.execute(
            select(CalendarEvent).where(
                CalendarEvent.owner_user_id == orm.owner_user_id,
                CalendarEvent.candidate_group_id == orm.candidate_group_id,
                CalendarEvent.id != orm.id,
                CalendarEvent.start_time >= datetime.now(timezone.utc),
                CalendarEvent.status.notin_(["completed", "cancelled"]),
            )
        )
        others = list(result.scalars().all())
        for e in others:
            e.status = "cancelled"
    await db.flush()
    await db.refresh(orm)
    return orm


async def delete_event(
    db: AsyncSession, event_id: int, *, owner_user_id: int | None = None
) -> bool:
    """删除日程。若传 owner_user_id 则校验归属。"""
    orm = await db.get(CalendarEvent, event_id)
    if orm is None:
        return False
    if owner_user_id is not None and orm.owner_user_id != owner_user_id:
        return False
    await db.delete(orm)
    await db.flush()
    return True
