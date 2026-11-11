"""
认证 API：登录、当前用户、鉴权依赖。
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.desktop_mode import is_desktop_sqlite_backend
from app.models.user import User
from app.schemas.auth import LoginRequest, LoginResponse, UserInfo, ProfileUpdateRequest, ChangePasswordRequest
from app.services.audit_log_service import write_audit_log
from app.services.auth_service import (
    get_user_by_username,
    verify_password,
    update_self_profile,
    change_self_password,
)
from app.services.feishu_identity_service import count_bound_identities_for_user
from app.core.security import create_access_token, decode_access_token

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)


async def get_current_user_optional(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User | None:
    """解析 JWT 得到当前用户；未携带或无效时返回 None（不抛错）。"""
    if not credentials or credentials.credentials is None:
        return None
    token = credentials.credentials
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        return None
    try:
        user_id = int(payload["sub"])
    except (ValueError, TypeError):
        return None
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        return None
    return user


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """要求已登录，否则 401。"""
    user = await get_current_user_optional(request, credentials, db)
    if user is None:
        await write_audit_log(
            db,
            action="login_failed",
            detail="missing or invalid token",
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录或登录已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def require_admin(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """要求当前用户为 admin，否则 403 并写审计日志。"""
    if current_user.role != "admin":
        logger.warning(
            "auth: admin access denied user_id=%s username=%s path=%s",
            current_user.id,
            current_user.username,
            request.url.path,
        )
        await write_audit_log(
            db,
            action="admin_access_denied",
            actor_user_id=current_user.id,
            actor_username=current_user.username,
            target_type="system",
            detail=f"path={request.url.path}",
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            metadata_json={"path": str(request.url.path)},
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return current_user


def _user_to_info(user: User, bound_feishu_count: int = 0) -> UserInfo:
    return UserInfo(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        last_login_at=user.last_login_at,
        created_at=getattr(user, "created_at", None),
        bound_feishu_identities_count=bound_feishu_count,
    )


from fastapi import APIRouter

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LoginResponse:
    """登录：校验用户名密码，返回 access_token 与用户信息。"""
    user = await get_user_by_username(db, body.username)
    if user is None:
        logger.warning("auth: login failed username=%s reason=user_not_found", body.username)
        await write_audit_log(
            db,
            action="login_failed",
            actor_username=body.username,
            detail="user not found",
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

    if not user.is_active:
        logger.warning("auth: login failed username=%s reason=user_disabled", body.username)
        await write_audit_log(
            db,
            action="login_failed",
            actor_user_id=user.id,
            actor_username=user.username,
            detail="user disabled",
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号已禁用")

    if not verify_password(body.password, user.password_hash):
        logger.warning("auth: login failed username=%s reason=invalid_password", body.username)
        await write_audit_log(
            db,
            action="login_failed",
            actor_username=body.username,
            detail="invalid password",
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

    from datetime import datetime, timezone
    user.last_login_at = datetime.now(timezone.utc)
    await db.flush()

    logger.info(
        "auth: login success username=%s user_id=%s role=%s",
        user.username,
        user.id,
        user.role,
    )
    await write_audit_log(
        db,
        action="login_success",
        actor_user_id=user.id,
        actor_username=user.username,
        target_type="user",
        target_id=str(user.id),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    access_token = create_access_token(str(user.id), extra_claims={"username": user.username, "role": user.role})
    bound_count = 0 if is_desktop_sqlite_backend() else await count_bound_identities_for_user(db, user.id)
    return LoginResponse(access_token=access_token, user=_user_to_info(user, bound_count))


@router.get("/me", response_model=UserInfo)
async def me(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserInfo:
    """获取当前登录用户信息（含飞书绑定数；桌面单机固定为 0）。"""
    bound_count = 0 if is_desktop_sqlite_backend() else await count_bound_identities_for_user(db, current_user.id)
    return _user_to_info(current_user, bound_count)


@router.patch("/me", response_model=UserInfo)
async def update_me(
    body: ProfileUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request = None,
) -> UserInfo:
    """用户修改自己的基础资料（仅 display_name）。"""
    user = await update_self_profile(db, current_user.id, display_name=body.display_name)
    await write_audit_log(
        db,
        action="user_update_profile",
        actor_user_id=current_user.id,
        actor_username=current_user.username,
        target_type="user",
        target_id=str(current_user.id),
        detail="display_name updated",
        ip_address=request.client.host if request and request.client else None,
        user_agent=request.headers.get("user-agent") if request else None,
        metadata_json={"field": "display_name"},
    )
    logger.info("user.profile: profile updated user_id=%s", current_user.id)
    bound_count = 0 if is_desktop_sqlite_backend() else await count_bound_identities_for_user(db, user.id)
    return _user_to_info(user, bound_count)


@router.post("/change-password", response_model=UserInfo)
async def change_password(
    body: ChangePasswordRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request = None,
) -> UserInfo:
    """用户修改自己的密码。"""
    try:
        user = await change_self_password(
            db,
            current_user.id,
            old_password=body.old_password,
            new_password=body.new_password,
            clear_must_change=True,
        )
    except ValueError as e:
        await write_audit_log(
            db,
            action="user_change_password",
            actor_user_id=current_user.id,
            actor_username=current_user.username,
            target_type="user",
            target_id=str(current_user.id),
            detail="change password failed: " + str(e),
            ip_address=request.client.host if request and request.client else None,
            user_agent=request.headers.get("user-agent") if request else None,
        )
        raise HTTPException(status_code=400, detail=str(e))
    await write_audit_log(
        db,
        action="user_change_password",
        actor_user_id=current_user.id,
        actor_username=current_user.username,
        target_type="user",
        target_id=str(current_user.id),
        detail="password changed successfully",
        ip_address=request.client.host if request and request.client else None,
        user_agent=request.headers.get("user-agent") if request else None,
    )
    bound_count = 0 if is_desktop_sqlite_backend() else await count_bound_identities_for_user(db, user.id)
    return _user_to_info(user, bound_count)
