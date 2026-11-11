"""
有效用户上下文：current_user / effective_user_id / acting_as_user_id。
用于多用户数据隔离与管理员视角切换。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Request

from app.api.auth import get_current_user
from app.db.session import get_db
from app.models.user import User
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

ACTING_USER_HEADER = "x-acting-user-id"


@dataclass
class EffectiveUserContext:
    current_user: User
    effective_user_id: int
    acting_as_user_id: int | None  # 仅当管理员切换视角时有值


async def get_effective_user_context(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    x_acting_user_id: Annotated[str | None, Header(alias=ACTING_USER_HEADER)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> EffectiveUserContext:
    """
    解析当前请求的“有效用户 ID”：
    - 普通用户：effective_user_id = current_user.id，忽略 X-Acting-User-Id
    - 管理员未传头：effective_user_id = current_user.id
    - 管理员传 X-Acting-User-Id：校验用户存在且启用，effective_user_id = 该用户 id
    """
    effective_user_id = current_user.id
    acting_as_user_id: int | None = None

    if current_user.role == "admin" and x_acting_user_id is not None and str(x_acting_user_id).strip():
        raw = str(x_acting_user_id).strip()
        try:
            target_id = int(raw)
            if target_id <= 0:
                pass
            else:
                target = await db.get(User, target_id)
                if target is not None and target.is_active:
                    effective_user_id = target_id
                    acting_as_user_id = target_id
                    # 审计日志由前端切换时调用 POST /admin/switch-context-log 写入，避免每次请求都写
                    if target_id != current_user.id:
                        logger.info(
                            "admin.context: effective user actor=%s acting_as=%s path=%s",
                            current_user.id,
                            target_id,
                            request.url.path,
                        )
                else:
                    logger.warning("admin.context: invalid or inactive acting_user_id=%s", raw)
        except ValueError:
            logger.warning("admin.context: non-integer X-Acting-User-Id=%s", raw[:50])

    return EffectiveUserContext(
        current_user=current_user,
        effective_user_id=effective_user_id,
        acting_as_user_id=acting_as_user_id,
    )


async def require_effective_owner(
    ctx: EffectiveUserContext,
    owner_user_id: int | None,
    resource_type: str = "resource",
    resource_id: str | None = None,
) -> None:
    """校验当前 effective_user_id 是否拥有该资源；否则抛出 HTTPException。调用方在 403 时写 data_access_denied 审计。"""
    from fastapi import HTTPException
    if owner_user_id is None:
        raise HTTPException(status_code=404, detail=f"{resource_type}不存在")
    if owner_user_id != ctx.effective_user_id:
        raise HTTPException(status_code=403, detail="无权访问该数据")


async def write_data_access_denied_and_raise(
    ctx: EffectiveUserContext,
    owner_user_id: int,
    resource_type: str,
    resource_id: str | None,
    request: Request | None,
    db: AsyncSession,
) -> None:
    """写 data_access_denied 审计并抛出 403。在 require_effective_owner 校验失败后由路由调用。"""
    from fastapi import HTTPException
    from app.services.audit_log_service import write_audit_log
    await write_audit_log(
        db,
        action="data_access_denied",
        actor_user_id=ctx.current_user.id,
        actor_username=ctx.current_user.username,
        target_type=resource_type,
        target_id=resource_id,
        detail=f"user_id={ctx.current_user.id} attempted access owner_user_id={owner_user_id}",
        ip_address=request.client.host if request and request.client else None,
        user_agent=request.headers.get("user-agent") if request else None,
        metadata_json={"effective_user_id": ctx.effective_user_id, "resource_owner_id": owner_user_id},
    )
    raise HTTPException(status_code=403, detail="无权访问该数据")
