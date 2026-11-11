"""Repair queue SLA：运行中超时判断（与列表、summary 统计口径一致）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.constants.project_governance import (
    PROJECT_REPAIR_QUEUE_DEFAULT_SLA_HOURS,
    REPAIR_STATUS_RUNNING,
)


def sla_overdue_cutoff(now: datetime | None = None) -> datetime:
    """与 summary / 列表 overdue 筛选一致：started_at < 本值 则视为已超时。"""
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now - timedelta(hours=float(PROJECT_REPAIR_QUEUE_DEFAULT_SLA_HOURS))


def compute_repair_queue_sla_fields(
    *,
    status: str,
    started_at: datetime | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """返回 is_overdue、running_duration_hours、overdue_hours（非 running 均为 false / null）。"""
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    if status != REPAIR_STATUS_RUNNING or started_at is None:
        return {
            "is_overdue": False,
            "running_duration_hours": None,
            "overdue_hours": None,
        }

    sa = started_at if started_at.tzinfo else started_at.replace(tzinfo=timezone.utc)
    duration_h = (now - sa).total_seconds() / 3600.0
    sla_h = float(PROJECT_REPAIR_QUEUE_DEFAULT_SLA_HOURS)
    is_overdue = duration_h > sla_h
    overdue_h = max(duration_h - sla_h, 0.0)
    return {
        "is_overdue": is_overdue,
        "running_duration_hours": round(duration_h, 2),
        "overdue_hours": round(overdue_h, 2),
    }
