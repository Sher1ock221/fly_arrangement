"""日历日程 Pydantic 模型。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CalendarEventBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=256)
    description: str | None = Field(None)
    start_time: datetime = Field(...)
    end_time: datetime = Field(...)
    type: str = Field(default="event", pattern="^(event|project|meeting|task)$")
    project_id: int | None = Field(None)
    status: str = Field(default="scheduled", pattern="^(scheduled|confirmed|completed|cancelled)$")
    candidate_group_id: str | None = Field(None, max_length=64)
    candidate_policy: str | None = Field(None, max_length=32)
    auto_cancel_others_on_complete: bool = Field(default=False)


class CalendarEventCreate(CalendarEventBase):
    pass


class CalendarEventUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=256)
    description: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    type: str | None = Field(None, pattern="^(event|project|meeting|task)$")
    project_id: int | None = None
    status: str | None = Field(None, pattern="^(scheduled|confirmed|completed|cancelled)$")
    candidate_group_id: str | None = Field(None, max_length=64)
    candidate_policy: str | None = Field(None, max_length=32)
    auto_cancel_others_on_complete: bool | None = None


class CalendarEventInDB(CalendarEventBase):
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(...)
    owner_user_id: int | None = Field(None, description="归属用户 ID")
    created_at: datetime | None = Field(None)
    updated_at: datetime | None = Field(None)
