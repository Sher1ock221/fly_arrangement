"""
协作相关 Pydantic 模型：collaborator 管理、项目更新、客户跟进、日程评论。
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ── 协作者 ──────────────────────────────────────────


class CollaboratorAdd(BaseModel):
    """添加协作者请求。"""
    user_id: int = Field(..., description="要共享给的用户 ID")


class CollaboratorOut(BaseModel):
    """协作者返回。"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    created_by_user_id: int | None = None
    created_at: datetime | None = None
    display_name: str | None = Field(None, description="协作者显示名称")
    username: str | None = Field(None, description="协作者用户名")


# ── 项目更新 / 进度 ─────────────────────────────────


class ProjectActivityCreate(BaseModel):
    content: str = Field(..., min_length=1, description="更新内容")
    update_type: str = Field(default="note", pattern="^(progress|note|requirement)$")


class ProjectActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    author_user_id: int | None = None
    content: str
    update_type: str
    created_at: datetime | None = None
    author_display_name: str | None = Field(None, description="作者显示名称")


# ── 客户跟进 ────────────────────────────────────────


class CustomerFollowupCreate(BaseModel):
    content: str = Field(..., min_length=1, description="跟进内容")


class CustomerFollowupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    author_user_id: int | None = None
    content: str
    created_at: datetime | None = None
    author_display_name: str | None = Field(None, description="作者显示名称")


# ── 日程评论 ────────────────────────────────────────


class CalendarEventCommentCreate(BaseModel):
    content: str = Field(..., min_length=1, description="评论内容")


class CalendarEventCommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    calendar_event_id: int
    author_user_id: int | None = None
    content: str
    created_at: datetime | None = None
    author_display_name: str | None = Field(None, description="作者显示名称")


# ── ownership 转移 ─────────────────────────────────


class TransferOwnerRequest(BaseModel):
    target_user_id: int = Field(..., description="要转移给的用户 ID")
