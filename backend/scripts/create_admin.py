"""Create the first administrator interactively; no default credentials are used."""
from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interactively create the first Fly Arrangement administrator."
    )
    parser.add_argument("--username", help="Administrator username; prompted when omitted.")
    parser.add_argument(
        "--database-url",
        help="Optional database URL override, useful for a packaged desktop installation.",
    )
    return parser.parse_args()


async def _create_admin(username: str, password: str) -> None:
    from app.db.session import AsyncSessionLocal
    from app.services.auth_service import create_initial_admin

    async with AsyncSessionLocal() as db:
        try:
            user = await create_initial_admin(db, username=username, password=password)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    print(f"已创建管理员账号：{user.username}")


def main() -> int:
    args = _parse_args()
    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url

    username = (args.username or input("管理员用户名: ")).strip()
    if not username:
        print("用户名不能为空。", file=sys.stderr)
        return 2

    password = getpass.getpass("管理员密码（至少 12 个字符）: ")
    confirmation = getpass.getpass("再次输入管理员密码: ")
    if password != confirmation:
        print("两次输入的密码不一致。", file=sys.stderr)
        return 2
    if len(password) < 12:
        print("管理员密码至少需要 12 个字符。", file=sys.stderr)
        return 2

    try:
        asyncio.run(_create_admin(username, password))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
