"""
项目表：项目管理模块核心实体。
升级后支持 customer_id 关联客户、status、软删除与创建时间，project_no 必填且唯一。
同时支持通过 project_customers 多对多关联多个客户。
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    """项目表。"""

    __tablename__ = "projects"

    # 主键
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # 数据归属：多用户隔离
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    initiator_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # 项目编号（唯一，格式如 P001，必填）
    project_no: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)

    # 项目名称
    name: Mapped[str] = mapped_column(String(256), nullable=False, index=True)

    # 截止日期（旧字段，保留兼容）
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)

    # 开始日期（旧字段，保留兼容）
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # 开始时间（精确到时分）
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 截止时间（精确到时分）
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 项目目标
    goal: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # 负责人
    owner: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # 更新日期（最后修改时间，由应用在每次更新时写入）
    update_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 项目内需（可滚动单行文本，用 Text 支持较长内容）
    requirements: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 项目进展（文本摘要）
    progress_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 客户名称（文本，保留用于历史兼容）
    customer_name: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # 客户主键，正式关联 customers 表
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # 项目状态，便于 AI 筛选与统计
    status: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)

    # 软删除标记
    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False)

    # 创建时间
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=utc_now,
    )

    # 关联客户（可选，保留用于历史兼容）
    customer: Mapped["Customer | None"] = relationship(
        "Customer",
        back_populates="projects",
        foreign_keys=[customer_id],
    )

    # 多对多：项目关联的客户（project_customers 中间表）
    project_customers: Mapped[list["ProjectCustomer"]] = relationship(
        "ProjectCustomer",
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Project id={self.id} project_no={self.project_no!r} name={self.name!r}>"
