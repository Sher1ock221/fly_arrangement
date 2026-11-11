"""
客户表：客户管理模块核心实体。
字段对应 PRD：客户名称、认识方式、单位名称、公司简介、联系方式、未来合作方向。
升级后支持软删除、创建时间及公司索引。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Customer(Base):
    """客户表。"""

    __tablename__ = "customers"

    # 主键
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # 客户名称
    name: Mapped[str] = mapped_column(String(256), nullable=False, index=True)

    # 认识方式
    origin: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # 单位名称
    company: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)

    # 公司简介
    profile: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 联系方式
    contact: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # 未来合作方向
    future_direction: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 担任职位
    position: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # 业务方向
    business_direction: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # 备注
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 如何认识/认识渠道（与 origin 并存，可后续统一）
    acquaintance_source: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # 更新时间
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=utc_now,
        onupdate=utc_now,
    )

    # 软删除标记
    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False)

    # 创建时间
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=utc_now,
    )

    # 数据归属：多用户隔离
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # 关联项目（一对多，通过 projects.customer_id，保留兼容）
    projects: Mapped[list["Project"]] = relationship(
        "Project",
        back_populates="customer",
        foreign_keys="Project.customer_id",
    )

    # 多对多：通过 project_customers 关联的项目
    project_customers: Mapped[list["ProjectCustomer"]] = relationship(
        "ProjectCustomer",
        back_populates="customer",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # 客户跟进记录（一对多）
    interactions: Mapped[list["CustomerInteraction"]] = relationship(
        "CustomerInteraction",
        back_populates="customer",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Customer id={self.id} name={self.name!r}>"
