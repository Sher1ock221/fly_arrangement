"""
协作服务：owner + collaborator 两级权限判断、可见性查询、协作者管理。
不破坏现有 owner_user_id 模型，只做扩展。
"""
from __future__ import annotations

import logging
from typing import Literal

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collaboration import (
    CalendarEventCollaborator,
    CalendarEventComment,
    CustomerCollaborator,
    CustomerFollowup,
    ProjectActivity,
    ProjectCollaborator,
)
from app.models.calendar_event import CalendarEvent
from app.models.customer import Customer
from app.models.project import Project
from app.models.user import User

logger = logging.getLogger(__name__)

AccessRole = Literal["owner", "collaborator", "none"]


# ── 权限判断 ────────────────────────────────────────


async def get_project_access_role(db: AsyncSession, project_id: int, user_id: int) -> AccessRole:
    p = await db.get(Project, project_id)
    if not p:
        return "none"
    if p.initiator_user_id == user_id:
        return "owner"
    if p.owner_user_id == user_id:
        return "owner"
    row = (
        await db.execute(
            select(ProjectCollaborator.id)
            .where(ProjectCollaborator.project_id == project_id, ProjectCollaborator.user_id == user_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    return "collaborator" if row is not None else "none"


async def get_customer_access_role(db: AsyncSession, customer_id: int, user_id: int) -> AccessRole:
    c = await db.get(Customer, customer_id)
    if not c:
        return "none"
    if c.owner_user_id == user_id:
        return "owner"
    row = (
        await db.execute(
            select(CustomerCollaborator.id)
            .where(CustomerCollaborator.customer_id == customer_id, CustomerCollaborator.user_id == user_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    return "collaborator" if row is not None else "none"


async def get_calendar_event_access_role(db: AsyncSession, event_id: int, user_id: int) -> AccessRole:
    e = await db.get(CalendarEvent, event_id)
    if not e:
        return "none"
    if e.owner_user_id == user_id:
        return "owner"
    row = (
        await db.execute(
            select(CalendarEventCollaborator.id)
            .where(CalendarEventCollaborator.calendar_event_id == event_id, CalendarEventCollaborator.user_id == user_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    return "collaborator" if row is not None else "none"


async def require_at_least_collaborator(
    db: AsyncSession,
    resource_type: str,
    resource_id: int,
    user_id: int,
) -> AccessRole:
    """要求至少 collaborator 权限，否则抛 403。返回实际角色。"""
    if resource_type == "project":
        role = await get_project_access_role(db, resource_id, user_id)
    elif resource_type == "customer":
        role = await get_customer_access_role(db, resource_id, user_id)
    elif resource_type == "calendar_event":
        role = await get_calendar_event_access_role(db, resource_id, user_id)
    else:
        role = "none"
    if role == "none":
        raise HTTPException(status_code=403, detail="无权访问该资源")
    return role


async def require_owner(
    db: AsyncSession,
    resource_type: str,
    resource_id: int,
    user_id: int,
) -> None:
    """要求 owner 权限，否则抛 403。"""
    role = await require_at_least_collaborator(db, resource_type, resource_id, user_id)
    if role != "owner":
        raise HTTPException(status_code=403, detail="仅资源负责人可执行此操作")


# ── 可见性查询辅助 ──────────────────────────────────


def project_visible_filter(user_id: int):
    """返回 SQLAlchemy where 条件：initiator OR owner OR collaborator。"""
    collab_subq = (
        select(ProjectCollaborator.project_id)
        .where(ProjectCollaborator.user_id == user_id)
        .correlate(Project)
        .scalar_subquery()
    )
    return or_(
        Project.initiator_user_id == user_id,
        Project.owner_user_id == user_id,
        Project.id.in_(collab_subq),
    )


def customer_visible_filter(user_id: int):
    collab_subq = (
        select(CustomerCollaborator.customer_id)
        .where(CustomerCollaborator.user_id == user_id)
        .correlate(Customer)
        .scalar_subquery()
    )
    return or_(
        Customer.owner_user_id == user_id,
        Customer.id.in_(collab_subq),
    )


def calendar_event_visible_filter(user_id: int):
    collab_subq = (
        select(CalendarEventCollaborator.calendar_event_id)
        .where(CalendarEventCollaborator.user_id == user_id)
        .correlate(CalendarEvent)
        .scalar_subquery()
    )
    return or_(
        CalendarEvent.owner_user_id == user_id,
        CalendarEvent.id.in_(collab_subq),
    )


# ── 协作者 CRUD ────────────────────────────────────


async def _get_user_brief(db: AsyncSession, user_id: int) -> dict:
    u = await db.get(User, user_id)
    if not u:
        return {"display_name": None, "username": None}
    return {"display_name": getattr(u, "display_name", None) or u.username, "username": u.username}


async def add_project_collaborator(
    db: AsyncSession, project_id: int, user_id: int, created_by: int,
) -> ProjectCollaborator:
    """添加标准协作者关系（source of truth: project_collaborators）。
    AI 不得绕开本服务直接写表。
    """
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(status_code=404, detail="项目不存在")
    if p.owner_user_id == user_id:
        raise HTTPException(status_code=400, detail="不能将负责人添加为协作者")
    existing = (
        await db.execute(
            select(ProjectCollaborator)
            .where(ProjectCollaborator.project_id == project_id, ProjectCollaborator.user_id == user_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="该用户已是协作者")
    target = await db.get(User, user_id)
    if not target or not target.is_active:
        raise HTTPException(status_code=400, detail="目标用户不存在或已停用")
    row = ProjectCollaborator(project_id=project_id, user_id=user_id, created_by_user_id=created_by)
    db.add(row)
    await db.flush()
    await db.refresh(row)
    logger.info("collaboration: add project collaborator project_id=%s user_id=%s by=%s", project_id, user_id, created_by)
    return row


async def remove_project_collaborator(db: AsyncSession, project_id: int, user_id: int) -> None:
    """移除标准协作者关系。仅作用于 collaborator，不用于 owner/initiator 变更。"""
    row = (
        await db.execute(
            select(ProjectCollaborator)
            .where(ProjectCollaborator.project_id == project_id, ProjectCollaborator.user_id == user_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="协作者不存在")
    await db.delete(row)
    await db.flush()
    logger.info("collaboration: remove project collaborator project_id=%s user_id=%s", project_id, user_id)


async def list_project_collaborators(db: AsyncSession, project_id: int) -> list[dict]:
    rows = (
        await db.execute(
            select(ProjectCollaborator).where(ProjectCollaborator.project_id == project_id).order_by(ProjectCollaborator.id)
        )
    ).scalars().all()
    result = []
    for r in rows:
        brief = await _get_user_brief(db, r.user_id)
        result.append({
            "id": r.id,
            "user_id": r.user_id,
            "created_by_user_id": r.created_by_user_id,
            "created_at": r.created_at,
            **brief,
        })
    return result


async def add_customer_collaborator(
    db: AsyncSession, customer_id: int, user_id: int, created_by: int,
) -> CustomerCollaborator:
    c = await db.get(Customer, customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="客户不存在")
    if c.owner_user_id == user_id:
        raise HTTPException(status_code=400, detail="不能将负责人添加为协作者")
    existing = (
        await db.execute(
            select(CustomerCollaborator)
            .where(CustomerCollaborator.customer_id == customer_id, CustomerCollaborator.user_id == user_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="该用户已是协作者")
    target = await db.get(User, user_id)
    if not target or not target.is_active:
        raise HTTPException(status_code=400, detail="目标用户不存在或已停用")
    row = CustomerCollaborator(customer_id=customer_id, user_id=user_id, created_by_user_id=created_by)
    db.add(row)
    await db.flush()
    await db.refresh(row)
    logger.info("collaboration: add customer collaborator customer_id=%s user_id=%s by=%s", customer_id, user_id, created_by)
    return row


async def remove_customer_collaborator(db: AsyncSession, customer_id: int, user_id: int) -> None:
    row = (
        await db.execute(
            select(CustomerCollaborator)
            .where(CustomerCollaborator.customer_id == customer_id, CustomerCollaborator.user_id == user_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="协作者不存在")
    await db.delete(row)
    await db.flush()
    logger.info("collaboration: remove customer collaborator customer_id=%s user_id=%s", customer_id, user_id)


async def list_customer_collaborators(db: AsyncSession, customer_id: int) -> list[dict]:
    rows = (
        await db.execute(
            select(CustomerCollaborator).where(CustomerCollaborator.customer_id == customer_id).order_by(CustomerCollaborator.id)
        )
    ).scalars().all()
    result = []
    for r in rows:
        brief = await _get_user_brief(db, r.user_id)
        result.append({
            "id": r.id,
            "user_id": r.user_id,
            "created_by_user_id": r.created_by_user_id,
            "created_at": r.created_at,
            **brief,
        })
    return result


async def add_calendar_event_collaborator(
    db: AsyncSession, event_id: int, user_id: int, created_by: int,
) -> CalendarEventCollaborator:
    e = await db.get(CalendarEvent, event_id)
    if not e:
        raise HTTPException(status_code=404, detail="日程不存在")
    if e.owner_user_id == user_id:
        raise HTTPException(status_code=400, detail="不能将负责人添加为协作者")
    existing = (
        await db.execute(
            select(CalendarEventCollaborator)
            .where(CalendarEventCollaborator.calendar_event_id == event_id, CalendarEventCollaborator.user_id == user_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="该用户已是协作者")
    target = await db.get(User, user_id)
    if not target or not target.is_active:
        raise HTTPException(status_code=400, detail="目标用户不存在或已停用")
    row = CalendarEventCollaborator(calendar_event_id=event_id, user_id=user_id, created_by_user_id=created_by)
    db.add(row)
    await db.flush()
    await db.refresh(row)
    logger.info("collaboration: add calendar_event collaborator event_id=%s user_id=%s by=%s", event_id, user_id, created_by)
    return row


async def remove_calendar_event_collaborator(db: AsyncSession, event_id: int, user_id: int) -> None:
    row = (
        await db.execute(
            select(CalendarEventCollaborator)
            .where(CalendarEventCollaborator.calendar_event_id == event_id, CalendarEventCollaborator.user_id == user_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="协作者不存在")
    await db.delete(row)
    await db.flush()
    logger.info("collaboration: remove calendar_event collaborator event_id=%s user_id=%s", event_id, user_id)


async def list_calendar_event_collaborators(db: AsyncSession, event_id: int) -> list[dict]:
    rows = (
        await db.execute(
            select(CalendarEventCollaborator).where(CalendarEventCollaborator.calendar_event_id == event_id).order_by(CalendarEventCollaborator.id)
        )
    ).scalars().all()
    result = []
    for r in rows:
        brief = await _get_user_brief(db, r.user_id)
        result.append({
            "id": r.id,
            "user_id": r.user_id,
            "created_by_user_id": r.created_by_user_id,
            "created_at": r.created_at,
            **brief,
        })
    return result


# ── 附属协作记录 CRUD ──────────────────────────────


async def add_project_activity(
    db: AsyncSession, project_id: int, author_user_id: int, content: str, update_type: str = "note",
) -> ProjectActivity:
    row = ProjectActivity(
        project_id=project_id, author_user_id=author_user_id, content=content, update_type=update_type,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def list_project_activities(db: AsyncSession, project_id: int) -> list[dict]:
    rows = (
        await db.execute(
            select(ProjectActivity).where(ProjectActivity.project_id == project_id).order_by(ProjectActivity.created_at.desc())
        )
    ).scalars().all()
    result = []
    for r in rows:
        brief = await _get_user_brief(db, r.author_user_id) if r.author_user_id else {"display_name": None, "username": None}
        result.append({
            "id": r.id,
            "project_id": r.project_id,
            "author_user_id": r.author_user_id,
            "content": r.content,
            "update_type": r.update_type,
            "created_at": r.created_at,
            "author_display_name": brief.get("display_name"),
        })
    return result


async def add_customer_followup(
    db: AsyncSession, customer_id: int, author_user_id: int, content: str,
) -> CustomerFollowup:
    row = CustomerFollowup(customer_id=customer_id, author_user_id=author_user_id, content=content)
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def list_customer_followups(db: AsyncSession, customer_id: int) -> list[dict]:
    rows = (
        await db.execute(
            select(CustomerFollowup).where(CustomerFollowup.customer_id == customer_id).order_by(CustomerFollowup.created_at.desc())
        )
    ).scalars().all()
    result = []
    for r in rows:
        brief = await _get_user_brief(db, r.author_user_id) if r.author_user_id else {"display_name": None, "username": None}
        result.append({
            "id": r.id,
            "customer_id": r.customer_id,
            "author_user_id": r.author_user_id,
            "content": r.content,
            "created_at": r.created_at,
            "author_display_name": brief.get("display_name"),
        })
    return result


async def add_calendar_event_comment(
    db: AsyncSession, event_id: int, author_user_id: int, content: str,
) -> CalendarEventComment:
    row = CalendarEventComment(calendar_event_id=event_id, author_user_id=author_user_id, content=content)
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def list_calendar_event_comments(db: AsyncSession, event_id: int) -> list[dict]:
    rows = (
        await db.execute(
            select(CalendarEventComment).where(CalendarEventComment.calendar_event_id == event_id).order_by(CalendarEventComment.created_at.desc())
        )
    ).scalars().all()
    result = []
    for r in rows:
        brief = await _get_user_brief(db, r.author_user_id) if r.author_user_id else {"display_name": None, "username": None}
        result.append({
            "id": r.id,
            "calendar_event_id": r.calendar_event_id,
            "author_user_id": r.author_user_id,
            "content": r.content,
            "created_at": r.created_at,
            "author_display_name": brief.get("display_name"),
        })
    return result


# ── 附属协作记录删除（作者本人 or 资源 owner 可删）────


async def can_delete_activity_record(
    db: AsyncSession,
    resource_type: str,
    resource_id: int,
    record_author_user_id: int | None,
    operator_user_id: int,
) -> bool:
    """判断 operator 是否有权删除某条附属记录（作者本人 or 资源 owner）。"""
    if record_author_user_id == operator_user_id:
        return True
    if resource_type == "project":
        p = await db.get(Project, resource_id)
        return p is not None and p.owner_user_id == operator_user_id
    if resource_type == "customer":
        c = await db.get(Customer, resource_id)
        return c is not None and c.owner_user_id == operator_user_id
    if resource_type == "calendar_event":
        e = await db.get(CalendarEvent, resource_id)
        return e is not None and e.owner_user_id == operator_user_id
    return False


async def delete_project_activity(
    db: AsyncSession, project_id: int, update_id: int, operator_user_id: int,
) -> None:
    row = await db.get(ProjectActivity, update_id)
    if not row or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="项目动态不存在")
    ok = await can_delete_activity_record(db, "project", project_id, row.author_user_id, operator_user_id)
    if not ok:
        logger.warning("collaboration: delete denied for non-author collaborator user=%s project_update=%s", operator_user_id, update_id)
        raise HTTPException(status_code=403, detail="仅作者本人或项目负责人可删除该动态")
    await db.delete(row)
    await db.flush()
    logger.info("collaboration: project update deleted id=%s by user=%s", update_id, operator_user_id)


async def delete_customer_followup(
    db: AsyncSession, customer_id: int, followup_id: int, operator_user_id: int,
) -> None:
    row = await db.get(CustomerFollowup, followup_id)
    if not row or row.customer_id != customer_id:
        raise HTTPException(status_code=404, detail="客户跟进记录不存在")
    ok = await can_delete_activity_record(db, "customer", customer_id, row.author_user_id, operator_user_id)
    if not ok:
        logger.warning("collaboration: delete denied for non-author collaborator user=%s customer_followup=%s", operator_user_id, followup_id)
        raise HTTPException(status_code=403, detail="仅作者本人或客户负责人可删除该跟进记录")
    await db.delete(row)
    await db.flush()
    logger.info("collaboration: customer followup deleted id=%s by user=%s", followup_id, operator_user_id)


async def delete_calendar_event_comment(
    db: AsyncSession, event_id: int, comment_id: int, operator_user_id: int,
) -> None:
    row = await db.get(CalendarEventComment, comment_id)
    if not row or row.calendar_event_id != event_id:
        raise HTTPException(status_code=404, detail="日程评论不存在")
    ok = await can_delete_activity_record(db, "calendar_event", event_id, row.author_user_id, operator_user_id)
    if not ok:
        logger.warning("collaboration: delete denied for non-author collaborator user=%s calendar_event_comment=%s", operator_user_id, comment_id)
        raise HTTPException(status_code=403, detail="仅作者本人或日程负责人可删除该评论")
    await db.delete(row)
    await db.flush()
    logger.info("collaboration: calendar event comment deleted id=%s by user=%s", comment_id, operator_user_id)


# ── ownership 转移 ─────────────────────────────────


async def _validate_transfer_target(db: AsyncSession, target_user_id: int, current_owner_id: int) -> User:
    """校验转移目标用户：存在、启用、不能是自己。"""
    if target_user_id == current_owner_id:
        raise HTTPException(status_code=400, detail="不能将负责人转移给自己")
    target = await db.get(User, target_user_id)
    if not target or not target.is_active:
        raise HTTPException(status_code=400, detail="目标用户不存在或已停用")
    return target


async def transfer_project_owner(
    db: AsyncSession, project_id: int, operator_user_id: int, target_user_id: int,
) -> dict:
    """更换负责人（owner_user_id）。
    关键写操作必须经由业务层与审计，不允许 AI 直接改归属字段。
    """
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(status_code=404, detail="项目不存在")
    if p.owner_user_id != operator_user_id:
        raise HTTPException(status_code=403, detail="仅项目负责人可转移归属")
    target = await _validate_transfer_target(db, target_user_id, operator_user_id)

    old_owner_id = p.owner_user_id
    p.owner_user_id = target_user_id
    await db.flush()

    # 新 owner 若之前是 collaborator，移除
    existing = (
        await db.execute(
            select(ProjectCollaborator)
            .where(ProjectCollaborator.project_id == project_id, ProjectCollaborator.user_id == target_user_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing:
        await db.delete(existing)
        await db.flush()

    # 原 owner 自动加为 collaborator
    already_collab = (
        await db.execute(
            select(ProjectCollaborator.id)
            .where(ProjectCollaborator.project_id == project_id, ProjectCollaborator.user_id == old_owner_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if not already_collab:
        db.add(ProjectCollaborator(project_id=project_id, user_id=old_owner_id, created_by_user_id=operator_user_id))
        await db.flush()

    target_brief = await _get_user_brief(db, target_user_id)
    logger.info("collaboration: transfer project owner project_id=%s from=%s to=%s", project_id, old_owner_id, target_user_id)
    return {
        "project_id": project_id,
        "new_owner_user_id": target_user_id,
        "new_owner_display_name": target_brief.get("display_name"),
        "old_owner_user_id": old_owner_id,
    }


async def transfer_customer_owner(
    db: AsyncSession, customer_id: int, operator_user_id: int, target_user_id: int,
) -> dict:
    c = await db.get(Customer, customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="客户不存在")
    if c.owner_user_id != operator_user_id:
        raise HTTPException(status_code=403, detail="仅客户负责人可转移归属")
    target = await _validate_transfer_target(db, target_user_id, operator_user_id)

    old_owner_id = c.owner_user_id
    c.owner_user_id = target_user_id
    await db.flush()

    existing = (
        await db.execute(
            select(CustomerCollaborator)
            .where(CustomerCollaborator.customer_id == customer_id, CustomerCollaborator.user_id == target_user_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing:
        await db.delete(existing)
        await db.flush()

    already_collab = (
        await db.execute(
            select(CustomerCollaborator.id)
            .where(CustomerCollaborator.customer_id == customer_id, CustomerCollaborator.user_id == old_owner_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if not already_collab:
        db.add(CustomerCollaborator(customer_id=customer_id, user_id=old_owner_id, created_by_user_id=operator_user_id))
        await db.flush()

    target_brief = await _get_user_brief(db, target_user_id)
    logger.info("collaboration: transfer customer owner customer_id=%s from=%s to=%s", customer_id, old_owner_id, target_user_id)
    return {
        "customer_id": customer_id,
        "new_owner_user_id": target_user_id,
        "new_owner_display_name": target_brief.get("display_name"),
        "old_owner_user_id": old_owner_id,
    }


async def transfer_calendar_event_owner(
    db: AsyncSession, event_id: int, operator_user_id: int, target_user_id: int,
) -> dict:
    e = await db.get(CalendarEvent, event_id)
    if not e:
        raise HTTPException(status_code=404, detail="日程不存在")
    if e.owner_user_id != operator_user_id:
        raise HTTPException(status_code=403, detail="仅日程负责人可转移归属")
    target = await _validate_transfer_target(db, target_user_id, operator_user_id)

    old_owner_id = e.owner_user_id
    e.owner_user_id = target_user_id
    await db.flush()

    existing = (
        await db.execute(
            select(CalendarEventCollaborator)
            .where(CalendarEventCollaborator.calendar_event_id == event_id, CalendarEventCollaborator.user_id == target_user_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing:
        await db.delete(existing)
        await db.flush()

    already_collab = (
        await db.execute(
            select(CalendarEventCollaborator.id)
            .where(CalendarEventCollaborator.calendar_event_id == event_id, CalendarEventCollaborator.user_id == old_owner_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if not already_collab:
        db.add(CalendarEventCollaborator(calendar_event_id=event_id, user_id=old_owner_id, created_by_user_id=operator_user_id))
        await db.flush()

    target_brief = await _get_user_brief(db, target_user_id)
    logger.info("collaboration: transfer calendar_event owner event_id=%s from=%s to=%s", event_id, old_owner_id, target_user_id)
    return {
        "event_id": event_id,
        "new_owner_user_id": target_user_id,
        "new_owner_display_name": target_brief.get("display_name"),
        "old_owner_user_id": old_owner_id,
    }


# ── pending action（AI 二次确认）───────────────────


async def resolve_user_by_name(db: AsyncSession, name: str) -> dict:
    """按 display_name 或 username 模糊匹配用户。"""
    name = name.strip()
    if not name:
        return {"success": False, "message": "用户名不能为空"}
    exact = (
        await db.execute(
            select(User).where(
                or_(User.display_name == name, User.username == name),
                User.is_active.is_(True),
            )
        )
    ).scalars().all()
    if len(exact) == 1:
        u = exact[0]
        return {"success": True, "user_id": u.id, "display_name": u.display_name or u.username, "username": u.username}
    if len(exact) > 1:
        return {"success": False, "message": f"找到多个用户匹配「{name}」，请更精确指定", "candidates": [
            {"user_id": u.id, "display_name": u.display_name or u.username} for u in exact
        ]}
    fuzzy = (
        await db.execute(
            select(User).where(
                or_(User.display_name.ilike(f"%{name}%"), User.username.ilike(f"%{name}%")),
                User.is_active.is_(True),
            )
        )
    ).scalars().all()
    if len(fuzzy) == 1:
        u = fuzzy[0]
        return {"success": True, "user_id": u.id, "display_name": u.display_name or u.username, "username": u.username}
    if len(fuzzy) > 1:
        return {"success": False, "message": f"找到多个用户匹配「{name}」，请更精确指定", "candidates": [
            {"user_id": u.id, "display_name": u.display_name or u.username} for u in fuzzy
        ]}
    return {"success": False, "message": f"未找到用户「{name}」"}


async def create_pending_transfer(
    db: AsyncSession, actor_user_id: int, resource_type: str, resource_id: int,
    target_user_id: int, payload: dict | None = None,
) -> "PendingAiAction":
    from app.models.pending_ai_action import PendingAiAction

    # 过期旧的 pending
    old = (
        await db.execute(
            select(PendingAiAction).where(
                PendingAiAction.actor_user_id == actor_user_id,
                PendingAiAction.resource_type == resource_type,
                PendingAiAction.resource_id == resource_id,
                PendingAiAction.action_type == "transfer_owner",
                PendingAiAction.status == "pending",
            )
        )
    ).scalars().all()
    for o in old:
        o.status = "cancelled"
    await db.flush()

    row = PendingAiAction(
        actor_user_id=actor_user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        action_type="transfer_owner",
        target_user_id=target_user_id,
        payload_json=payload,
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    logger.info("collaboration: pending transfer created id=%s actor=%s %s/%s -> user=%s",
                row.id, actor_user_id, resource_type, resource_id, target_user_id)
    return row


async def get_latest_pending_transfer(db: AsyncSession, actor_user_id: int) -> "PendingAiAction | None":
    from app.models.pending_ai_action import PendingAiAction
    row = (
        await db.execute(
            select(PendingAiAction).where(
                PendingAiAction.actor_user_id == actor_user_id,
                PendingAiAction.action_type == "transfer_owner",
                PendingAiAction.status == "pending",
                PendingAiAction.expires_at > datetime.now(timezone.utc),
            ).order_by(PendingAiAction.id.desc()).limit(1)
        )
    ).scalar_one_or_none()
    return row


async def confirm_pending_transfer(db: AsyncSession, actor_user_id: int) -> dict:
    """确认最近一条待确认转移动作。"""
    from app.services.audit_log_service import write_audit_log
    pending = await get_latest_pending_transfer(db, actor_user_id)
    if not pending:
        return {"success": False, "message": "没有待确认的转移操作，或操作已过期"}

    rt = pending.resource_type
    rid = pending.resource_id
    target_uid = pending.target_user_id

    if rt == "project":
        result = await transfer_project_owner(db, rid, actor_user_id, target_uid)
    elif rt == "customer":
        result = await transfer_customer_owner(db, rid, actor_user_id, target_uid)
    elif rt == "calendar_event":
        result = await transfer_calendar_event_owner(db, rid, actor_user_id, target_uid)
    else:
        return {"success": False, "message": f"不支持的资源类型: {rt}"}

    pending.status = "confirmed"
    pending.confirmed_at = datetime.now(timezone.utc)
    await db.flush()

    await write_audit_log(
        db, action=f"{rt}_transfer_owner", actor_user_id=actor_user_id,
        target_type=rt, target_id=str(rid),
        detail=f"transferred ownership to user_id={target_uid}",
        metadata_json=result,
    )
    await write_audit_log(
        db, action="pending_transfer_action_confirmed", actor_user_id=actor_user_id,
        target_type="pending_ai_action", target_id=str(pending.id),
        detail=f"confirmed transfer {rt}/{rid} to user_id={target_uid}",
    )

    target_brief = await _get_user_brief(db, target_uid)
    type_label = {"project": "项目", "customer": "客户", "calendar_event": "日程"}.get(rt, rt)
    return {
        "success": True,
        "message": f"已成功将{type_label}的负责人转移给{target_brief.get('display_name', target_uid)}，你已自动保留为协作者。",
        **result,
    }


async def cancel_pending_transfer(db: AsyncSession, actor_user_id: int) -> dict:
    from app.services.audit_log_service import write_audit_log
    pending = await get_latest_pending_transfer(db, actor_user_id)
    if not pending:
        return {"success": False, "message": "没有待确认的转移操作"}
    pending.status = "cancelled"
    await db.flush()
    await write_audit_log(
        db, action="pending_transfer_action_cancelled", actor_user_id=actor_user_id,
        target_type="pending_ai_action", target_id=str(pending.id),
        detail="cancelled pending transfer",
    )
    logger.info("collaboration: pending transfer cancelled id=%s actor=%s", pending.id, actor_user_id)
    return {"success": True, "message": "已取消转移操作"}
