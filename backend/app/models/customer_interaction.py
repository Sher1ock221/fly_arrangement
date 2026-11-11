"""
客户跟进记录表：客户沟通/见面/合作记录。
支持 manual / ai / feishu / web 等来源，便于后续 AI 归档。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CustomerInteraction(Base):
    """客户跟进记录表。"""

    __tablename__ = "customer_interactions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    meeting_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    talk_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    cooperation_direction: Mapped[str | None] = mapped_column(String(512), nullable=True)

    cooperation_intent: Mapped[str | None] = mapped_column(String(512), nullable=True)

    next_cooperation_plan: Mapped[str | None] = mapped_column(String(512), nullable=True)

    specific_needs: Mapped[str | None] = mapped_column(Text, nullable=True)

    importance: Mapped[int | None] = mapped_column(Integer, nullable=True)

    source: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    raw_input: Mapped[str | None] = mapped_column(Text, nullable=True)

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

    customer: Mapped["Customer"] = relationship(
        "Customer",
        back_populates="interactions",
    )

    def __repr__(self) -> str:
        return f"<CustomerInteraction id={self.id} customer_id={self.customer_id}>"
