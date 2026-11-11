"""
管理员 API：用户管理、飞书身份池绑定/解绑/忽略、审计日志查询、系统状态、导出。
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import require_admin
from app.core.config import settings
from app.db.desktop_mode import is_desktop_sqlite_backend
from app.db.session import get_db
from app.models.user import User
from app.models.feishu_identity_pool import FeishuIdentityPool
from app.models.system_audit_log import SystemAuditLog
from app.schemas.admin import (
    UserCreateRequest,
    UserUpdateRequest,
    UserResetPasswordRequest,
)
from app.services.audit_log_service import write_audit_log
from app.services.auth_service import (
    create_user,
    list_users,
    get_user_by_id,
    update_user,
    reset_user_password,
    set_user_active,
    delete_user,
)
from app.services.feishu_identity_service import (
    unbind_feishu_identities_for_user,
    list_bound_identities_for_user,
    _mask_open_id,
    _mask_union_id,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


def _desktop_default_exclude_feishu_audit(action_filter: str | None) -> Any | None:
    """
    桌面 SQLite：列表/概览默认隐藏 action 以 feishu_ 开头的审计行（历史残留）；
    调用方显式传入 action 筛选时不加此条件，便于按需排查。
    """
    if not is_desktop_sqlite_backend():
        return None
    if action_filter and str(action_filter).strip():
        return None
    return ~SystemAuditLog.action.like("feishu_%")


def _user_item(r: User) -> dict[str, Any]:
    return {
        "id": r.id,
        "username": r.username,
        "display_name": r.display_name,
        "role": r.role,
        "is_active": r.is_active,
        "must_change_password": r.must_change_password,
        "last_login_at": r.last_login_at.isoformat() if r.last_login_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


# ---------- 管理员控制台概览 ----------
@router.get("/dashboard-summary")
async def admin_dashboard_summary(
    request: Request,
    current_user: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """管理员控制台首页概览：用户数、飞书身份统计、最近审计日志。"""
    from datetime import datetime, timezone, timedelta

    # 用户统计
    total_users = (await db.execute(select(func.count(User.id)))).scalar_one() or 0
    active_users = (
        await db.execute(select(func.count(User.id)).where(User.is_active.is_(True)))
    ).scalar_one() or 0
    admin_users = (
        await db.execute(select(func.count(User.id)).where(User.role == "admin"))
    ).scalar_one() or 0
    normal_users = (
        await db.execute(select(func.count(User.id)).where(User.role == "user"))
    ).scalar_one() or 0

    # 飞书身份统计（桌面 SQLite 不查表，固定为 0）
    if is_desktop_sqlite_backend():
        total_feishu = bound_feishu = unbound_feishu = ignored_feishu = 0
    else:
        total_feishu = (
            await db.execute(select(func.count(FeishuIdentityPool.id)))
        ).scalar_one() or 0
        bound_feishu = (
            await db.execute(
                select(func.count(FeishuIdentityPool.id)).where(FeishuIdentityPool.bind_status == "bound")
            )
        ).scalar_one() or 0
        unbound_feishu = (
            await db.execute(
                select(func.count(FeishuIdentityPool.id)).where(FeishuIdentityPool.bind_status == "unbound")
            )
        ).scalar_one() or 0
        ignored_feishu = (
            await db.execute(
                select(func.count(FeishuIdentityPool.id)).where(FeishuIdentityPool.bind_status == "ignored")
            )
        ).scalar_one() or 0

    # 最近 10 条审计日志（桌面 SQLite 默认排除飞书相关 action）
    recent_stmt = (
        select(SystemAuditLog)
        .order_by(desc(SystemAuditLog.created_at), desc(SystemAuditLog.id))
        .limit(10)
    )
    _excl = _desktop_default_exclude_feishu_audit(None)
    if _excl is not None:
        recent_stmt = recent_stmt.where(_excl)
    recent_logs_result = await db.execute(recent_stmt)
    recent_logs = list(recent_logs_result.scalars().all())
    recent_audit_logs = [
        {
            "id": r.id,
            "actor_username": r.actor_username,
            "action": r.action,
            "target_type": r.target_type,
            "target_id": r.target_id,
            "detail": (r.detail or "")[:200],
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in recent_logs
    ]

    # 近 7 天登录成功次数（可选）
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    recent_login_count = (
        await db.execute(
            select(func.count(SystemAuditLog.id)).where(
                SystemAuditLog.action == "login_success",
                SystemAuditLog.created_at >= week_ago,
            )
        )
    ).scalar_one() or 0

    logger.info("admin.dashboard: viewed summary by user_id=%s", current_user.id)

    return {
        "ok": True,
        "total_users": total_users,
        "active_users": active_users,
        "admin_users": admin_users,
        "normal_users": normal_users,
        "total_feishu_identities": total_feishu,
        "bound_feishu_identities": bound_feishu,
        "unbound_feishu_identities": unbound_feishu,
        "ignored_feishu_identities": ignored_feishu,
        "recent_audit_logs": recent_audit_logs,
        "recent_login_success_count": recent_login_count,
    }


@router.get("/users")
async def admin_list_users(
    request: Request,
    q: str | None = Query(None, description="搜索 username / display_name"),
    role: str | None = Query(None, description="admin / user"),
    is_active: bool | None = Query(None, description="按启用状态筛选"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    current_user: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, total = await list_users(db, page=page, page_size=page_size, q=q, role=role, is_active=is_active)
    if is_desktop_sqlite_backend():
        bound_map: dict[int, int] = {}
    else:
        bound_counts_stmt = (
            select(FeishuIdentityPool.bound_user_id, func.count(FeishuIdentityPool.id))
            .where(FeishuIdentityPool.bind_status == "bound", FeishuIdentityPool.bound_user_id.isnot(None))
            .group_by(FeishuIdentityPool.bound_user_id)
        )
        bound_result = await db.execute(bound_counts_stmt)
        bound_map = {r[0]: r[1] for r in bound_result.all()}
    user_items = []
    for r in rows:
        item = _user_item(r)
        item["bound_feishu_count"] = bound_map.get(r.id, 0)
        user_items.append(item)
    return {"ok": True, "page": page, "page_size": page_size, "total": total, "items": user_items}


# ---------- 创建用户 ----------
@router.post("/users")
async def admin_create_user(
    request: Request,
    body: UserCreateRequest,
    current_user: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        user = await create_user(
            db,
            username=body.username,
            password=body.password,
            display_name=body.display_name,
            role=body.role,
            is_active=body.is_active,
            must_change_password=body.must_change_password,
        )
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))
    await write_audit_log(
        db,
        action="admin_create_user",
        actor_user_id=current_user.id,
        actor_username=current_user.username,
        target_type="user",
        target_id=str(user.id),
        detail=f"created user username={user.username} role={user.role}",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata_json={"user_id": user.id, "username": user.username, "role": user.role},
    )
    return {"ok": True, "user": _user_item(user)}


# ---------- 编辑用户 ----------
@router.patch("/users/{user_id}")
async def admin_update_user(
    user_id: int,
    request: Request,
    body: UserUpdateRequest,
    current_user: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from fastapi import HTTPException
    try:
        user = await update_user(
            db,
            user_id,
            display_name=body.display_name,
            role=body.role,
            is_active=body.is_active,
            must_change_password=body.must_change_password,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="用户不存在")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await write_audit_log(
        db,
        action="admin_update_user",
        actor_user_id=current_user.id,
        actor_username=current_user.username,
        target_type="user",
        target_id=str(user_id),
        detail=f"updated user user_id={user_id}",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata_json={"user_id": user_id},
    )
    return {"ok": True, "user": _user_item(user)}


# ---------- 重置密码 ----------
@router.post("/users/{user_id}/reset-password")
async def admin_reset_password(
    user_id: int,
    request: Request,
    body: UserResetPasswordRequest,
    current_user: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from fastapi import HTTPException
    try:
        user = await reset_user_password(
            db,
            user_id,
            new_password=body.new_password,
            must_change_password=body.must_change_password,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="用户不存在")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await write_audit_log(
        db,
        action="admin_reset_user_password",
        actor_user_id=current_user.id,
        actor_username=current_user.username,
        target_type="user",
        target_id=str(user_id),
        detail=f"reset password for user_id={user_id}",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata_json={"user_id": user_id},
    )
    return {"ok": True, "user": _user_item(user)}


# ---------- 启用/禁用用户 ----------
@router.post("/users/{user_id}/set-active")
async def admin_set_user_active(
    user_id: int,
    request: Request,
    is_active: bool = Query(..., description="true=启用, false=禁用"),
    current_user: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from fastapi import HTTPException
    try:
        user = await set_user_active(db, user_id, is_active=is_active)
    except LookupError:
        raise HTTPException(status_code=404, detail="用户不存在")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await write_audit_log(
        db,
        action="admin_set_user_active",
        actor_user_id=current_user.id,
        actor_username=current_user.username,
        target_type="user",
        target_id=str(user_id),
        detail=f"set user active user_id={user_id} is_active={is_active}",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata_json={"user_id": user_id, "is_active": is_active},
    )
    return {"ok": True, "user": _user_item(user)}


# ---------- 删除用户（管理员） ----------
@router.delete("/users/{user_id}")
async def admin_delete_user(
    user_id: int,
    request: Request,
    current_user: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """删除用户。不可删自己、不可删唯一管理员、不可删仍有归属资源的用户；删除前自动解绑飞书。"""
    from fastapi import HTTPException
    try:
        result = await delete_user(
            db,
            user_id,
            actor_user_id=current_user.id,
            actor_username=current_user.username,
            unbind_feishu_fn=unbind_feishu_identities_for_user,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="用户不存在")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await write_audit_log(
        db,
        action="admin_delete_user",
        actor_user_id=current_user.id,
        actor_username=current_user.username,
        target_type="user",
        target_id=str(user_id),
        detail=f"deleted user username={result['username']} feishu_unbound={result['feishu_unbound_count']}",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata_json={"user_id": user_id, "username": result["username"], "feishu_unbound_count": result["feishu_unbound_count"]},
    )
    return {"ok": True, "message": "账号已删除"}


# ---------- 用户详情（管理员） ----------
@router.get("/users/{user_id}")
async def admin_get_user_detail(
    user_id: int,
    request: Request,
    current_user: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """管理员查看用户详情：基础信息、飞书绑定摘要、可选数量统计。"""
    from fastapi import HTTPException
    from app.models.project import Project
    from app.models.customer import Customer
    from app.models.chat import Conversation
    from app.models.calendar_event import CalendarEvent

    user = await get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if is_desktop_sqlite_backend():
        bound_list: list[dict[str, Any]] = []
    else:
        bindings = await list_bound_identities_for_user(db, user_id)
        bound_list = [
            {
                "identity_id": i.id,
                "tenant_key": i.tenant_key,
                "open_id_masked": _mask_open_id(i.open_id),
                "union_id_masked": _mask_union_id(i.union_id),
                "sender_name": i.sender_name,
                "last_seen_at": i.last_seen_at.isoformat() if i.last_seen_at else None,
            }
            for i in bindings
        ]

    # 可选数量统计
    project_count = (await db.execute(select(func.count(Project.id)).where(Project.owner_user_id == user_id))).scalar_one() or 0
    customer_count = (await db.execute(select(func.count(Customer.id)).where(Customer.owner_user_id == user_id))).scalar_one() or 0
    conversation_count = (await db.execute(select(func.count(Conversation.id)).where(Conversation.owner_user_id == user_id))).scalar_one() or 0
    calendar_event_count = (await db.execute(select(func.count(CalendarEvent.id)).where(CalendarEvent.owner_user_id == user_id))).scalar_one() or 0

    logger.info("admin.user: viewed user detail user_id=%s", user_id)

    out = _user_item(user)
    out["bound_feishu_identities"] = bound_list
    out["bound_feishu_count"] = len(bound_list)
    out["project_count"] = project_count
    out["customer_count"] = customer_count
    out["conversation_count"] = conversation_count
    out["calendar_event_count"] = calendar_event_count
    return {"ok": True, "user": out}


# ---------- 审计日志查询 ----------
@router.get("/audit-logs")
async def admin_list_audit_logs(
    request: Request,
    action: str | None = Query(None, description="按 action 筛选（精确或前缀）"),
    target_type: str | None = Query(None, description="按 target_type 筛选"),
    actor_user_id: int | None = Query(None),
    q: str | None = Query(None, description="模糊搜索 actor_username / detail"),
    start_date: str | None = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: str | None = Query(None, description="结束日期 YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    current_user: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from datetime import datetime as dt, timezone
    stmt = select(SystemAuditLog)
    count_stmt = select(func.count(SystemAuditLog.id))
    _excl_logs = _desktop_default_exclude_feishu_audit(action)
    if _excl_logs is not None:
        stmt = stmt.where(_excl_logs)
        count_stmt = count_stmt.where(_excl_logs)
    if action and action.strip():
        act = action.strip()
        if "%" in act or "*" in act:
            stmt = stmt.where(SystemAuditLog.action.ilike(act.replace("*", "%")))
            count_stmt = count_stmt.where(SystemAuditLog.action.ilike(act.replace("*", "%")))
        else:
            stmt = stmt.where(SystemAuditLog.action == act)
            count_stmt = count_stmt.where(SystemAuditLog.action == act)
    if target_type and target_type.strip():
        stmt = stmt.where(SystemAuditLog.target_type == target_type.strip())
        count_stmt = count_stmt.where(SystemAuditLog.target_type == target_type.strip())
    if actor_user_id is not None:
        stmt = stmt.where(SystemAuditLog.actor_user_id == actor_user_id)
        count_stmt = count_stmt.where(SystemAuditLog.actor_user_id == actor_user_id)
    if q and q.strip():
        kw = f"%{q.strip()}%"
        cond = or_(
            SystemAuditLog.actor_username.ilike(kw),
            (SystemAuditLog.detail.isnot(None)) & (SystemAuditLog.detail.ilike(kw)),
        )
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    if start_date and start_date.strip():
        try:
            start_dt = dt.fromisoformat(start_date.strip() + "T00:00:00+00:00")
            stmt = stmt.where(SystemAuditLog.created_at >= start_dt)
            count_stmt = count_stmt.where(SystemAuditLog.created_at >= start_dt)
        except ValueError:
            pass
    if end_date and end_date.strip():
        try:
            end_dt = dt.fromisoformat(end_date.strip() + "T23:59:59.999999+00:00")
            stmt = stmt.where(SystemAuditLog.created_at <= end_dt)
            count_stmt = count_stmt.where(SystemAuditLog.created_at <= end_dt)
        except ValueError:
            pass
    total = (await db.execute(count_stmt)).scalar_one() or 0
    stmt = stmt.order_by(desc(SystemAuditLog.created_at), desc(SystemAuditLog.id))
    result = await db.execute(stmt.offset((page - 1) * page_size).limit(page_size))
    rows = list(result.scalars().all())
    items = [
        {
            "id": r.id,
            "actor_user_id": r.actor_user_id,
            "actor_username": r.actor_username,
            "action": r.action,
            "target_type": r.target_type,
            "target_id": r.target_id,
            "detail": r.detail,
            "ip_address": r.ip_address,
            "user_agent": r.user_agent,
            "metadata_json": r.metadata_json,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return {"ok": True, "page": page, "page_size": page_size, "total": total, "items": items}


@router.get("/audit-logs/{log_id}")
async def admin_get_audit_log_detail(
    log_id: int,
    request: Request,
    current_user: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """管理员查看单条审计日志详情。"""
    from fastapi import HTTPException
    row = await db.get(SystemAuditLog, log_id)
    if not row:
        raise HTTPException(status_code=404, detail="审计记录不存在")
    logger.info("admin.audit: viewed log detail log_id=%s", log_id)
    return {
        "ok": True,
        "item": {
            "id": row.id,
            "actor_user_id": row.actor_user_id,
            "actor_username": row.actor_username,
            "action": row.action,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "detail": row.detail,
            "ip_address": row.ip_address,
            "user_agent": row.user_agent,
            "metadata_json": row.metadata_json,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        },
    }


# ---------- 系统状态（管理员） ----------
@router.get("/system-status")
async def admin_system_status(
    request: Request,
    current_user: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """系统基础状态，供管理员控制台「系统状态」页使用。"""
    from app.services.auth_service import get_user_by_username

    warnings: list[str] = []
    database_connected = False
    database_url_masked = ""
    try:
        await db.execute(text("SELECT 1"))
        database_connected = True
        url = getattr(settings, "DATABASE_URL", "") or ""
        if "@" in url:
            parts = url.split("@", 1)
            database_url_masked = "***@" + (parts[1] if len(parts) > 1 else "***")
        else:
            database_url_masked = "***" if url else ""
    except Exception as e:
        warnings.append(f"数据库连接异常: {e!s}")

    desk = is_desktop_sqlite_backend()

    total_users = (await db.execute(select(func.count(User.id)))).scalar_one() or 0
    total_active = (
        await db.execute(select(func.count(User.id)).where(User.is_active.is_(True)))
    ).scalar_one() or 0
    if desk:
        total_feishu = 0
        total_bound_feishu = 0
    else:
        total_feishu = (
            await db.execute(select(func.count(FeishuIdentityPool.id)))
        ).scalar_one() or 0
        total_bound_feishu = (
            await db.execute(
                select(func.count(FeishuIdentityPool.id)).where(
                    FeishuIdentityPool.bind_status == "bound"
                )
            )
        ).scalar_one() or 0

    default_admin = await get_user_by_username(db, "admin123")
    default_admin_exists = default_admin is not None
    if default_admin_exists and getattr(default_admin, "must_change_password", True):
        warnings.append("检测到旧版本预置管理员 admin123 尚需修改密码。")

    feishu_config_present = (
        False
        if desk
        else bool(getattr(settings, "FEISHU_APP_ID", "") and getattr(settings, "FEISHU_APP_SECRET", ""))
    )
    from app.models.ai_config import AIConfig
    model_config_row = (
        await db.execute(select(func.count(AIConfig.id)).where(AIConfig.is_active.is_(True)))
    ).scalar_one() or 0
    model_config_present = model_config_row > 0

    now = datetime.now(timezone.utc)
    uptime_seconds = None
    if hasattr(request.app.state, "start_time") and request.app.state.start_time:
        uptime_seconds = int((now - request.app.state.start_time).total_seconds())

    from app.services.ollama_service import get_ollama_status
    ollama = get_ollama_status()
    if (not desk) and (not ollama.get("model_ready")) and ollama.get("last_error"):
        warnings.append(f"AI 预热未就绪: {ollama.get('last_error')}")

    logger.info("admin.system: viewed system-status by user_id=%s", current_user.id)
    return {
        "ok": True,
        "app_name": "Fly Arrangement",
        "app_version": getattr(settings, "APP_VERSION", "0.1.0"),
        "environment": getattr(settings, "ENVIRONMENT", "dev"),
        "database_connected": database_connected,
        "database_url_masked": database_url_masked or None,
        "default_admin_exists": default_admin_exists,
        "total_users": total_users,
        "total_active_users": total_active,
        "total_feishu_identities": total_feishu,
        "total_bound_feishu_identities": total_bound_feishu,
        "feishu_config_present": feishu_config_present,
        "feishu_desktop_disabled": bool(desk),
        "model_config_present": model_config_present,
        "ollama_reachable": ollama.get("ollama_reachable", False),
        "model_ready": ollama.get("model_ready", False),
        "last_warmup_at": ollama.get("last_warmup_at"),
        "current_server_time": now.isoformat(),
        "uptime_seconds": uptime_seconds,
        "warnings": warnings,
    }


# ---------- 系统信息（管理员） ----------
@router.get("/system-info")
async def admin_system_info(
    request: Request,
    current_user: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """系统说明信息，供前端「系统信息」页展示。"""
    desk = is_desktop_sqlite_backend()
    if desk:
        features = [
            "用户与权限（管理员/普通用户）",
            "多用户数据隔离（owner_user_id）",
            "项目 / 客户 / 日程 / 对话",
            "本地提醒与 AI 助手（Ollama）",
            "审计日志与导出",
        ]
        enabled_modules = ["auth", "admin", "projects", "customers", "calendar", "chat", "ai", "audit"]
        notes = [
            "桌面单机版不启用飞书同步、Webhook 与飞书身份池。",
            "仅管理员可访问系统状态、导出与用户管理。",
            "普通用户仅可访问个人设置与自身数据。",
        ]
    else:
        features = [
            "用户与权限（管理员/普通用户）",
            "多用户数据隔离（owner_user_id）",
            "管理员视角切换",
            "飞书身份池与手动绑定",
            "项目 / 客户 / 日程 / 对话",
            "AI 助手与飞书 Webhook",
            "审计日志与导出",
        ]
        enabled_modules = ["auth", "admin", "projects", "customers", "calendar", "chat", "ai", "feishu", "audit"]
        notes = [
            "仅管理员可访问系统状态、导出、用户管理、飞书身份池。",
            "普通用户仅可访问个人设置与自身数据。",
        ]
    return {
        "ok": True,
        "app_name": "Fly Arrangement",
        "app_version": getattr(settings, "APP_VERSION", "0.1.0"),
        "build_time": None,
        "environment": getattr(settings, "ENVIRONMENT", "dev"),
        "features": features,
        "enabled_modules": enabled_modules,
        "notes": notes,
    }


# ---------- 导出用户列表 CSV ----------
def _csv_line(row: list) -> str:
    out = io.StringIO()
    csv.writer(out, lineterminator="\n", quoting=csv.QUOTE_MINIMAL).writerow(row)
    return out.getvalue()


@router.get("/export/users")
async def admin_export_users(
    request: Request,
    q: str | None = Query(None),
    role: str | None = Query(None),
    is_active: bool | None = Query(None),
    current_user: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """导出用户列表为 CSV。仅管理员。"""
    rows, _ = await list_users(
        db, page=1, page_size=10000, q=q, role=role, is_active=is_active
    )
    lines = [
        _csv_line(["id", "username", "display_name", "role", "is_active", "must_change_password", "last_login_at", "created_at"]),
    ]
    for r in rows:
        lines.append(
            _csv_line([
                r.id,
                r.username or "",
                (r.display_name or "").replace("\n", " "),
                r.role or "",
                str(r.is_active),
                str(r.must_change_password),
                r.last_login_at.isoformat() if r.last_login_at else "",
                r.created_at.isoformat() if r.created_at else "",
            ])
        )
    body = "\r\n".join(lines).encode("utf-8-sig")
    await write_audit_log(
        db,
        action="admin_export_users",
        actor_user_id=current_user.id,
        actor_username=current_user.username,
        target_type="system",
        detail=f"exported users count={len(rows)}",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    logger.info("admin.export: users exported count=%s by user_id=%s", len(rows), current_user.id)
    return StreamingResponse(
        io.BytesIO(body),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="users.csv"'},
    )


# ---------- 导出审计日志 CSV ----------
@router.get("/export/audit-logs")
async def admin_export_audit_logs(
    request: Request,
    action: str | None = Query(None),
    target_type: str | None = Query(None),
    actor_user_id: int | None = Query(None),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    q: str | None = Query(None),
    current_user: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """导出审计日志为 CSV。仅管理员。"""
    from datetime import datetime as dt
    stmt = select(SystemAuditLog)
    _excl_export = _desktop_default_exclude_feishu_audit(action)
    if _excl_export is not None:
        stmt = stmt.where(_excl_export)
    if action and action.strip():
        act = action.strip()
        if "%" in act or "*" in act:
            stmt = stmt.where(SystemAuditLog.action.ilike(act.replace("*", "%")))
        else:
            stmt = stmt.where(SystemAuditLog.action == act)
    if target_type and target_type.strip():
        stmt = stmt.where(SystemAuditLog.target_type == target_type.strip())
    if actor_user_id is not None:
        stmt = stmt.where(SystemAuditLog.actor_user_id == actor_user_id)
    if q and q.strip():
        kw = f"%{q.strip()}%"
        cond = or_(
            SystemAuditLog.actor_username.ilike(kw),
            (SystemAuditLog.detail.isnot(None)) & (SystemAuditLog.detail.ilike(kw)),
        )
        stmt = stmt.where(cond)
    if start_date and start_date.strip():
        try:
            start_dt = dt.fromisoformat(start_date.strip() + "T00:00:00+00:00")
            stmt = stmt.where(SystemAuditLog.created_at >= start_dt)
        except ValueError:
            pass
    if end_date and end_date.strip():
        try:
            end_dt = dt.fromisoformat(end_date.strip() + "T23:59:59.999999+00:00")
            stmt = stmt.where(SystemAuditLog.created_at <= end_dt)
        except ValueError:
            pass
    stmt = stmt.order_by(desc(SystemAuditLog.created_at), desc(SystemAuditLog.id)).limit(10000)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    lines = [
        _csv_line([
            "id", "actor_user_id", "actor_username", "action", "target_type", "target_id",
            "detail", "ip_address", "user_agent", "created_at",
        ]),
    ]
    for r in rows:
        detail_clean = (r.detail or "").replace("\n", " ").replace("\r", "")
        ua_clean = (r.user_agent or "").replace("\n", " ").replace("\r", "")[:500]
        lines.append(
            _csv_line([
                r.id,
                r.actor_user_id or "",
                (r.actor_username or "").replace("\n", " "),
                r.action or "",
                (r.target_type or "").replace("\n", " "),
                (r.target_id or "").replace("\n", " "),
                detail_clean,
                (r.ip_address or "").replace("\n", " "),
                ua_clean,
                r.created_at.isoformat() if r.created_at else "",
            ])
        )
    body = "\r\n".join(lines).encode("utf-8-sig")
    await write_audit_log(
        db,
        action="admin_export_audit_logs",
        actor_user_id=current_user.id,
        actor_username=current_user.username,
        target_type="system",
        detail=f"exported audit logs count={len(rows)}",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    logger.info("admin.export: audit logs exported count=%s", len(rows))
    return StreamingResponse(
        io.BytesIO(body),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="audit_logs.csv"'},
    )
