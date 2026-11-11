"""
飞书私聊离线补偿入口：委托给 feishu_history_sync_service 执行，保持向后兼容的别名。
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.feishu_history_sync_service import run_feishu_history_sync_once


async def scan_and_sync_unprocessed_feishu_messages(db: AsyncSession) -> None:
    """
    扫描所有已绑定且带 chat_id 的飞书身份（仅私聊），对每个会话拉取历史消息并补处理。
    委托给 run_feishu_history_sync_once 实现。
    """
    await run_feishu_history_sync_once(db)
