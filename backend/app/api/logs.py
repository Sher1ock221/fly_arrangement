"""
日志与对话记录 API：
- GET /logs/system：系统日志查询（按 level 筛选 + 分页）
- GET /logs/chat：对话记录查询（关键词搜索 + 分页）
- DELETE /logs：清空日志
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.log import ChatRecord, SystemLog
from app.models.chat import Conversation
from app.schemas.log import ChatRecordInDB, PaginatedResponse, SystemLogInDB

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("/system", response_model=PaginatedResponse)
async def list_system_logs(
    level: str | None = Query(None, description="可选：INFO/ERROR"),
    module: str | None = Query(None, description="可选：按模块前缀筛选，如 feishu."),
    user_id: int | None = Query(None, description="可选：按用户 ID 过滤（暂按 request_id 与审计日志 actor_user_id 关联，若已集成）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(SystemLog)
    count_stmt = select(func.count(SystemLog.id))
    if level:
        stmt = stmt.where(SystemLog.level == level)
        count_stmt = count_stmt.where(SystemLog.level == level)
    if module and module.strip():
        stmt = stmt.where(SystemLog.module.ilike(f"{module.strip()}%"))
        count_stmt = count_stmt.where(SystemLog.module.ilike(f"{module.strip()}%"))

    total = int((await db.execute(count_stmt)).scalar_one())
    result = await db.execute(
        stmt.order_by(desc(SystemLog.timestamp), desc(SystemLog.id))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = list(result.scalars().all())
    items = [SystemLogInDB.model_validate(r) for r in rows]
    return {"page": page, "page_size": page_size, "total": total, "items": items}


@router.get("/chat", response_model=PaginatedResponse)
async def list_chat_records(
    q: str | None = Query(None, description="关键词：匹配 user_message 或 ai_response"),
    channel: str | None = Query(None, description="来源渠道：web / feishu"),
    user_id: int | None = Query(
        None,
        description="可选：按系统用户 ID 过滤（当前通过 external_user_id / 绑定映射，若已集成）",
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(ChatRecord)
    count_stmt = select(func.count(ChatRecord.id))
    if q and q.strip():
        kw = f"%{q.strip()}%"
        cond = or_(ChatRecord.user_message.ilike(kw), ChatRecord.ai_response.ilike(kw))
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    if channel and channel.strip():
        stmt = stmt.where(ChatRecord.channel == channel.strip())
        count_stmt = count_stmt.where(ChatRecord.channel == channel.strip())
    if user_id is not None:
        # 目前仅按会话 owner_user_id 过滤：即该用户在 Web 端发起的对话；
        # 飞书通道暂不做用户映射。
        stmt = stmt.join(Conversation, ChatRecord.source_conversation_id == Conversation.id).where(
            Conversation.owner_user_id == user_id
        )
        count_stmt = count_stmt.join(
            Conversation, ChatRecord.source_conversation_id == Conversation.id
        ).where(Conversation.owner_user_id == user_id)

    total = int((await db.execute(count_stmt)).scalar_one())
    result = await db.execute(
        stmt.order_by(desc(ChatRecord.timestamp), desc(ChatRecord.id))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = list(result.scalars().all())
    # 飞书同一条用户消息可能历史存在多条 ChatRecord，按 incoming_message_id 去重展示（保留一条）
    seen_incoming: set[str] = set()
    deduped: list[ChatRecord] = []
    for r in rows:
        if r.channel == "feishu" and r.incoming_message_id:
            if r.incoming_message_id in seen_incoming:
                continue
            seen_incoming.add(r.incoming_message_id)
        deduped.append(r)
    items = [ChatRecordInDB.model_validate(r) for r in deduped]
    return {"page": page, "page_size": page_size, "total": total, "items": items}


@router.delete("", summary="清空日志")
async def clear_logs(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    r1 = await db.execute(delete(SystemLog))
    r2 = await db.execute(delete(ChatRecord))
    await db.flush()
    return {
        "ok": True,
        "deleted_system": int(getattr(r1, "rowcount", 0) or 0),
        "deleted_chat": int(getattr(r2, "rowcount", 0) or 0),
    }

