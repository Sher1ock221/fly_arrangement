"""
客户跟进记录相关 Pydantic 模型：创建、更新、数据库返回。
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CustomerInteractionBase(BaseModel):
    """跟进记录通用字段。"""

    meeting_time: datetime | None = Field(None, description="见面/沟通时间")
    talk_summary: str | None = Field(None, description="谈话内容")
    cooperation_direction: str | None = Field(None, max_length=512, description="业务合作方向")
    cooperation_intent: str | None = Field(None, max_length=512, description="意向合作")
    next_cooperation_plan: str | None = Field(None, max_length=512, description="下次意向合作内容")
    specific_needs: str | None = Field(None, description="具体需求")
    importance: int | None = Field(None, ge=1, le=5, description="重要性 1~5")
    source: str | None = Field(None, max_length=32, description="来源: manual / ai / feishu / web")
    raw_input: str | None = Field(None, description="原始输入，便于审计")


class CustomerInteractionCreate(CustomerInteractionBase):
    """创建客户跟进记录请求体。"""

    pass


class CustomerInteractionUpdate(BaseModel):
    """更新客户跟进记录请求体（全部可选）。"""

    meeting_time: datetime | None = Field(None, description="见面/沟通时间")
    talk_summary: str | None = Field(None, description="谈话内容")
    cooperation_direction: str | None = Field(None, max_length=512, description="业务合作方向")
    cooperation_intent: str | None = Field(None, max_length=512, description="意向合作")
    next_cooperation_plan: str | None = Field(None, max_length=512, description="下次意向合作内容")
    specific_needs: str | None = Field(None, description="具体需求")
    importance: int | None = Field(None, ge=1, le=5, description="重要性 1~5")
    source: str | None = Field(None, max_length=32, description="来源")
    raw_input: str | None = Field(None, description="原始输入")


class CustomerInteractionRead(CustomerInteractionBase):
    """客户跟进记录返回（含 id、customer_id、时间戳）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="主键")
    customer_id: int = Field(..., description="客户 id")
    created_at: datetime | None = Field(None, description="创建时间")
    updated_at: datetime | None = Field(None, description="更新时间")
