"""
系统日志与对话记录表：
- SystemLog：记录运行报错/告警及 request_id 链路追踪
- ChatRecord：记录 AI 对话与触发的工具调用，支持 session_id、intent
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SystemLog(Base):
    """系统运行日志（错误/告警/信息）。"""

    __tablename__ = "system_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # INFO/ERROR
    module: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    stack_trace: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        index=True,
    )
    # 请求链路追踪
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    def __repr__(self) -> str:
        return f"<SystemLog id={self.id} level={self.level} module={self.module!r}>"


class ChatRecord(Base):
    """AI 对话记录。"""

    __tablename__ = "chat_records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_message: Mapped[str] = mapped_column(Text, nullable=False)
    ai_response: Mapped[str] = mapped_column(Text, nullable=False)
    tool_calls: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    channel: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'web'"),
        index=True,
    )
    external_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    external_chat_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    source_conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    external_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    """飞书/外部 回复消息 ID（我方发出的消息）。"""
    incoming_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    """飞书 用户消息 ID（幂等去重用：同一条 incoming 只应有一条 ChatRecord）。"""
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        index=True,
    )
    # 同一轮对话标识
    session_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    # AI 解析的意图，如 update_project_owner / query_project / create_project
    intent: Mapped[str | None] = mapped_column(String(100), nullable=True)

    def __repr__(self) -> str:
        return f"<ChatRecord id={self.id}>"
