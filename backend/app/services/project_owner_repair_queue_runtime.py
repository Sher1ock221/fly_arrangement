"""
project_owner_repair_queue 在 SQLite 下的幂等补建与查询封装。

该表由 Alembic 023 在 PostgreSQL 上创建，桌面 SQLite baseline 不包含对应 ORM，
因此通过 DDL + 本模块统一访问，避免多处裸 SQL 与缺表 500。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.sqlite_auxiliary import PROJECT_OWNER_REPAIR_QUEUE_DDL

logger = logging.getLogger(__name__)


def _is_missing_owner_repair_queue_table(exc: BaseException) -> bool:
    orig = getattr(exc, "orig", exc)
    msg = str(orig)
    return "no such table: project_owner_repair_queue" in msg


async def ensure_project_owner_repair_queue_table(db: AsyncSession) -> None:
    if db.bind is None or db.bind.dialect.name != "sqlite":
        return
    for stmt in PROJECT_OWNER_REPAIR_QUEUE_DDL:
        await db.execute(text(stmt))


async def count_project_owner_repair_queue(db: AsyncSession) -> int:
    await ensure_project_owner_repair_queue_table(db)
    try:
        row = await db.execute(text("SELECT COUNT(*) FROM project_owner_repair_queue"))
        return int(row.scalar_one() or 0)
    except OperationalError as exc:
        if _is_missing_owner_repair_queue_table(exc):
            logger.warning(
                "project_owner_repair_queue_missing_count_zero: %s",
                exc,
            )
            return 0
        raise


async def list_project_owner_repair_queue_all(db: AsyncSession) -> list[dict[str, Any]]:
    await ensure_project_owner_repair_queue_table(db)
    try:
        result = await db.execute(
            text(
                """
                SELECT project_id, owner_text, reason, created_at
                FROM project_owner_repair_queue
                ORDER BY created_at DESC
                """
            )
        )
        return [dict(r) for r in result.mappings().all()]
    except OperationalError as exc:
        if _is_missing_owner_repair_queue_table(exc):
            logger.warning("project_owner_repair_queue_missing_return_empty: %s", exc)
            return []
        raise


async def fetch_project_owner_repair_queue_for_project(
    db: AsyncSession, project_id: int
) -> dict[str, Any] | None:
    await ensure_project_owner_repair_queue_table(db)
    try:
        row = (
            await db.execute(
                text(
                    """
                    SELECT project_id, owner_text, reason, created_at
                    FROM project_owner_repair_queue
                    WHERE project_id = :project_id
                    LIMIT 1
                    """
                ),
                {"project_id": project_id},
            )
        ).mappings().first()
        return dict(row) if row is not None else None
    except OperationalError as exc:
        if _is_missing_owner_repair_queue_table(exc):
            logger.warning("project_owner_repair_queue_missing_return_empty: %s", exc)
            return None
        raise


async def list_project_owner_repair_queue_legacy_scan(db: AsyncSession) -> list[dict[str, Any]]:
    """供 project_repair_scanner 使用，仅选取 scanner 所需列。"""
    await ensure_project_owner_repair_queue_table(db)
    try:
        result = await db.execute(
            text("SELECT project_id, owner_text, reason FROM project_owner_repair_queue")
        )
        return [dict(r) for r in result.mappings().all()]
    except OperationalError as exc:
        if _is_missing_owner_repair_queue_table(exc):
            logger.warning("project_owner_repair_queue_missing_return_empty: %s", exc)
            return []
        raise
