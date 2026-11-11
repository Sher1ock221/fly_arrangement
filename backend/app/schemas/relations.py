"""
跨模块轻量关系/摘要 schema。

设计目标：
- 避免 project.py / customer.py 之间互相 import 完整读模型
- 让被其它模块引用的 brief 类型稳定、低耦合
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class CustomerBrief(BaseModel):
    """客户简要信息（用于项目关联客户列表）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="客户主键")
    name: str = Field(..., description="客户名称")
    company: str | None = Field(None, description="公司")
    position: str | None = Field(None, description="职位")


class ProjectBriefForCustomer(BaseModel):
    """客户详情中的项目简要信息。"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="主键")
    project_no: str | None = Field(None, description="项目编号")
    name: str = Field(..., description="项目名称")
    status: str | None = Field(None, description="状态")
    deadline: date | None = Field(None, description="截止日期")
    owner: str | None = Field(None, description="负责人")
    related_customers: list[CustomerBrief] = Field(default_factory=list, description="关联客户简要列表")

