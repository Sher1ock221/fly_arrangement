"""
认证服务：密码哈希、校验、默认管理员初始化、用户删除。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from passlib.context import CryptContext
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    result = await db.execute(select(User).where(User.username == username).limit(1))
    return result.scalar_one_or_none()


async def list_users(
    db: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 20,
    q: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
) -> tuple[list[User], int]:
    stmt = select(User)
    count_stmt = select(func.count(User.id))
    if q and q.strip():
        kw = f"%{q.strip()}%"
        cond = or_(User.username.ilike(kw), User.display_name.ilike(kw))
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    if role and role.strip():
        stmt = stmt.where(User.role == role.strip())
        count_stmt = count_stmt.where(User.role == role.strip())
    if is_active is not None:
        stmt = stmt.where(User.is_active.is_(is_active))
        count_stmt = count_stmt.where(User.is_active.is_(is_active))
    total = (await db.execute(count_stmt)).scalar_one() or 0
    stmt = stmt.order_by(User.created_at.desc(), User.id.desc())
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    return rows, total


async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    return await db.get(User, user_id)


async def count_admin_users(db: AsyncSession, *, active_only: bool = False) -> int:
    stmt = select(func.count(User.id)).where(User.role == "admin")
    if active_only:
        stmt = stmt.where(User.is_active.is_(True))
    return (await db.execute(stmt)).scalar_one() or 0


async def create_user(
    db: AsyncSession,
    *,
    username: str,
    password: str,
    display_name: str | None = None,
    role: str = "user",
    is_active: bool = True,
    must_change_password: bool = True,
) -> User:
    username = username.strip()
    if not username:
        raise ValueError("username 不能为空")
    if not password or len(password) < 6:
        raise ValueError("password 至少 6 位")
    if role not in ("admin", "user"):
        raise ValueError("role 只允许 admin / user")
    existing = await get_user_by_username(db, username)
    if existing:
        raise ValueError("用户名已存在")
    user = User(
        username=username,
        password_hash=hash_password(password),
        display_name=display_name or None,
        role=role,
        is_active=is_active,
        must_change_password=must_change_password,
    )
    db.add(user)
    await db.flush()
    logger.info("admin.user: created user username=%s role=%s", user.username, user.role)
    return user


async def update_user(
    db: AsyncSession,
    user_id: int,
    *,
    display_name: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
    must_change_password: bool | None = None,
) -> User:
    user = await get_user_by_id(db, user_id)
    if not user:
        raise LookupError("用户不存在")
    admin_count = await count_admin_users(db, active_only=True)
    if user.role == "admin" and admin_count <= 1:
        if role is not None and role != "admin":
            logger.warning("admin.user: blocked demoting last admin user_id=%s", user_id)
            raise ValueError("不能将系统唯一管理员降为普通用户")
        if is_active is False:
            logger.warning("admin.user: blocked disabling last admin user_id=%s", user_id)
            raise ValueError("不能禁用系统唯一管理员")
    if display_name is not None:
        user.display_name = display_name.strip() or None
    if role is not None:
        user.role = role
    if is_active is not None:
        user.is_active = is_active
    if must_change_password is not None:
        user.must_change_password = must_change_password
    user.updated_at = datetime.now(timezone.utc)
    await db.flush()
    logger.info("admin.user: updated user user_id=%s", user_id)
    return user


async def reset_user_password(
    db: AsyncSession,
    user_id: int,
    *,
    new_password: str,
    must_change_password: bool = True,
) -> User:
    if not new_password or len(new_password) < 6:
        raise ValueError("新密码至少 6 位")
    user = await get_user_by_id(db, user_id)
    if not user:
        raise LookupError("用户不存在")
    user.password_hash = hash_password(new_password)
    user.must_change_password = must_change_password
    user.updated_at = datetime.now(timezone.utc)
    await db.flush()
    logger.info("admin.user: reset password for user_id=%s", user_id)
    return user


async def set_user_active(db: AsyncSession, user_id: int, *, is_active: bool) -> User:
    user = await get_user_by_id(db, user_id)
    if not user:
        raise LookupError("用户不存在")
    if user.role == "admin" and not is_active:
        admin_count = await count_admin_users(db, active_only=True)
        if admin_count <= 1:
            logger.warning("admin.user: blocked disabling last admin user_id=%s", user_id)
            raise ValueError("不能禁用系统唯一管理员")
    user.is_active = is_active
    user.updated_at = datetime.now(timezone.utc)
    await db.flush()
    logger.info("admin.user: set user active user_id=%s is_active=%s", user_id, is_active)
    return user


async def update_self_profile(
    db: AsyncSession,
    user_id: int,
    *,
    display_name: str | None = None,
) -> User:
    """用户修改自己的资料（仅 display_name）。"""
    user = await get_user_by_id(db, user_id)
    if not user:
        raise LookupError("用户不存在")
    if display_name is not None:
        user.display_name = display_name.strip() or None
    user.updated_at = datetime.now(timezone.utc)
    await db.flush()
    logger.info("user.profile: updated profile user_id=%s", user_id)
    return user


async def change_self_password(
    db: AsyncSession,
    user_id: int,
    *,
    old_password: str,
    new_password: str,
    clear_must_change: bool = True,
) -> User:
    """用户修改自己的密码；校验旧密码正确。"""
    if not new_password or len(new_password) < 6:
        raise ValueError("新密码至少 6 位")
    user = await get_user_by_id(db, user_id)
    if not user:
        raise LookupError("用户不存在")
    if not verify_password(old_password, user.password_hash):
        logger.warning("user.security: change password failed user_id=%s reason=wrong_old_password", user_id)
        raise ValueError("当前密码错误")
    user.password_hash = hash_password(new_password)
    if clear_must_change:
        user.must_change_password = False
    user.updated_at = datetime.now(timezone.utc)
    await db.flush()
    logger.info("user.security: password changed user_id=%s", user_id)
    return user


async def count_owned_resources_for_user(db: AsyncSession, user_id: int) -> dict[str, int]:
    """统计某用户作为 owner 的资源数量（项目、客户、日程、会话）。用于删除前校验。"""
    from app.models.calendar_event import CalendarEvent
    from app.models.chat import Conversation
    from app.models.customer import Customer
    from app.models.project import Project

    projects = (await db.execute(select(func.count(Project.id)).where(Project.owner_user_id == user_id))).scalar_one() or 0
    customers = (await db.execute(select(func.count(Customer.id)).where(Customer.owner_user_id == user_id))).scalar_one() or 0
    calendar_events = (await db.execute(select(func.count(CalendarEvent.id)).where(CalendarEvent.owner_user_id == user_id))).scalar_one() or 0
    conversations = (await db.execute(select(func.count(Conversation.id)).where(Conversation.owner_user_id == user_id))).scalar_one() or 0
    return {
        "projects": projects,
        "customers": customers,
        "calendar_events": calendar_events,
        "conversations": conversations,
    }


async def delete_user(
    db: AsyncSession,
    user_id: int,
    *,
    actor_user_id: int,
    actor_username: str,
    unbind_feishu_fn: Any,
) -> dict[str, Any]:
    """
    删除用户（硬删除）。仅当无 owned 资源时允许。
    校验：不能删自己、不能删唯一管理员、不能删仍有归属资源的用户。
    删除前自动解绑该用户的所有飞书身份。
    unbind_feishu_fn(db, user_id) 返回解绑数量。
    返回 {"username": str, "feishu_unbound_count": int} 供审计使用。
    """
    user = await get_user_by_id(db, user_id)
    if not user:
        raise LookupError("用户不存在")
    if user_id == actor_user_id:
        logger.warning("admin.user: blocked delete self user_id=%s", user_id)
        raise ValueError("不能删除当前登录账号")
    admin_count = await count_admin_users(db, active_only=True)
    if user.role == "admin" and admin_count <= 1:
        logger.warning("admin.user: blocked delete only admin user_id=%s", user_id)
        raise ValueError("不能删除系统唯一管理员")
    counts = await count_owned_resources_for_user(db, user_id)
    if any(v > 0 for v in counts.values()):
        parts = []
        if counts["projects"] > 0:
            parts.append(f"{counts['projects']} 个项目")
        if counts["customers"] > 0:
            parts.append(f"{counts['customers']} 个客户")
        if counts["calendar_events"] > 0:
            parts.append(f"{counts['calendar_events']} 个日程")
        if counts["conversations"] > 0:
            parts.append(f"{counts['conversations']} 个会话")
        msg = "该用户仍拥有 " + "、".join(parts) + "，请先转移或清理后再删除"
        logger.warning("admin.user: blocked delete user with owned resources user_id=%s counts=%s", user_id, counts)
        raise ValueError(msg)
    feishu_unbound_count = await unbind_feishu_fn(db, user_id)
    await db.delete(user)
    await db.flush()
    logger.info(
        "admin.user: deleted user_id=%s username=%s feishu_unbound=%s",
        user_id,
        user.username,
        feishu_unbound_count,
    )
    return {"username": user.username, "feishu_unbound_count": feishu_unbound_count}


async def create_initial_admin(
    db: AsyncSession,
    *,
    username: str,
    password: str,
) -> User:
    """Create the first administrator only when explicit credentials are supplied."""
    if await count_admin_users(db, active_only=False) > 0:
        raise ValueError("管理员账号已存在；请使用现有管理员账户登录。")
    if len(password or "") < 12:
        raise ValueError("初始管理员密码至少需要 12 个字符。")
    return await create_user(
        db,
        username=username,
        password=password,
        display_name="系统管理员",
        role="admin",
        is_active=True,
        must_change_password=False,
    )
