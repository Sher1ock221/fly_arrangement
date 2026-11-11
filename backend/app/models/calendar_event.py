"""
日历日程表：支持 event / project / meeting / task 类型，可关联 project_id。
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CalendarEvent(Base):
    """日历日程。"""

    __tablename__ = "calendar_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="event", index=True
    )  # event | project | meeting | task
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=utc_now,
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=utc_now,
        onupdate=utc_now,
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="scheduled", index=True
    )  # scheduled | confirmed | completed | cancelled
    candidate_group_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    candidate_policy: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )  # candidate | mutually_exclusive
    auto_cancel_others_on_complete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    def __repr__(self) -> str:
        return f"<CalendarEvent id={self.id} title={self.title!r} type={self.type}>"
