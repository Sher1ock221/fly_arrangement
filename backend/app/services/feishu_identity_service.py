"""
飞书身份待绑定池：采集、查询、绑定/解绑/忽略。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feishu_identity_pool import FeishuIdentityPool
from app.models.user import User

logger = logging.getLogger(__name__)


def _mask_open_id(open_id: str | None, visible: int = 4) -> str:
    if not open_id or len(open_id) <= visible * 2:
        return "***"
    return f"{open_id[:visible]}***{open_id[-visible:]}"


def _mask_union_id(union_id: str | None, visible: int = 4) -> str:
    if not union_id or len(union_id) <= visible * 2:
        return "***"
    return f"{union_id[:visible]}***{union_id[-visible:]}"


async def count_bound_identities_for_user(db: AsyncSession, user_id: int) -> int:
    """某用户已绑定的飞书身份数量。"""
    r = await db.execute(
        select(func.count(FeishuIdentityPool.id)).where(
            FeishuIdentityPool.bound_user_id == user_id,
            FeishuIdentityPool.bind_status == "bound",
        )
    )
    return (r.scalar_one() or 0) or 0


async def list_bound_identities_for_user(db: AsyncSession, user_id: int) -> list[FeishuIdentityPool]:
    """某用户已绑定的飞书身份列表（bound 状态）。"""
    r = await db.execute(
        select(FeishuIdentityPool)
        .where(
            FeishuIdentityPool.bound_user_id == user_id,
            FeishuIdentityPool.bind_status == "bound",
        )
        .order_by(FeishuIdentityPool.last_seen_at.desc().nullslast(), FeishuIdentityPool.id.desc())
    )
    return list(r.scalars().all())


async def get_identity_by_id(db: AsyncSession, identity_id: int) -> FeishuIdentityPool | None:
    return await db.get(FeishuIdentityPool, identity_id)


async def bind_feishu_identity(
    db: AsyncSession,
    identity_id: int,
    *,
    user_id: int,
    remark: str | None = None,
) -> FeishuIdentityPool:
    identity = await get_identity_by_id(db, identity_id)
    if not identity:
        raise LookupError("飞书身份不存在")
    user = await db.get(User, user_id)
    if not user:
        raise LookupError("用户不存在")
    identity.bound_user_id = user_id
    identity.bind_status = "bound"
    if remark is not None:
        identity.remark = remark.strip() or None
    identity.updated_at = datetime.now(timezone.utc)
    await db.flush()
    logger.info(
        "admin.feishu_identity: bound identity_id=%s user_id=%s tenant_key=%s open_id=%s",
        identity_id,
        user_id,
        identity.tenant_key or "",
        _mask_open_id(identity.open_id),
    )
    return identity


async def unbind_feishu_identities_for_user(db: AsyncSession, user_id: int) -> int:
    """解除某用户的所有飞书绑定（删除账号前调用）。返回解绑数量。"""
    from sqlalchemy import update
    r = await db.execute(
        update(FeishuIdentityPool)
        .where(
            FeishuIdentityPool.bound_user_id == user_id,
            FeishuIdentityPool.bind_status == "bound",
        )
        .values(bound_user_id=None, bind_status="unbound", updated_at=datetime.now(timezone.utc))
    )
    await db.flush()
    count = r.rowcount if r.rowcount is not None else 0
    if count > 0:
        logger.info(
            "admin.feishu_identity: unbind all for user_id=%s count=%s (e.g. before user delete)",
            user_id,
            count,
        )
    return count


async def unbind_feishu_identity(
    db: AsyncSession,
    identity_id: int,
    *,
    remark: str | None = None,
) -> FeishuIdentityPool:
    identity = await get_identity_by_id(db, identity_id)
    if not identity:
        raise LookupError("飞书身份不存在")
    identity.bound_user_id = None
    identity.bind_status = "unbound"
    if remark is not None:
        identity.remark = remark.strip() or None
    identity.updated_at = datetime.now(timezone.utc)
    await db.flush()
    logger.info("admin.feishu_identity: unbound identity_id=%s", identity_id)
    return identity


async def ignore_feishu_identity(
    db: AsyncSession,
    identity_id: int,
    *,
    remark: str | None = None,
) -> FeishuIdentityPool:
    identity = await get_identity_by_id(db, identity_id)
    if not identity:
        raise LookupError("飞书身份不存在")
    identity.bind_status = "ignored"
    if remark is not None:
        identity.remark = remark.strip() or None
    identity.updated_at = datetime.now(timezone.utc)
    await db.flush()
    logger.info("admin.feishu_identity: ignored identity_id=%s", identity_id)
    return identity


async def resolve_bound_user_for_feishu_message(
    db: AsyncSession,
    *,
    open_id: str | None,
    union_id: str | None,
    tenant_key: str | None,
) -> tuple[FeishuIdentityPool | None, int | None]:
    """
    根据飞书事件身份解析是否已绑定系统用户。
    不依赖 Web 登录态、token 或 session，仅查 feishu_identity_pool 与 bound_user_id。
    用于飞书私聊「绑定用户免登录对话」：已绑定用户未登录 Web 时也可在飞书端与 AI 对话。
    返回 (identity, bound_user_id)。
    - 若 bind_status == 'bound'，bound_user_id 为对应用户 id；
    - 若 bind_status == 'ignored' 或 'unbound'，bound_user_id 为 None。
    - 若未找到身份记录，identity 为 None。
    """
    identity: FeishuIdentityPool | None = None
    if union_id:
        r = await db.execute(
            select(FeishuIdentityPool).where(FeishuIdentityPool.union_id == union_id).limit(1)
        )
        identity = r.scalar_one_or_none()
    if identity is None and tenant_key and open_id:
        r = await db.execute(
            select(FeishuIdentityPool).where(
                FeishuIdentityPool.tenant_key == tenant_key,
                FeishuIdentityPool.open_id == open_id,
            ).limit(1)
        )
        identity = r.scalar_one_or_none()
    if identity is None:
        return None, None
    if identity.bind_status == "bound" and identity.bound_user_id:
        return identity, identity.bound_user_id
    return identity, None


async def upsert_feishu_identity(
    db: AsyncSession,
    *,
    tenant_key: str | None = None,
    open_id: str | None = None,
    union_id: str | None = None,
    feishu_user_id: str | None = None,
    chat_id: str | None = None,
    message_id: str | None = None,
    event_id: str | None = None,
    sender_name: str | None = None,
    raw_payload: dict | list | None = None,
) -> FeishuIdentityPool | None:
    """
    根据 tenant_key+open_id 或 union_id 查找或创建待绑定身份，更新 last_seen_at / last_event_id 等。
    若 open_id 与 union_id 均无，返回 None（不新建）。
    """
    if not open_id and not union_id:
        return None

    now = datetime.now(timezone.utc)
    clauses = []
    if open_id:
        clauses.append(FeishuIdentityPool.open_id == open_id)
    if union_id:
        clauses.append(FeishuIdentityPool.union_id == union_id)

    existing = (
        await db.execute(
            select(FeishuIdentityPool).where(or_(*clauses)).order_by(FeishuIdentityPool.id.desc()).limit(1)
        )
    ).scalar_one_or_none()

    if existing:
        existing.last_seen_at = now
        existing.last_event_id = event_id or existing.last_event_id
        if message_id is not None:
            existing.message_id = message_id
        if chat_id is not None:
            existing.chat_id = chat_id
        if sender_name is not None:
            existing.sender_name = sender_name
        if raw_payload is not None:
            existing.raw_payload = raw_payload
        if tenant_key is not None:
            existing.tenant_key = tenant_key
        if union_id is not None:
            existing.union_id = union_id
        if feishu_user_id is not None:
            existing.feishu_user_id = feishu_user_id
        await db.flush()
        return existing

    row = FeishuIdentityPool(
        tenant_key=tenant_key,
        open_id=open_id,
        union_id=union_id,
        feishu_user_id=feishu_user_id,
        chat_id=chat_id,
        message_id=message_id,
        sender_name=sender_name,
        raw_payload=raw_payload,
        first_seen_at=now,
        last_seen_at=now,
        last_event_id=event_id,
        bind_status="unbound",
    )
    db.add(row)
    await db.flush()
    return row
