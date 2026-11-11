"""
AI 配置表：动态配置 Ollama 等模型的连接信息，替代环境变量。
升级后支持 temperature 与 created_at。
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AIConfig(Base):
    """AI 配置表，仅保留一条 is_active=True 的记录作为当前生效配置。"""

    __tablename__ = "ai_configs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.2)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    def __repr__(self) -> str:
        return f"<AIConfig id={self.id} model={self.model_name!r} active={self.is_active}>"
