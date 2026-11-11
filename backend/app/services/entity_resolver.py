"""
实体解析：根据用户自然语言查询解析出 project_id / customer_id。
供 AI 先 resolve 再 update，避免猜测 id。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Customer, Project
from app.models.collaboration import (
    CustomerCollaborator,
    ProjectCollaborator,
)

# 中文数字 -> 阿拉伯数字
_CN_NUM = {
    "零": "0", "一": "1", "二": "2", "三": "3", "四": "4",
    "五": "5", "六": "6", "七": "7", "八": "8", "九": "9",
    "十": "10", "十一": "11", "十二": "12",
}


def _chinese_number_to_digit(s: str) -> str:
    if not s or not isinstance(s, str):
        return s
    t = s.strip()
    for cn, digit in sorted(_CN_NUM.items(), key=lambda x: -len(x[0])):
        t = t.replace(cn, digit)
    return t.strip()


async def resolve_project(db: AsyncSession, query: str, *, owner_user_id: int | None = None) -> dict[str, Any]:
    """
    根据项目名称/编号解析出唯一项目。
    匹配顺序：project_no 精确 -> name 精确 -> project_no 模糊 -> name 模糊 -> 中文数字转数字后再试。
    若提供 owner_user_id，匹配该用户 own 或 collaborate 的项目。
    返回 {"success": True, "project_id", "project_no", "name"} 或 {"success": False, "message": "..."}。
    """
    if not query or not str(query).strip():
        return {"success": False, "message": "未找到项目"}

    raw = str(query).strip()

    def _owner_filter(stmt):
        if owner_user_id is not None:
            collab_exists = exists().where(
                ProjectCollaborator.project_id == Project.id,
                ProjectCollaborator.user_id == owner_user_id,
            )
            return stmt.where(or_(Project.owner_user_id == owner_user_id, collab_exists))
        return stmt

    async def _exact_no(val: str):
        stmt = select(Project).where(Project.project_no == val).limit(1)
        r = await db.execute(_owner_filter(stmt))
        return r.scalar_one_or_none()

    async def _exact_name(val: str):
        stmt = select(Project).where(Project.name == val).limit(1)
        r = await db.execute(_owner_filter(stmt))
        return r.scalar_one_or_none()

    async def _ilike_no(val: str):
        if not val:
            return None
        stmt = select(Project).where(Project.project_no.ilike(f"%{val}%")).limit(2)
        r = await db.execute(_owner_filter(stmt))
        rows = list(r.scalars().all())
        if len(rows) == 0:
            return None
        if len(rows) > 1:
            return None
        return rows[0]

    async def _ilike_name(val: str):
        stmt = select(Project).where(Project.name.ilike(f"%{val}%")).limit(2)
        r = await db.execute(_owner_filter(stmt))
        rows = list(r.scalars().all())
        if len(rows) == 0:
            return None
        if len(rows) > 1:
            return None
        return rows[0]

    async def _try_all(val: str):
        p = await _exact_no(val)
        if p:
            return p
        p = await _exact_name(val)
        if p:
            return p
        p = await _ilike_no(val)
        if p:
            return p
        p = await _ilike_name(val)
        return p

    p = await _try_all(raw)
    if p:
        return {
            "success": True,
            "project_id": p.id,
            "project_no": (p.project_no or "").strip(),
            "name": (p.name or "").strip(),
        }

    converted = _chinese_number_to_digit(raw)
    if converted != raw:
        p = await _try_all(converted)
        if p:
            return {
                "success": True,
                "project_id": p.id,
                "project_no": (p.project_no or "").strip(),
                "name": (p.name or "").strip(),
            }
        if converted.isdigit():
            p = await _exact_no(f"P{converted.zfill(3)}")  # _exact_no 内部已应用 _owner_filter
            if p:
                return {
                    "success": True,
                    "project_id": p.id,
                    "project_no": (p.project_no or "").strip(),
                    "name": (p.name or "").strip(),
                }

    return {"success": False, "message": "未找到项目"}


async def resolve_customer(db: AsyncSession, query: str, *, owner_user_id: int | None = None) -> dict[str, Any]:
    """
    根据客户名称或公司名解析出唯一客户。
    匹配：name 精确 -> company 精确 -> name ILIKE -> company ILIKE。
    若提供 owner_user_id，匹配该用户 own 或 collaborate 的客户。
    返回 {"success": True, "customer_id", "name"} 或 {"success": False, "message": "..."}。
    """
    if not query or not str(query).strip():
        return {"success": False, "message": "未找到客户"}

    raw = str(query).strip()

    def _base(stmt):
        if owner_user_id is not None:
            collab_exists = exists().where(
                CustomerCollaborator.customer_id == Customer.id,
                CustomerCollaborator.user_id == owner_user_id,
            )
            return stmt.where(or_(Customer.owner_user_id == owner_user_id, collab_exists))
        return stmt

    r = await db.execute(_base(select(Customer).where(Customer.name == raw).limit(1)))
    row = r.scalar_one_or_none()
    if row:
        return {"success": True, "customer_id": row.id, "name": (row.name or "").strip()}

    r = await db.execute(_base(select(Customer).where(Customer.company == raw).limit(1)))
    row = r.scalar_one_or_none()
    if row:
        return {"success": True, "customer_id": row.id, "name": (row.name or "").strip()}

    r = await db.execute(_base(select(Customer).where(Customer.name.ilike(f"%{raw}%")).limit(10)))
    rows = list(r.scalars().all())
    if len(rows) == 1:
        return {"success": True, "customer_id": rows[0].id, "name": (rows[0].name or "").strip()}
    if len(rows) > 1:
        candidates = [
            {"name": (r.name or "").strip(), "company": (r.company or "").strip() or None, "position": (r.position or "").strip() or None}
            for r in rows
        ]
        return {"success": False, "message": "存在多个匹配客户，请指定更具体的客户名称", "candidates": candidates}

    r = await db.execute(_base(select(Customer).where(Customer.company.ilike(f"%{raw}%")).limit(10)))
    rows = list(r.scalars().all())
    if len(rows) == 1:
        return {"success": True, "customer_id": rows[0].id, "name": (rows[0].name or "").strip()}
    if len(rows) > 1:
        candidates = [
            {"name": (r.name or "").strip(), "company": (r.company or "").strip() or None, "position": (r.position or "").strip() or None}
            for r in rows
        ]
        return {"success": False, "message": "存在多个匹配客户，请指定更具体的客户名称", "candidates": candidates}

    return {"success": False, "message": "未找到客户"}
