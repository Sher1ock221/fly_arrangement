"""
项目-客户多对多关联表：一个项目可关联多个客户。
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProjectCustomer(Base):
    """项目与客户的多对多关联。"""

    __tablename__ = "project_customers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=utc_now,
    )

    __table_args__ = (UniqueConstraint("project_id", "customer_id", name="uq_project_customers_project_customer"),)

    project: Mapped["Project"] = relationship("Project", back_populates="project_customers")
    customer: Mapped["Customer"] = relationship("Customer", back_populates="project_customers")

    def __repr__(self) -> str:
        return f"<ProjectCustomer project_id={self.project_id} customer_id={self.customer_id}>"
