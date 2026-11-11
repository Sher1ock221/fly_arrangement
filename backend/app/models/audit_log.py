"""
审计日志表：记录项目/客户的 update、delete、create 操作，用于撤销功能。
old_value / new_value 为 JSONB，便于按字段恢复。升级后增加 operator 与 timestamp 默认值。
"""
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# 目标类型与操作类型常量，便于 API 与业务使用
TARGET_TYPE_PROJECT = "project"
TARGET_TYPE_CUSTOMER = "customer"
ACTION_UPDATE = "update"
ACTION_DELETE = "delete"
ACTION_CREATE = "create"


class AuditLog(Base):
    """审计日志表。"""

    __tablename__ = "audit_logs"

    # 主键
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # 目标类型：project / customer
    target_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    # 目标记录主键 id
    target_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # 操作类型：update / delete / create
    action: Mapped[str] = mapped_column(String(32), nullable=False)

    # 变更前的完整快照（JSON），用于撤销时恢复
    old_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # 变更后的完整快照（JSON），update 时写入
    new_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # 记录时间，默认当前时间
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    # 操作者：AI / system / admin 等
    operator: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 触发来源：web / ai / feishu / system
    operator_source: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'system'")
    )
    # 外部操作人标识（如飞书 open_id）
    operator_external_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} {self.target_type}:{self.target_id} {self.action}>"
