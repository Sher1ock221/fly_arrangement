"""
日志与对话记录相关 Pydantic 模型。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SystemLogInDB(BaseModel):
    """系统日志数据库返回。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    level: str = Field(..., description="INFO/ERROR")
    module: str
    message: str
    stack_trace: str | None = None
    timestamp: datetime


class ChatRecordInDB(BaseModel):
    """对话记录数据库返回。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_message: str
    ai_response: str
    tool_calls: Any | None = None
    channel: str = "web"
    external_user_id: str | None = None
    external_chat_id: str | None = None
    source_conversation_id: int | None = None
    external_message_id: str | None = None
    incoming_message_id: str | None = None
    timestamp: datetime


class PaginatedResponse(BaseModel):
    """通用分页响应。"""

    page: int
    page_size: int
    total: int
    items: list[Any]

