"""日历日程 API。按 effective_user_id 隔离。"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.calendar_event import (
    CalendarEventCreate,
    CalendarEventInDB,
    CalendarEventUpdate,
)
from app.services.calendar_service import (
    create_event,
    delete_event,
    get_events,
    update_event,
)
from app.services.effective_user import (
    EffectiveUserContext,
    get_effective_user_context,
    require_effective_owner,
    write_data_access_denied_and_raise,
)

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("/events", response_model=list[dict])
async def list_events(
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    start: datetime | None = Query(None, description="开始时间（含）"),
    end: datetime | None = Query(None, description="结束时间（含）"),
    project_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """获取当前有效用户的日程列表（owner + 共享给我的）；可选 start/end 时间范围、project_id。"""
    from app.services.collaboration_service import calendar_event_visible_filter
    from app.models.calendar_event import CalendarEvent as CE
    from sqlalchemy import select as sel
    stmt = sel(CE).where(calendar_event_visible_filter(ctx.effective_user_id)).order_by(CE.start_time.asc())
    if start is not None:
        stmt = stmt.where(CE.end_time >= start)
    if end is not None:
        stmt = stmt.where(CE.start_time <= end)
    if project_id is not None:
        stmt = stmt.where(CE.project_id == project_id)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    out = []
    for r in rows:
        d = CalendarEventInDB.model_validate(r).model_dump(mode="json")
        d["access_role"] = "owner" if r.owner_user_id == ctx.effective_user_id else "collaborator"
        out.append(d)
    return out


@router.get("/events/{event_id}", response_model=dict)
async def get_event(
    event_id: int,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取单个日程详情（含 access_role）。"""
    from app.models.calendar_event import CalendarEvent
    from app.services.collaboration_service import require_at_least_collaborator
    orm = await db.get(CalendarEvent, event_id)
    if not orm:
        raise HTTPException(status_code=404, detail="日程不存在")
    role = await require_at_least_collaborator(db, "calendar_event", event_id, ctx.effective_user_id)
    d = CalendarEventInDB.model_validate(orm).model_dump(mode="json")
    d["access_role"] = role
    return d


