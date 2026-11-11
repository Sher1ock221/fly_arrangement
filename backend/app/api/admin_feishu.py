"""
管理员飞书相关 API：身份池、视角切换审计、导出等。
仅非桌面 SQLite（服务端）部署时由 main 注册。
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import require_admin
from app.db.session import get_db
from app.models.user import User
from app.models.feishu_identity_pool import FeishuIdentityPool
from app.schemas.admin import FeishuIdentityBindRequest, FeishuIdentityIgnoreRequest, SwitchContextLogRequest
from app.services.audit_log_service import write_audit_log
from app.services.auth_service import get_user_by_id
from app.services.feishu_identity_service import (
    bind_feishu_identity,
    ignore_feishu_identity,
    list_bound_identities_for_user,
    unbind_feishu_identity,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin-feishu"])


def _csv_line(row: list) -> str:
    out = io.StringIO()
    csv.writer(out, lineterminator="\n", quoting=csv.QUOTE_MINIMAL).writerow(row)
    return out.getvalue()


# ---------- 管理员视角切换：可切换用户列表 ----------
@router.get("/effective-users")
async def admin_effective_users(
    current_user: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """返回可切换视角的用户列表（id, username, display_name, role, is_active），供前端下拉框使用。"""
    from sqlalchemy import select
    result = await db.execute(
        select(User).where(User.is_active.is_(True)).order_by(User.id)
    )
    users = list(result.scalars().all())
    return {
        "ok": True,
        "items": [
            {"id": u.id, "username": u.username, "display_name": u.display_name, "role": u.role, "is_active": u.is_active}
            for u in users
        ],
    }


# ---------- 管理员视角切换：记录审计（前端切换时调用，避免每次请求写日志） ----------
@router.post("/switch-context-log")
async def admin_switch_context_log(
    request: Request,
    body: SwitchContextLogRequest,
    current_user: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """管理员切换视角时调用，写入 admin_switch_effective_user 审计。"""
    from fastapi import HTTPException
    target = await db.get(User, body.acting_user_id)
    if target is None or not target.is_active:
        raise HTTPException(status_code=400, detail="目标用户不存在或已禁用")
    await write_audit_log(
        db,
        action="admin_switch_effective_user",
        actor_user_id=current_user.id,
        actor_username=current_user.username,
        target_type="user",
        target_id=str(body.acting_user_id),
        detail=f"view_as user_id={body.acting_user_id}",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata_json={"from_user_id": current_user.id, "to_user_id": body.acting_user_id},
    )
    return {"ok": True}

@router.get("/users/{user_id}/feishu-bindings")
async def admin_get_user_feishu_bindings(
    user_id: int,
    request: Request,
    current_user: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """管理员查看某用户已绑定的飞书身份列表。"""
    from fastapi import HTTPException
    user = await get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    identities = await list_bound_identities_for_user(db, user_id)
    items = [
        {
            "identity_id": i.id,
            "tenant_key": i.tenant_key,
            "open_id": i.open_id,
            "union_id": i.union_id,
            "sender_name": i.sender_name,
            "first_seen_at": i.first_seen_at.isoformat() if i.first_seen_at else None,
            "last_seen_at": i.last_seen_at.isoformat() if i.last_seen_at else None,
        }
        for i in identities
    ]
    return {"ok": True, "items": items}


# ---------- 飞书身份池列表（增强：bound_user_id 筛选、附带 bound_user 信息） ----------
@router.get("/feishu-identities")
async def list_feishu_identities(
    request: Request,
    bind_status: str | None = Query(None, description="unbound / bound / ignored"),
    bound_user_id: int | None = Query(None, description="按绑定用户 ID 筛选"),
    q: str | None = Query(None, description="搜索 tenant_key / open_id / union_id / sender_name"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    current_user: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(FeishuIdentityPool)
    if bind_status and bind_status.strip():
        stmt = stmt.where(FeishuIdentityPool.bind_status == bind_status.strip())
    if bound_user_id is not None:
        stmt = stmt.where(FeishuIdentityPool.bound_user_id == bound_user_id)
    if q and q.strip():
        kw = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                FeishuIdentityPool.tenant_key.ilike(kw),
                FeishuIdentityPool.open_id.ilike(kw),
                FeishuIdentityPool.union_id.ilike(kw),
                FeishuIdentityPool.sender_name.ilike(kw),
            )
        )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one() or 0
    order_stmt = stmt.order_by(desc(FeishuIdentityPool.last_seen_at), desc(FeishuIdentityPool.id))
    result = await db.execute(order_stmt.offset((page - 1) * page_size).limit(page_size))
    rows = list(result.scalars().all())
    bound_ids = [r.bound_user_id for r in rows if r.bound_user_id is not None]
    users_map: dict[int, User] = {}
    if bound_ids:
        users_result = await db.execute(select(User).where(User.id.in_(bound_ids)))
        for u in users_result.scalars().all():
            users_map[u.id] = u

    items = []
    for r in rows:
        bound_user = None
        if r.bound_user_id is not None and r.bound_user_id in users_map:
            u = users_map[r.bound_user_id]
            bound_user = {"id": u.id, "username": u.username, "display_name": u.display_name}
        items.append({
            "id": r.id,
            "tenant_key": r.tenant_key,
            "open_id": r.open_id,
            "union_id": r.union_id,
            "feishu_user_id": r.feishu_user_id,
            "sender_name": r.sender_name,
            "chat_id": r.chat_id,
            "message_id": r.message_id,
            "bind_status": r.bind_status,
            "bound_user_id": r.bound_user_id,
            "bound_user": bound_user,
            "first_seen_at": r.first_seen_at.isoformat() if r.first_seen_at else None,
            "last_seen_at": r.last_seen_at.isoformat() if r.last_seen_at else None,
            "last_event_id": r.last_event_id,
            "remark": r.remark,
        })
    return {"ok": True, "page": page, "page_size": page_size, "total": total, "items": items}


# ---------- 绑定飞书身份 ----------
@router.post("/feishu-identities/{identity_id}/bind")
async def admin_bind_feishu_identity(
    identity_id: int,
    request: Request,
    body: FeishuIdentityBindRequest,
    current_user: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from fastapi import HTTPException
    try:
        identity = await bind_feishu_identity(db, identity_id, user_id=body.user_id, remark=body.remark)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    await write_audit_log(
        db,
        action="admin_bind_feishu_identity",
        actor_user_id=current_user.id,
        actor_username=current_user.username,
        target_type="feishu_identity",
        target_id=str(identity_id),
        detail=f"bound feishu_identity_id={identity_id} to user_id={body.user_id}",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata_json={"identity_id": identity_id, "user_id": body.user_id},
    )
    return {
        "ok": True,
        "identity": {
            "id": identity.id,
            "bind_status": identity.bind_status,
            "bound_user_id": identity.bound_user_id,
            "remark": identity.remark,
        },
    }


# ---------- 解绑飞书身份 ----------
@router.post("/feishu-identities/{identity_id}/unbind")
async def admin_unbind_feishu_identity(
    identity_id: int,
    request: Request,
    current_user: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from fastapi import HTTPException
    try:
        identity = await unbind_feishu_identity(db, identity_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    await write_audit_log(
        db,
        action="admin_unbind_feishu_identity",
        actor_user_id=current_user.id,
        actor_username=current_user.username,
        target_type="feishu_identity",
        target_id=str(identity_id),
        detail=f"unbound feishu_identity_id={identity_id}",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata_json={"identity_id": identity_id},
    )
    return {
        "ok": True,
        "identity": {
            "id": identity.id,
            "bind_status": identity.bind_status,
            "bound_user_id": identity.bound_user_id,
        },
    }


# ---------- 忽略飞书身份 ----------
@router.post("/feishu-identities/{identity_id}/ignore")
async def admin_ignore_feishu_identity(
    identity_id: int,
    request: Request,
    body: FeishuIdentityIgnoreRequest | None = None,
    current_user: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from fastapi import HTTPException
    remark = body.remark if body else None
    try:
        identity = await ignore_feishu_identity(db, identity_id, remark=remark)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    await write_audit_log(
        db,
        action="admin_ignore_feishu_identity",
        actor_user_id=current_user.id,
        actor_username=current_user.username,
        target_type="feishu_identity",
        target_id=str(identity_id),
        detail=f"ignored feishu_identity_id={identity_id}",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata_json={"identity_id": identity_id},
    )
    return {
        "ok": True,
        "identity": {
            "id": identity.id,
            "bind_status": identity.bind_status,
            "remark": identity.remark,
        },
    }


# ---------- 导出飞书身份池 CSV ----------
@router.get("/export/feishu-identities")
async def admin_export_feishu_identities(
    request: Request,
    q: str | None = Query(None),
    bind_status: str | None = Query(None),
    bound_user_id: int | None = Query(None),
    current_user: Any = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """导出飞书身份池为 CSV。仅管理员。"""
    stmt = select(FeishuIdentityPool)
    if bind_status and bind_status.strip():
        stmt = stmt.where(FeishuIdentityPool.bind_status == bind_status.strip())
    if bound_user_id is not None:
        stmt = stmt.where(FeishuIdentityPool.bound_user_id == bound_user_id)
    if q and q.strip():
        kw = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                FeishuIdentityPool.tenant_key.ilike(kw),
                FeishuIdentityPool.open_id.ilike(kw),
                FeishuIdentityPool.union_id.ilike(kw),
                FeishuIdentityPool.sender_name.ilike(kw),
            )
        )
    stmt = stmt.order_by(desc(FeishuIdentityPool.last_seen_at), desc(FeishuIdentityPool.id)).limit(10000)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    bound_ids = [r.bound_user_id for r in rows if r.bound_user_id is not None]
    users_map: dict[int, User] = {}
    if bound_ids:
        users_result = await db.execute(select(User).where(User.id.in_(bound_ids)))
        for u in users_result.scalars().all():
            users_map[u.id] = u
    lines = [
        _csv_line([
            "id", "tenant_key", "open_id", "union_id", "sender_name", "bind_status",
            "bound_user_id", "bound_username", "first_seen_at", "last_seen_at", "last_event_id",
        ]),
    ]
    for r in rows:
        bound_username = ""
        if r.bound_user_id and r.bound_user_id in users_map:
            bound_username = users_map[r.bound_user_id].username or ""
        lines.append(
            _csv_line([
                r.id,
                (r.tenant_key or "").replace("\n", " "),
                (r.open_id or "").replace("\n", " "),
                (r.union_id or "").replace("\n", " "),
                (r.sender_name or "").replace("\n", " "),
                r.bind_status or "",
                r.bound_user_id or "",
                bound_username,
                r.first_seen_at.isoformat() if r.first_seen_at else "",
                r.last_seen_at.isoformat() if r.last_seen_at else "",
                (r.last_event_id or "").replace("\n", " "),
            ])
        )
    body = "\r\n".join(lines).encode("utf-8-sig")
    await write_audit_log(
        db,
        action="admin_export_feishu_identities",
        actor_user_id=current_user.id,
        actor_username=current_user.username,
        target_type="system",
        detail=f"exported feishu identities count={len(rows)}",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    logger.info("admin.export: feishu identities exported count=%s", len(rows))
    return StreamingResponse(
        io.BytesIO(body),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="feishu_identities.csv"'},
    )
