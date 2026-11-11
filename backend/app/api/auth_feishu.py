"""
当前用户飞书绑定查询：仅服务端部署注册；桌面 SQLite 不挂载本路由。
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services.feishu_identity_service import (
    list_bound_identities_for_user,
    _mask_open_id,
    _mask_union_id,
)

router = APIRouter(prefix="/auth", tags=["auth-feishu"])


@router.get("/my-feishu-bindings")
async def my_feishu_bindings(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """当前用户绑定的飞书身份列表（脱敏）。"""
    identities = await list_bound_identities_for_user(db, current_user.id)
    items = [
        {
            "identity_id": i.id,
            "tenant_key": i.tenant_key,
            "open_id_masked": _mask_open_id(i.open_id),
            "union_id_masked": _mask_union_id(i.union_id),
            "sender_name": i.sender_name,
            "bind_status": i.bind_status,
            "first_seen_at": i.first_seen_at.isoformat() if i.first_seen_at else None,
            "last_seen_at": i.last_seen_at.isoformat() if i.last_seen_at else None,
        }
        for i in identities
    ]
    return {"ok": True, "items": items}
