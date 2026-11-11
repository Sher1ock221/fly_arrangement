"""
项目相关 Pydantic 模型：创建、更新、数据库返回。
"""
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal


from app.schemas.relations import CustomerBrief, ProjectBriefForCustomer


class ProjectBase(BaseModel):
    """项目通用字段。"""

    project_no: str | None = Field(None, max_length=20, description="项目编号，如 P001（可选，不传则自动生成）")
    name: str = Field(..., min_length=1, max_length=256, description="项目名称")
    deadline: date | None = Field(None, description="截止日期（历史兼容字段，建议改用 deadline_at）", deprecated=True)
    start_date: date | None = Field(None, description="开始日期（历史兼容字段，建议改用 start_time）", deprecated=True)
    deadline_at: datetime | None = Field(None, description="截止时间（日期+时间）")
    start_time: datetime | None = Field(None, description="开始时间（日期+时间）")
    goal: str | None = Field(None, max_length=1024, description="项目目标")
    owner: str | None = Field(None, max_length=128, description="负责人展示缓存（非归属真相字段）", deprecated=True)
    requirements: str | None = Field(None, description="项目内需（可滚动单行文本）")
    progress_text: str | None = Field(None, description="项目进展")
    customer_name: str | None = Field(None, max_length=256, description="历史文本客户名（建议改用 related_customers）", deprecated=True)


class ProjectCreate(ProjectBase):
    """创建项目请求体。"""

    customer_id: int | None = Field(None, description="关联客户 id（旧单客户，兼容）；与 customer_ids 二选一，customer_ids 优先")
    customer_ids: list[int] | None = Field(None, description="关联客户 id 列表，多对多；与旧 customer_id 兼容，以本字段为主")
    owner_user_id: int = Field(..., description="负责人用户ID（项目归属主字段）")


class ProjectUpdate(BaseModel):
    """更新项目请求体（全部可选，只更新提交的字段）。"""

    project_no: str | None = Field(None, max_length=20, description="项目编号")
    name: str | None = Field(None, min_length=1, max_length=256, description="项目名称")
    deadline: date | None = Field(None, description="截止日期")
    start_date: date | None = Field(None, description="开始日期")
    goal: str | None = Field(None, max_length=1024, description="项目目标")
    owner: str | None = Field(None, max_length=128, description="负责人")
    requirements: str | None = Field(None, description="项目内需")
    customer_name: str | None = Field(None, max_length=256, description="客户名称")
    customer_id: int | None = Field(None, description="关联客户 id（旧单客户，兼容）")
    customer_ids: list[int] | None = Field(None, description="关联客户 id 列表，多对多；与旧 customer_id 兼容，以本字段为主")
    owner_user_id: int | None = Field(None, description="负责人用户ID（优先于 owner 文本）")


class ProjectInDB(ProjectBase):
    """项目数据库返回（含 id、update_date、owner_user_id）。project_no 继承为 Optional，兼容无编号的旧数据。"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="主键")
    update_date: datetime | None = Field(None, description="最后更新日期")
    owner_user_id: int | None = Field(None, description="归属用户 ID")
    initiator_user_id: int | None = Field(None, description="发起人用户 ID")


class MemberBrief(BaseModel):
    user_id: int
    display_name: str
    username: str | None = None
    is_active: bool | None = None


class LegacyMemberItem(BaseModel):
    legacy_key: str
    display_name: str
    reason: str
    created_at: datetime | None = None


class ProjectShareMembersView(BaseModel):
    initiator: MemberBrief | None = None
    owner: MemberBrief | None = None
    collaborators: list[dict] = Field(default_factory=list, description="标准协作者列表（source of truth: project_collaborators）")
    legacy_members: list[LegacyMemberItem] = Field(default_factory=list, description="待清理旧成员")


class ProjectRead(ProjectInDB):
    """项目列表/详情返回：基础字段 + 关联客户列表（多对多）。"""

    related_customers: list[CustomerBrief] = Field(default_factory=list, description="关联客户简要列表")


class ProjectView(ProjectRead):
    """项目对外视图：补充角色关系与发起人展示名。"""

    access_role: Literal["owner", "collaborator"] = Field(..., description="当前有效用户在项目中的访问角色")
    is_initiator: bool = Field(False, description="当前有效用户是否为发起人")
    is_owner: bool = Field(False, description="当前有效用户是否为负责人")
    initiator_display_name: str | None = Field(None, description="发起人展示名")
