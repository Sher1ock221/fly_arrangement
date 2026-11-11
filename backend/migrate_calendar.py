"""
数据库迁移脚本：创建 calendar_events 表，为 projects 表新增 start_date 列。
执行：在 backend 目录下运行 python migrate_calendar.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.models.base import Base
from app.models import project, calendar_event  # noqa: F401  # 注册表


async def migrate():
    try:
        import asyncpg
    except ImportError:
        print("请先安装 asyncpg: pip install asyncpg")
        sys.exit(1)

    url = os.getenv("DATABASE_URL") or ""
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)

    conn = await asyncpg.connect(url)
    try:
        # 创建 calendar_events 表
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS calendar_events (
                id SERIAL PRIMARY KEY,
                title VARCHAR(256) NOT NULL,
                description TEXT,
                start_time TIMESTAMP WITH TIME ZONE NOT NULL,
                end_time TIMESTAMP WITH TIME ZONE NOT NULL,
                type VARCHAR(32) NOT NULL DEFAULT 'event',
                project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
            );
        """)
        print("calendar_events 表已存在或已创建。")

        # projects 表新增 start_date（若不存在）
        await conn.execute("""
            ALTER TABLE projects ADD COLUMN IF NOT EXISTS start_date DATE;
        """)
        print("projects.start_date 列已存在或已添加。")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(migrate())
