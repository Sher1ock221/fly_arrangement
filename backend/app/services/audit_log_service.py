"""
系统审计日志服务：写入 system_audit_logs，不替代现有 SystemLog / AuditLog。
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_audit_log import SystemAuditLog

logger = logging.getLogger(__name__)


async def write_audit_log(
    db: AsyncSession,
    *,
    action: str,
    actor_user_id: int | None = None,
    actor_username: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata_json: dict | list | None = None,
) -> None:
    """写入一条审计日志。"""
    log_entry = SystemAuditLog(
        actor_user_id=actor_user_id,
        actor_username=actor_username,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata_json=metadata_json,
    )
    db.add(log_entry)
    await db.flush()
