"""
SQLAlchemy 异步引擎与 AsyncSession 配置。
支持根据 DATABASE_URL 自动识别 PostgreSQL / SQLite。
"""
from collections.abc import AsyncGenerator
import logging

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
from app.db.url import (
    ensure_sqlite_parent_dir,
    get_database_url,
    is_postgres_url,
    is_sqlite_url,
    normalize_database_url,
)

# 导入所有模型，使 Base.metadata 包含全部表（供 Alembic 等使用）
from app.models import ai_config, audit_log, calendar_event, chat, customer, feishu, feishu_identity_pool, log, project, system_audit_log, system_config, user  # noqa: F401

logger = logging.getLogger(__name__)
DATABASE_URL = normalize_database_url(get_database_url())

if is_sqlite_url(DATABASE_URL):
    ensure_sqlite_parent_dir(DATABASE_URL)
    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        future=True,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
elif is_postgres_url(DATABASE_URL):
    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        future=True,
        pool_pre_ping=True,
    )
else:
    # 未识别方言时保持通用异步引擎初始化，避免破坏扩展场景。
    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        future=True,
    )

if is_sqlite_url(DATABASE_URL):
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        pragma_sql_list = (
            "PRAGMA busy_timeout=30000",
            "PRAGMA journal_mode=WAL",
            "PRAGMA synchronous=NORMAL",
            "PRAGMA foreign_keys=ON",
        )
        try:
            cursor = dbapi_connection.cursor()
        except Exception as exc:
            logger.warning("sqlite pragma setup skipped: cursor unavailable: %s", exc)
            return
        try:
            for sql in pragma_sql_list:
                try:
                    cursor.execute(sql)
                except Exception as exc:
                    logger.warning("sqlite pragma failed sql=%s err=%s", sql, exc)
        finally:
            try:
                cursor.close()
            except Exception:
                pass

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """依赖注入：为每个请求提供异步会话，请求结束后关闭。"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
