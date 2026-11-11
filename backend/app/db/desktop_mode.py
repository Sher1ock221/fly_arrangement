"""
桌面单机模式判定：与 SQLite 文件库部署一致，用于关闭飞书路由与后台任务。

说明：不以「是否安装桌面包」为标志，仅以 DATABASE_URL 是否为 SQLite 为准，
与现有 main.py lifespan 行为保持一致。
"""

from __future__ import annotations

from app.db.url import get_database_url, is_sqlite_url, normalize_database_url


def is_desktop_sqlite_backend() -> bool:
    try:
        return is_sqlite_url(normalize_database_url(get_database_url()))
    except Exception:
        return False
