"""
飞书身份待绑定池：采集用户与机器人对话时的 open_id/union_id 等，本阶段仅采集与查询。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FeishuIdentityPool(Base):
    __tablename__ = "feishu_identity_pool"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    open_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    union_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    feishu_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    chat_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sender_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    raw_payload: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    bind_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'unbound'"), index=True
    )
    bound_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        Index("ix_feishu_identity_pool_tenant_open", "tenant_key", "open_id", unique=False),
    )
