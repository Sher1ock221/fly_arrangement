"""
飞书集成相关 Pydantic 模型。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class FeishuUserInDB(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    open_id: str
    user_id: str | None = None
    union_id: str | None = None
    name: str | None = None
    avatar_url: str | None = None
    tenant_key: str | None = None
    is_active: bool
    last_seen_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class FeishuConversationInDB(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    feishu_open_id: str
    feishu_chat_id: str | None = None
    conversation_type: str
    source_conversation_id: int | None = None
    last_message_id: str | None = None
    title: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class FeishuMessageEventInDB(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_id: str | None = None
    message_id: str | None = None
    chat_id: str | None = None
    open_id: str | None = None
    event_type: str
    message_type: str | None = None
    raw_payload: Any | None = None
    process_status: str
    error_message: str | None = None
    retry_count: int
    duration_ms: int | None = None
    response_message_id: str | None = None
    created_at: datetime
    updated_at: datetime


class FeishuTokenInDB(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    token_type: str
    access_token: str
    expire_at: datetime
    created_at: datetime
    updated_at: datetime


class FeishuConfigRead(BaseModel):
    app_id: str | None = None
    app_secret_masked: str | None = None
    app_secret_configured: bool = False
    verification_token_masked: str | None = None
    verification_token_configured: bool = False
    encrypt_key_masked: str | None = None
    encrypt_key_configured: bool = False
    signature_check: bool = True
    enable_signature_check: bool = True
    enable_whitelist: bool = False
    whitelist_open_ids: str = ""
    bot_name: str = ""
    public_api_base_url: str | None = None
    public_api_base_url_configured: bool = False
    source_summary: str = "env"
    webhook_url: str | None = None
    undo_url: str | None = None
    app_id_configured: bool = False
    whitelist_count: int = 0
    config_source: str = "env"


class FeishuConfigUpdate(BaseModel):
    app_id: str | None = None
    app_secret: str | None = None
    verification_token: str | None = None
    encrypt_key: str | None = None
    signature_check: bool | None = None
    enable_signature_check: bool | None = None
    enable_whitelist: bool | None = None
    whitelist_open_ids: str | None = None
    bot_name: str | None = None
    public_api_base_url: str | None = None
    keep_existing_app_secret: bool = True
    keep_existing_verification_token: bool = True
    keep_existing_encrypt_key: bool = True


class FeishuConfigTestResult(BaseModel):
    ok: bool
    message: str
    app_id_ok: bool
    app_secret_ok: bool
    token_ok: bool
    public_api_base_url_ok: bool
    normalized_public_api_base_url: str | None = None
    has_minimum_required_config: bool
    webhook_url: str | None = None
    undo_url: str | None = None
    warnings: list[str] = []
    errors: list[str] = []
    checks: list[dict[str, str | bool]] = []
