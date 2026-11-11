"""对话会话 API 的 Pydantic 模型。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ConversationCreate(BaseModel):
    """创建会话请求体。"""

    title: str = Field(default="新对话", max_length=256)


class ConversationUpdate(BaseModel):
    """更新会话（如标题）请求体。"""

    title: str = Field(..., min_length=1, max_length=256)


class ConversationResponse(BaseModel):
    """会话列表/详情返回。"""

    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    source: str = "web"
    created_at: datetime
    updated_at: datetime


class SummarizeTitleRequest(BaseModel):
    """生成标题请求体：传入前几条消息内容。"""

    messages: list[dict[str, str]] = Field(
        ...,
        description="消息列表，每项含 role 与 content",
    )


class ConversationMessageResponse(BaseModel):
    """单条会话消息（用于 GET /conversations/:id/messages）。"""

    role: str
    content: str
    created_at: datetime | None = None
