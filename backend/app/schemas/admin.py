"""管理员接口用 Pydantic 模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

ROLES = ("admin", "user")


def _strip(v: str | None) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)
    display_name: str | None = Field(None, max_length=128)
    role: str = Field(default="user")
    is_active: bool = True
    must_change_password: bool = True

    @field_validator("username", mode="before")
    @classmethod
    def strip_username(cls, v: str) -> str:
        return str(v).strip() if v else ""

    @field_validator("role")
    @classmethod
    def role_allowed(cls, v: str) -> str:
        if v not in ROLES:
            raise ValueError("role must be admin or user")
        return v


class UserUpdateRequest(BaseModel):
    display_name: str | None = Field(None, max_length=128)
    role: str | None = None
    is_active: bool | None = None
    must_change_password: bool | None = None

    @field_validator("role")
    @classmethod
    def role_allowed(cls, v: str | None) -> str | None:
        if v is not None and v not in ROLES:
            raise ValueError("role must be admin or user")
        return v


class UserResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=6, max_length=128)
    must_change_password: bool = True


class FeishuIdentityBindRequest(BaseModel):
    user_id: int = Field(..., gt=0)
    remark: str | None = Field(None, max_length=500)

    @field_validator("remark", mode="before")
    @classmethod
    def strip_remark(cls, v: str | None) -> str | None:
        return _strip(v)


class FeishuIdentityIgnoreRequest(BaseModel):
    remark: str | None = Field(None, max_length=500)

    @field_validator("remark", mode="before")
    @classmethod
    def strip_remark(cls, v: str | None) -> str | None:
        return _strip(v)


class SwitchContextLogRequest(BaseModel):
    """管理员切换视角时记录审计用。"""
    acting_user_id: int = Field(..., gt=0, description="要切换到的用户 ID")


# ---------- 数据维护（管理员专用） ----------

LOG_CLEAR_SCOPES = ("chat", "system", "audit", "feishu", "all")
CONFIRM_TEXTS = {
    "chat": "CLEAR_CHAT_LOGS",
    "system": "CLEAR_SYSTEM_LOGS",
    "audit": "CLEAR_AUDIT_LOGS",
    "feishu": "CLEAR_FEISHU_LOGS",
    "all": "CLEAR_ALL_LOGS",
}


class LogsClearRequest(BaseModel):
    scope: str = Field(..., description="chat | system | audit | feishu | all")
    confirm_text: str = Field(..., min_length=1)

    def validate_confirm(self) -> None:
        if self.scope not in LOG_CLEAR_SCOPES:
            raise ValueError("scope 必须为 chat / system / audit / feishu / all")
        expected = CONFIRM_TEXTS.get(self.scope)
        if expected and self.confirm_text.strip() != expected:
            raise ValueError(f"确认词错误，请输入：{expected}")


class ReassignDataRequest(BaseModel):
    resource_type: str = Field(..., description="projects | customers | calendar_events | conversations")
    target_user_id: int = Field(..., gt=0)
    only_null_owner: bool = True
    before_datetime: str | None = Field(None, description="仅处理该时间之前的数据，ISO 格式")
    confirm_text: str = Field(..., min_length=1)

    def validate_confirm(self) -> None:
        if self.confirm_text.strip() != "REASSIGN_DATA":
            raise ValueError("确认词错误，请输入：REASSIGN_DATA")


class DeleteMaintenanceRequest(BaseModel):
    resource_type: str = Field(..., description="projects | customers | calendar_events | conversations")
    mode: str = Field(..., description="null_owner | by_user | by_ids")
    target_user_id: int | None = Field(None, gt=0)
    ids: list[int] | None = Field(None, description="mode=by_ids 时使用")
    before_datetime: str | None = Field(None, description="仅处理该时间之前的数据，ISO 格式")
    confirm_text: str = Field(..., min_length=1)

    def validate_confirm(self) -> None:
        if self.confirm_text.strip() != "DELETE_SELECTED_DATA":
            raise ValueError("确认词错误，请输入：DELETE_SELECTED_DATA")
