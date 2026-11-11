"""
数据库 URL 工具：
- 统一读取 DATABASE_URL
- 识别 PostgreSQL / SQLite
- 标准化常见 URL 形式
- 在 SQLite 文件库模式下确保父目录存在
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.core.config import settings

DEFAULT_SQLITE_URL = "sqlite+aiosqlite:///./data/fly_arrangement.db"


def get_database_url() -> str:
    """优先使用环境变量 DATABASE_URL，其次使用 settings，最后回退默认 SQLite。"""
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url

    settings_url = getattr(settings, "DATABASE_URL", None)
    if settings_url:
        return settings_url

    return DEFAULT_SQLITE_URL


def is_sqlite_url(database_url: str) -> bool:
    """判断 URL 是否为 sqlite / sqlite+aiosqlite。"""
    url = (database_url or "").lower()
    return url.startswith("sqlite://") or url.startswith("sqlite+aiosqlite://")


def is_postgres_url(database_url: str) -> bool:
    """判断 URL 是否为 postgresql / postgresql+asyncpg。"""
    url = (database_url or "").lower()
    return url.startswith("postgresql://") or url.startswith("postgresql+asyncpg://")


def normalize_database_url(database_url: str) -> str:
    """
    标准化数据库 URL：
    - sqlite:///  -> sqlite+aiosqlite:///
    - postgresql:// -> postgresql+asyncpg://
    其他情况原样返回。
    """
    if not database_url:
        return database_url

    if database_url.startswith("sqlite+aiosqlite://"):
        return database_url
    if database_url.startswith("sqlite://"):
        return database_url.replace("sqlite://", "sqlite+aiosqlite://", 1)

    if database_url.startswith("postgresql+asyncpg://"):
        return database_url
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    return database_url


def ensure_sqlite_parent_dir(database_url: str) -> None:
    """
    对 SQLite 文件数据库创建父目录。
    - 内存库 sqlite:///:memory: / sqlite+aiosqlite:///:memory: 跳过
    - 仅处理 sqlite URL
    """
    if not is_sqlite_url(database_url):
        return

    parsed = urlparse(database_url)
    db_path = unquote(parsed.path or "")
    if not db_path:
        return

    # sqlite URL 的 path 通常为 "/:memory:" 或 "/C:/..." 或 "/./data/..."
    normalized = db_path.lstrip("/")
    if normalized == ":memory:":
        return

    db_file = Path(normalized)
    db_file.parent.mkdir(parents=True, exist_ok=True)
