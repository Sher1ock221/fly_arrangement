"""
对话历史 API：会话列表、创建、更新标题、AI 生成标题。
按 effective_user_id 隔离：列表/创建/更新/删除/生成标题均按归属用户。
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Body, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.chat import Conversation
from app.models.log import ChatRecord
from app.schemas.chat import (
    ConversationCreate,
    ConversationResponse,
    ConversationUpdate,
    ConversationMessageResponse,
    SummarizeTitleRequest,
)
from app.services.ai_engine import generate_conversation_title
from app.services.effective_user import (
    EffectiveUserContext,
    get_effective_user_context,
    require_effective_owner,
    write_data_access_denied_and_raise,
)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> list[ConversationResponse]:
    """获取当前有效用户的所有会话（含 Web 与飞书私聊同步），按 updated_at 倒序。不包含飞书群聊。"""
    result = await db.execute(
        select(Conversation)
        .where(Conversation.owner_user_id == ctx.effective_user_id)
        .where(Conversation.source.in_(["web", "feishu_private"]))
        .order_by(Conversation.updated_at.desc())
    )
    rows = result.scalars().all()
    return [ConversationResponse.model_validate(r) for r in rows]


@router.post("/conversations", response_model=ConversationResponse)
async def create_conversation(
    body: ConversationCreate | None = Body(None),
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    """新建会话，可选标题，默认「新对话」。归属当前有效用户。"""
    title = (body.title if body else None) or "新对话"
    conv = Conversation(title=title[:256], owner_user_id=ctx.effective_user_id)
    db.add(conv)
    await db.flush()
    await db.refresh(conv)
    return ConversationResponse.model_validate(conv)


@router.patch("/conversations/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(
    conversation_id: int,
    body: ConversationUpdate,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> ConversationResponse:
    """更新会话标题（含手动修改）。校验归属。"""
    conv = await db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    try:
        await require_effective_owner(ctx, conv.owner_user_id, "conversation", str(conversation_id))
    except HTTPException as e:
        if e.status_code == 403:
            await write_data_access_denied_and_raise(
                ctx, conv.owner_user_id or 0, "conversation", str(conversation_id), request, db
            )
        raise
    await db.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(title=body.title[:256], updated_at=datetime.now(timezone.utc))
    )
    await db.flush()
    result = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    conv = result.scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return ConversationResponse.model_validate(conv)


@router.get("/conversations/{conversation_id}/messages", response_model=list[ConversationMessageResponse])
async def list_conversation_messages(
    conversation_id: int,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
) -> list[ConversationMessageResponse]:
    """获取指定会话的消息列表（含 Web 与飞书私聊同步的消息）。校验归属。"""
    conv = await db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    try:
        await require_effective_owner(ctx, conv.owner_user_id, "conversation", str(conversation_id))
    except HTTPException as e:
        if e.status_code == 403:
            await write_data_access_denied_and_raise(
                ctx, conv.owner_user_id or 0, "conversation", str(conversation_id), None, db
            )
        raise
    result = await db.execute(
        select(ChatRecord)
        .where(ChatRecord.source_conversation_id == conversation_id)
        .order_by(ChatRecord.timestamp.asc(), ChatRecord.id.asc())
    )
    rows = result.scalars().all()
    out: list[ConversationMessageResponse] = []
    for r in rows:
        if r.user_message:
            out.append(
                ConversationMessageResponse(
                    role="user",
                    content=r.user_message,
                    created_at=r.timestamp,
                )
            )
        if r.ai_response:
            out.append(
                ConversationMessageResponse(
                    role="assistant",
                    content=r.ai_response,
                    created_at=r.timestamp,
                )
            )
    return out


@router.post("/conversations/{conversation_id}/summarize-title")
async def summarize_conversation_title(
    conversation_id: int,
    body: SummarizeTitleRequest,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> dict[str, str]:
    """根据前几条消息调用 AI 生成 5-10 字标题并更新会话。校验归属。"""
    conv = await db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    try:
        await require_effective_owner(ctx, conv.owner_user_id, "conversation", str(conversation_id))
    except HTTPException as e:
        if e.status_code == 403:
            await write_data_access_denied_and_raise(
                ctx, conv.owner_user_id or 0, "conversation", str(conversation_id), request, db
            )
        raise
    if not body.messages:
        raise HTTPException(status_code=400, detail="messages 不能为空")
    title = await generate_conversation_title(db, body.messages)
    await db.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(title=title[:256], updated_at=datetime.now(timezone.utc))
    )
    await db.flush()
    return {"title": title}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    ctx: EffectiveUserContext = Depends(get_effective_user_context),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> None:
    """删除会话。校验归属。"""
    conv = await db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    try:
        await require_effective_owner(ctx, conv.owner_user_id, "conversation", str(conversation_id))
    except HTTPException as e:
        if e.status_code == 403:
            await write_data_access_denied_and_raise(
                ctx, conv.owner_user_id or 0, "conversation", str(conversation_id), request, db
            )
        raise
    await db.delete(conv)
    await db.flush()
