"""
提醒任务：单次、固定频率、相对日程；支持飞书私聊触达。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ReminderTask(Base):
    __tablename__ = "reminder_tasks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'feishu_private'"), index=True
    )
    feishu_open_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    tenant_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("calendar_events.id", ondelete="SET NULL"), nullable=True, index=True
    )
    related_project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    related_customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reminder_type: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )  # one_time | recurring | relative_to_event
    schedule_rule_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    next_trigger_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_trigger_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'active'"), index=True
    )  # active | paused | completed | cancelled | failed
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    logs: Mapped[list["ReminderLog"]] = relationship(
        "ReminderLog", back_populates="task", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_reminder_tasks_due", "status", "is_enabled", "next_trigger_at"),
    )


class ReminderLog(Base):
    __tablename__ = "reminder_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    reminder_task_id: Mapped[int] = mapped_column(
        ForeignKey("reminder_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # sent | failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    feishu_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    task: Mapped["ReminderTask"] = relationship("ReminderTask", back_populates="logs")
