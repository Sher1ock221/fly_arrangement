"""
客户相关 Pydantic 模型：创建、更新、数据库返回。
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.customer_interaction import CustomerInteractionRead
from app.schemas.relations import ProjectBriefForCustomer


class CustomerBase(BaseModel):
    """客户通用字段。"""

    name: str = Field(..., min_length=1, max_length=256, description="客户名称")
    origin: str | None = Field(None, max_length=256, description="认识方式")
    company: str | None = Field(None, max_length=256, description="单位名称")
    profile: str | None = Field(None, description="公司简介")
    contact: str | None = Field(None, max_length=512, description="联系方式")
    future_direction: str | None = Field(None, description="未来合作方向")
    position: str | None = Field(None, max_length=128, description="担任职位")
    business_direction: str | None = Field(None, max_length=512, description="业务方向")
    notes: str | None = Field(None, description="备注")
    acquaintance_source: str | None = Field(None, max_length=256, description="如何认识/认识渠道")


class CustomerCreate(CustomerBase):
    """创建客户请求体。"""

    pass


class CustomerUpdate(BaseModel):
    """更新客户请求体（全部可选）。"""

    name: str | None = Field(None, min_length=1, max_length=256, description="客户名称")
    origin: str | None = Field(None, max_length=256, description="认识方式")
    company: str | None = Field(None, max_length=256, description="单位名称")
    profile: str | None = Field(None, description="公司简介")
    contact: str | None = Field(None, max_length=512, description="联系方式")
    future_direction: str | None = Field(None, description="未来合作方向")
    position: str | None = Field(None, max_length=128, description="担任职位")
    business_direction: str | None = Field(None, max_length=512, description="业务方向")
    notes: str | None = Field(None, description="备注")
    acquaintance_source: str | None = Field(None, max_length=256, description="如何认识/认识渠道")


class CustomerInDB(CustomerBase):
    """客户数据库返回（含 id、created_at、updated_at、owner_user_id）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="主键")
    created_at: datetime | None = Field(None, description="创建时间")
    updated_at: datetime | None = Field(None, description="更新时间")
    owner_user_id: int | None = Field(None, description="归属用户 ID")


class CustomerRead(CustomerInDB):
    """客户列表项：基础信息 + 可选统计。"""

    project_count: int | None = Field(None, description="关联项目数量")
    last_contact_at: datetime | None = Field(None, description="最近一次沟通时间")


class CustomerDetailRead(CustomerInDB):
    """客户详情：基础信息 + 关联项目列表 + 沟通记录列表。"""

    projects: list[ProjectBriefForCustomer] = Field(default_factory=list, description="该客户关联项目列表")
    interactions: list[CustomerInteractionRead] = Field(default_factory=list, description="该客户沟通记录，按 meeting_time 倒序")
