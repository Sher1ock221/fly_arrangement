"""
飞书集成相关数据表：
- FeishuUser：飞书用户身份主表（当前即内部用户主体）
- FeishuConversation：飞书会话到 conversations 的映射
- FeishuMessageEvent：飞书事件幂等、状态流转、重试与审计
- FeishuToken：飞书 access_token 缓存
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.url import get_database_url, is_postgres_url, normalize_database_url
from app.models.base import Base

_IS_POSTGRES = is_postgres_url(normalize_database_url(get_database_url()))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FeishuUser(Base):
    __tablename__ = "feishu_users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    open_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    union_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    tenant_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class FeishuConversation(Base):
    __tablename__ = "feishu_conversations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    feishu_open_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    feishu_chat_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    conversation_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # p2p / group_at
    source_conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    last_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        (
            Index(
                "uq_feishu_conversations_p2p",
                "feishu_open_id",
                "conversation_type",
                unique=True,
                postgresql_where=text("conversation_type = 'p2p'"),
            ),
            Index(
                "uq_feishu_conversations_group_user",
                "feishu_chat_id",
                "feishu_open_id",
                "conversation_type",
                unique=True,
                postgresql_where=text("conversation_type = 'group_at'"),
            ),
        )
        if _IS_POSTGRES
        else ()
    )


class FeishuMessageEvent(Base):
    __tablename__ = "feishu_message_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True, index=True)
    message_id: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True, index=True)
    chat_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    open_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    message_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw_payload: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    process_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'received'"), index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'webhook'"),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class FeishuSyncState(Base):
    """飞书离线补偿同步水位表：按绑定用户+私聊会话记录 last_processed 等，用于历史消息拉取与去重。"""

    __tablename__ = "feishu_sync_state"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    bound_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    identity_pool_id: Mapped[int | None] = mapped_column(
        ForeignKey("feishu_identity_pool.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    tenant_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    open_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    union_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    chat_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    channel_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'feishu_private'"),
        index=True,
    )
    last_synced_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_synced_message_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_processed_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_processed_message_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    __table_args__ = (
        Index("ix_feishu_sync_state_tenant_open", "tenant_key", "open_id"),
        Index("ix_feishu_sync_state_enabled", "is_enabled"),
        Index(
            "uq_feishu_sync_state_chat_channel",
            "chat_id",
            "channel_type",
            unique=True,
        ),
    )


class FeishuToken(Base):
    __tablename__ = "feishu_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    token_type: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    expire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
