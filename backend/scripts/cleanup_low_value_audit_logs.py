"""
一次性脚本：删除已写入的“低价值”审计日志（仅查看/刷新类 action）。
不删除有副作用、可追责的审计记录。

可删除的 action 包括：
- admin_view_data_maintenance_summary
- admin_view_dashboard_summary
- admin_view_system_status
- admin_view_system_info
- admin_view_users
- admin_view_feishu_identities
- admin_view_user_detail
- admin_view_user_feishu_bindings
- admin_view_audit_log_detail
- user_view_help_center
- admin_view_help_center

执行方式（在项目根目录）：
  python backend/scripts/cleanup_low_value_audit_logs.py
或：
  cd backend && python scripts/cleanup_low_value_audit_logs.py
"""
from __future__ import annotations

import asyncio
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.abspath(os.path.join(_SCRIPT_DIR, ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from sqlalchemy import delete, func, select

from app.db.session import AsyncSessionLocal
from app.models.system_audit_log import SystemAuditLog


LOW_VALUE_ACTIONS = frozenset({
    "admin_view_data_maintenance_summary",
    "admin_view_dashboard_summary",
    "admin_view_system_status",
    "admin_view_system_info",
    "admin_view_users",
    "admin_view_feishu_identities",
    "admin_view_user_detail",
    "admin_view_user_feishu_bindings",
    "admin_view_audit_log_detail",
    "user_view_help_center",
    "admin_view_help_center",
})


async def main() -> None:
    async with AsyncSessionLocal() as db:
        count_stmt = select(func.count(SystemAuditLog.id)).where(
            SystemAuditLog.action.in_(LOW_VALUE_ACTIONS)
        )
        total = (await db.execute(count_stmt)).scalar_one() or 0
        print(f"将删除 action 属于上述集合的审计日志，共 {total} 条。")
        if total == 0:
            print("无需删除，退出。")
            return

        result = await db.execute(
            delete(SystemAuditLog).where(SystemAuditLog.action.in_(LOW_VALUE_ACTIONS))
        )
        await db.commit()
        deleted = int(getattr(result, "rowcount", 0) or 0)
        print(f"实际删除 {deleted} 条。")


if __name__ == "__main__":
    asyncio.run(main())
