"""
桌面版 SQLite baseline 初始化脚本。

用途：
- 仅在 DATABASE_URL 指向 SQLite 时执行
- 基于当前 SQLAlchemy 模型执行 Base.metadata.create_all
- 幂等，可重复执行

执行方式（在项目根目录）：
  python backend/scripts/init_sqlite_baseline.py
或（在 backend 目录）：
  python scripts/init_sqlite_baseline.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

# 保证可从项目根或 backend 目录执行
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.abspath(os.path.join(_SCRIPT_DIR, ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.db.session import DATABASE_URL, engine
from app.db.sqlite_auxiliary import ensure_project_owner_repair_queue_sqlite_connection
from app.db.url import ensure_sqlite_parent_dir, is_sqlite_url, normalize_database_url
from app.models.base import Base
import app.models  # noqa: F401  # 确保所有模型注册到 Base.metadata


def _mask_database_url(url: str) -> str:
    """日志展示用：尽量隐藏密码。"""
    if not url:
        return url
    parsed = urlparse(url)
    if parsed.password is None:
        return url
    return url.replace(f":{parsed.password}@", ":***@")


def _sqlite_path_info(url: str) -> tuple[bool, Path | None]:
    """
    返回 (is_memory, db_file_path)：
    - :memory: 返回 (True, None)
    - 文件库返回 (False, Path)
    """
    parsed = urlparse(url)
    db_path = unquote(parsed.path or "")
    normalized = db_path.lstrip("/")
    if normalized == ":memory:":
        return True, None
    if not normalized:
        return False, None
    return False, Path(normalized)


async def main() -> None:
    normalized_url = normalize_database_url(DATABASE_URL)
    is_sqlite = is_sqlite_url(normalized_url)

    db_type = "sqlite" if is_sqlite else "non-sqlite"
    print(f"[baseline] database_type={db_type}")
    print(f"[baseline] database_url={_mask_database_url(normalized_url)}")

    if not is_sqlite:
        print("[baseline] skip: current DATABASE_URL is not SQLite, no action taken.")
        return

    is_memory, db_file = _sqlite_path_info(normalized_url)
    if is_memory:
        print("[baseline] sqlite_mode=:memory: (non-persistent).")
    elif db_file is not None:
        parent = db_file.parent
        existed_before = parent.exists()
        ensure_sqlite_parent_dir(normalized_url)
        parent_exists_after = parent.exists()
        if existed_before:
            print(f"[baseline] sqlite_parent_dir_exists={parent}")
        elif parent_exists_after:
            print(f"[baseline] sqlite_parent_dir_created={parent}")
        else:
            print(f"[baseline] sqlite_parent_dir_status=unknown path={parent}")
    else:
        # 保底日志，不中断 create_all
        ensure_sqlite_parent_dir(normalized_url)
        print("[baseline] sqlite_parent_dir=unable_to_resolve_path, continue.")

    table_count = len(Base.metadata.tables)
    print(f"[baseline] metadata_tables={table_count}")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(ensure_project_owner_repair_queue_sqlite_connection)

    print("[baseline] create_all_completed=true")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