@router.post("/events", response_model=CalendarEventInDB, status_code=201)
async def post_event(
    body: CalendarEventCreate,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> CalendarEventInDB:
    """创建日程。归属当前有效用户。"""
    orm = await create_event(db, body, owner_user_id=ctx.effective_user_id)
    return CalendarEventInDB.model_validate(orm)


@router.put("/events/{event_id}", response_model=CalendarEventInDB)
async def put_event(
    event_id: int,
    body: CalendarEventUpdate,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> CalendarEventInDB:
    """更新日程。校验归属。"""
    orm = await update_event(
        db, event_id, body, owner_user_id=ctx.effective_user_id
    )
    if orm is None:
        # 可能 404 或归属不符，需区分：若存在但归属不符则写审计
        from app.models.calendar_event import CalendarEvent
        existing = await db.get(CalendarEvent, event_id)
        if existing and existing.owner_user_id is not None and existing.owner_user_id != ctx.effective_user_id:
            await write_data_access_denied_and_raise(
                ctx, existing.owner_user_id, "calendar_event", str(event_id), request, db
            )
        raise HTTPException(status_code=404, detail="日程不存在")
    return CalendarEventInDB.model_validate(orm)


@router.delete("/events/{event_id}", status_code=204)
async def remove_event(
    event_id: int,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> None:
    """删除日程。校验归属。"""
    ok = await delete_event(db, event_id, owner_user_id=ctx.effective_user_id)
    if not ok:
        from app.models.calendar_event import CalendarEvent
        existing = await db.get(CalendarEvent, event_id)
        if existing and existing.owner_user_id is not None and existing.owner_user_id != ctx.effective_user_id:
            await write_data_access_denied_and_raise(
                ctx, existing.owner_user_id, "calendar_event", str(event_id), request, db
            )
        raise HTTPException(status_code=404, detail="日程不存在")


# ── 协作者管理（仅 owner） ──────────────────────────

from app.schemas.collaboration import CollaboratorAdd, CollaboratorOut, CalendarEventCommentCreate, CalendarEventCommentOut, TransferOwnerRequest
from app.services.collaboration_service import (
    add_calendar_event_collaborator,
    remove_calendar_event_collaborator,
    list_calendar_event_collaborators,
    require_owner as require_resource_owner,
    require_at_least_collaborator,
    add_calendar_event_comment,
    list_calendar_event_comments,
    delete_calendar_event_comment,
    transfer_calendar_event_owner as transfer_event_owner_svc,
    _get_user_brief,
)
from app.services.audit_log_service import write_audit_log as write_audit


@router.get("/events/{event_id}/collaborators", response_model=list[CollaboratorOut])
async def get_event_collaborators(
    event_id: int,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await require_at_least_collaborator(db, "calendar_event", event_id, ctx.effective_user_id)
    return await list_calendar_event_collaborators(db, event_id)


@router.post("/events/{event_id}/collaborators", response_model=CollaboratorOut, status_code=201)
async def post_event_collaborator(
    event_id: int,
    body: CollaboratorAdd,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_resource_owner(db, "calendar_event", event_id, ctx.effective_user_id)
    row = await add_calendar_event_collaborator(db, event_id, body.user_id, ctx.effective_user_id)
    await write_audit(
        db, action="calendar_event_add_collaborator", actor_user_id=ctx.effective_user_id,
        target_type="calendar_event", target_id=str(event_id),
        detail=f"added collaborator user_id={body.user_id}",
        metadata_json={"collaborator_user_id": body.user_id},
    )
    brief = await _get_user_brief(db, row.user_id)
    return {"id": row.id, "user_id": row.user_id, "created_by_user_id": row.created_by_user_id, "created_at": row.created_at, **brief}


@router.delete("/events/{event_id}/collaborators/{user_id}", status_code=204)
async def del_event_collaborator(
    event_id: int,
    user_id: int,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    await require_resource_owner(db, "calendar_event", event_id, ctx.effective_user_id)
    await remove_calendar_event_collaborator(db, event_id, user_id)
    await write_audit(
        db, action="calendar_event_remove_collaborator", actor_user_id=ctx.effective_user_id,
        target_type="calendar_event", target_id=str(event_id),
        detail=f"removed collaborator user_id={user_id}",
        metadata_json={"collaborator_user_id": user_id},
    )


# ── 日程评论（owner + collaborator 可添加） ────────

@router.get("/events/{event_id}/comments", response_model=list[CalendarEventCommentOut])
async def get_event_comments(
    event_id: int,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await require_at_least_collaborator(db, "calendar_event", event_id, ctx.effective_user_id)
    return await list_calendar_event_comments(db, event_id)


@router.post("/events/{event_id}/comments", response_model=CalendarEventCommentOut, status_code=201)
async def post_event_comment(
    event_id: int,
    body: CalendarEventCommentCreate,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_at_least_collaborator(db, "calendar_event", event_id, ctx.effective_user_id)
    row = await add_calendar_event_comment(db, event_id, ctx.effective_user_id, body.content)
    await write_audit(
        db, action="calendar_event_add_comment", actor_user_id=ctx.effective_user_id,
        target_type="calendar_event", target_id=str(event_id),
        detail="added comment",
    )
    brief = await _get_user_brief(db, ctx.effective_user_id)
    return {
        "id": row.id, "calendar_event_id": row.calendar_event_id, "author_user_id": row.author_user_id,
        "content": row.content, "created_at": row.created_at,
        "author_display_name": brief.get("display_name"),
    }


@router.delete("/events/{event_id}/comments/{comment_id}", status_code=204)
async def del_event_comment(
    event_id: int,
    comment_id: int,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    await require_at_least_collaborator(db, "calendar_event", event_id, ctx.effective_user_id)
    await delete_calendar_event_comment(db, event_id, comment_id, ctx.effective_user_id)
    await write_audit(
        db, action="calendar_event_delete_comment", actor_user_id=ctx.effective_user_id,
        target_type="calendar_event", target_id=str(event_id),
        detail=f"deleted comment id={comment_id}",
        metadata_json={"comment_id": comment_id},
    )


# ── ownership 转移 ────────────────────────────────


@router.post("/events/{event_id}/transfer-owner")
async def transfer_event_owner(
    event_id: int,
    body: TransferOwnerRequest,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_resource_owner(db, "calendar_event", event_id, ctx.effective_user_id)
    result = await transfer_event_owner_svc(db, event_id, ctx.effective_user_id, body.target_user_id)
    await write_audit(
        db, action="calendar_event_transfer_owner", actor_user_id=ctx.effective_user_id,
        target_type="calendar_event", target_id=str(event_id),
        detail=f"transferred ownership to user_id={body.target_user_id}",
        metadata_json=result,
    )
    return {"ok": True, **result}
