"""
系统配置相关 schema。
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SystemConfigInDB(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    config_key: str
    config_value: str | None = None
    is_secret: bool
    description: str | None = None
    created_at: datetime
    updated_at: datetime
