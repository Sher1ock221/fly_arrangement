"""
SQLite 辅助表 DDL（未挂到 Base.metadata 的表，见 Alembic 023）。

桌面版 baseline 仅 create_all 已注册模型，因此需显式 CREATE TABLE IF NOT EXISTS。
PostgreSQL 仍由 Alembic 管理，此处不在非 sqlite 方言上执行任何语句。
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection


# 与 alembic/versions/023_project_owner_repair_queue.py 语义对齐：
# project_id 为主键；避免额外 NOT NULL / 外键，降低脏数据导致初始化失败的风险。
_CREATE_PROJECT_OWNER_REPAIR_QUEUE = """
CREATE TABLE IF NOT EXISTS project_owner_repair_queue (
    project_id INTEGER PRIMARY KEY,
    owner_text VARCHAR(128),
    reason TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""

_INDEX_PROJECT_ID = (
    "CREATE INDEX IF NOT EXISTS ix_project_owner_repair_queue_project_id "
    "ON project_owner_repair_queue (project_id)"
)

_INDEX_CREATED_AT = (
    "CREATE INDEX IF NOT EXISTS ix_project_owner_repair_queue_created_at "
    "ON project_owner_repair_queue (created_at)"
)

# 供 AsyncSession 与 sync Connection 共用，避免 DDL 字符串分叉。
PROJECT_OWNER_REPAIR_QUEUE_DDL: tuple[str, ...] = (
    _CREATE_PROJECT_OWNER_REPAIR_QUEUE,
    _INDEX_PROJECT_ID,
    _INDEX_CREATED_AT,
)


def ensure_project_owner_repair_queue_sqlite_connection(connection: Connection) -> None:
    """在同步 Connection 上幂等补建（供 init_sqlite_baseline / run_sync 使用）。"""
    if connection.dialect.name != "sqlite":
        return
    for stmt in PROJECT_OWNER_REPAIR_QUEUE_DDL:
        connection.execute(text(stmt))
