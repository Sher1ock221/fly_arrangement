from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.system_config import SystemConfig


FEISHU_CONFIG_KEYS = {
    "app_id": "feishu.app_id",
    "app_secret": "feishu.app_secret",
    "verification_token": "feishu.verification_token",
    "encrypt_key": "feishu.encrypt_key",
    "signature_check": "feishu.signature_check",
    "enable_whitelist": "feishu.enable_whitelist",
    "whitelist_open_ids": "feishu.whitelist_open_ids",
    "bot_name": "feishu.bot_name",
    "public_api_base_url": "app.public_api_base_url",
}

FEISHU_KEY_DESCRIPTIONS = {
    FEISHU_CONFIG_KEYS["app_id"]: "飞书应用 App ID",
    FEISHU_CONFIG_KEYS["app_secret"]: "飞书应用 App Secret",
    FEISHU_CONFIG_KEYS["verification_token"]: "飞书事件订阅 Verification Token",
    FEISHU_CONFIG_KEYS["encrypt_key"]: "飞书事件订阅 Encrypt Key",
    FEISHU_CONFIG_KEYS["signature_check"]: "飞书 webhook 签名校验开关",
    FEISHU_CONFIG_KEYS["enable_whitelist"]: "飞书白名单开关",
    FEISHU_CONFIG_KEYS["whitelist_open_ids"]: "飞书白名单 open_id 列表",
    FEISHU_CONFIG_KEYS["bot_name"]: "飞书机器人名称（群聊@识别）",
    FEISHU_CONFIG_KEYS["public_api_base_url"]: "公网 API 基础地址",
}

FEISHU_SECRET_KEYS = {
    FEISHU_CONFIG_KEYS["app_secret"],
    FEISHU_CONFIG_KEYS["verification_token"],
    FEISHU_CONFIG_KEYS["encrypt_key"],
}

FEISHU_ENV_FALLBACKS = {
    FEISHU_CONFIG_KEYS["app_id"]: settings.FEISHU_APP_ID,
    FEISHU_CONFIG_KEYS["app_secret"]: settings.FEISHU_APP_SECRET,
    FEISHU_CONFIG_KEYS["verification_token"]: settings.FEISHU_VERIFICATION_TOKEN,
    FEISHU_CONFIG_KEYS["encrypt_key"]: settings.FEISHU_ENCRYPT_KEY,
    FEISHU_CONFIG_KEYS["signature_check"]: str(settings.FEISHU_ENABLE_SIGNATURE_CHECK).lower(),
    FEISHU_CONFIG_KEYS["enable_whitelist"]: str(settings.FEISHU_ENABLE_WHITELIST).lower(),
    FEISHU_CONFIG_KEYS["whitelist_open_ids"]: settings.FEISHU_WHITELIST_OPEN_IDS,
    FEISHU_CONFIG_KEYS["bot_name"]: settings.FEISHU_BOT_NAME,
    FEISHU_CONFIG_KEYS["public_api_base_url"]: settings.PUBLIC_API_BASE_URL,
}


def _to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def normalize_public_api_base_url(value: str | None) -> str:
    return (str(value or "").strip()).rstrip("/")


def build_feishu_urls(public_api_base_url: str | None) -> tuple[str | None, str | None]:
    base = normalize_public_api_base_url(public_api_base_url)
    if not base:
        return None, None
    return f"{base}/api/v1/ai/feishu-webhook", f"{base}/api/v1/ai/feishu-undo"


def is_non_public_base_url(public_api_base_url: str | None) -> bool:
    base = normalize_public_api_base_url(public_api_base_url)
    if not base:
        return False
    try:
        host = (urlparse(base).hostname or "").lower()
    except Exception:
        return False
    if host in {"localhost", "127.0.0.1"}:
        return True
    return host.startswith("10.") or host.startswith("192.168.") or host.startswith("172.16.")


def mask_secret(value: str | None) -> str | None:
    if value is None:
        return None
    if value == "":
        return ""
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}{'*' * (len(value) - 4)}{value[-2:]}"


async def get_config(db: AsyncSession, key: str) -> str | None:
    row = (
        await db.execute(select(SystemConfig).where(SystemConfig.config_key == key).limit(1))
    ).scalar_one_or_none()
    if row is None:
        return None
    return row.config_value


async def set_config(
    db: AsyncSession,
    key: str,
    value: str | None,
    *,
    is_secret: bool = False,
    description: str | None = None,
) -> SystemConfig:
    row = (
        await db.execute(select(SystemConfig).where(SystemConfig.config_key == key).limit(1))
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if row is None:
        row = SystemConfig(
            config_key=key,
            config_value=value,
            is_secret=is_secret,
            description=description,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        row.config_value = value
        row.is_secret = is_secret
        if description is not None:
            row.description = description
        row.updated_at = now
    await db.flush()
    return row


async def bulk_get(db: AsyncSession, keys: list[str]) -> dict[str, str | None]:
    if not keys:
        return {}
    rows = list(
        (
            await db.execute(select(SystemConfig).where(SystemConfig.config_key.in_(keys)))
        ).scalars().all()
    )
    mapping = {r.config_key: r.config_value for r in rows}
    return {k: mapping.get(k) for k in keys}


async def bulk_set(
    db: AsyncSession,
    configs: dict[str, dict[str, Any]],
) -> None:
    for key, cfg in configs.items():
        await set_config(
            db,
            key,
            cfg.get("value"),
            is_secret=bool(cfg.get("is_secret", False)),
            description=cfg.get("description"),
        )


@dataclass
class EffectiveConfigValue:
    value: str | None
    source: str


async def get_effective_config(
    db: AsyncSession,
    key: str,
    *,
    env_fallback: str | None = None,
) -> EffectiveConfigValue:
    db_value = await get_config(db, key)
    if db_value not in (None, ""):
        return EffectiveConfigValue(value=db_value, source="db")
    if env_fallback not in (None, ""):
        return EffectiveConfigValue(value=env_fallback, source="env")
    return EffectiveConfigValue(value=None, source="none")


async def get_feishu_config(db: AsyncSession) -> dict[str, Any]:
    effective: dict[str, EffectiveConfigValue] = {}
    for key in FEISHU_CONFIG_KEYS.values():
        effective[key] = await get_effective_config(
            db, key, env_fallback=FEISHU_ENV_FALLBACKS.get(key)
        )
    sources = {v.source for v in effective.values() if v.source != "none"}
    if not sources:
        source_summary = "env"
    elif len(sources) == 1:
        source_summary = next(iter(sources))
    else:
        source_summary = "mixed"

    app_id = effective[FEISHU_CONFIG_KEYS["app_id"]].value
    app_secret = effective[FEISHU_CONFIG_KEYS["app_secret"]].value
    verification_token = effective[FEISHU_CONFIG_KEYS["verification_token"]].value
    encrypt_key = effective[FEISHU_CONFIG_KEYS["encrypt_key"]].value
    signature_check = _to_bool(
        effective[FEISHU_CONFIG_KEYS["signature_check"]].value,
        default=settings.FEISHU_ENABLE_SIGNATURE_CHECK,
    )
    enable_whitelist = _to_bool(
        effective[FEISHU_CONFIG_KEYS["enable_whitelist"]].value,
        default=settings.FEISHU_ENABLE_WHITELIST,
    )
    whitelist_open_ids = effective[FEISHU_CONFIG_KEYS["whitelist_open_ids"]].value or ""
    bot_name = effective[FEISHU_CONFIG_KEYS["bot_name"]].value or ""
    public_api_base_url = normalize_public_api_base_url(
        effective[FEISHU_CONFIG_KEYS["public_api_base_url"]].value or ""
    )
    webhook_path = "/api/v1/ai/feishu-webhook"
    undo_path = "/api/v1/ai/feishu-undo"
    webhook_url, undo_url = build_feishu_urls(public_api_base_url)
    whitelist_count = len([x for x in str(whitelist_open_ids).split(",") if x.strip()])

    verification_token_source = effective[FEISHU_CONFIG_KEYS["verification_token"]].source

    return {
        "app_id": app_id or "",
        "app_secret": app_secret or "",
        "verification_token": verification_token or "",
        "encrypt_key": encrypt_key or "",
        "signature_check": signature_check,
        "enable_whitelist": enable_whitelist,
        "whitelist_open_ids": whitelist_open_ids,
        "bot_name": bot_name,
        "public_api_base_url": public_api_base_url,
        "webhook_path": webhook_path,
        "undo_path": undo_path,
        "webhook_url": webhook_url,
        "undo_url": undo_url,
        "app_id_configured": bool(app_id),
        "public_api_base_url_configured": bool(public_api_base_url),
        "app_secret_configured": bool(app_secret),
        "verification_token_configured": bool(verification_token),
        "encrypt_key_configured": bool(encrypt_key),
        "whitelist_count": whitelist_count,
        "source_summary": source_summary,
        "config_source": source_summary,
        "app_secret_masked": mask_secret(app_secret),
        "verification_token_masked": mask_secret(verification_token),
        "encrypt_key_masked": mask_secret(encrypt_key),
        "_verification_token_source": verification_token_source,
    }


async def save_feishu_config(db: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    current = await get_feishu_config(db)
    app_id = payload.get("app_id")
    app_secret = payload.get("app_secret")
    verification_token = payload.get("verification_token")
    encrypt_key = payload.get("encrypt_key")
    signature_check = payload.get("signature_check")
    if signature_check is None:
        signature_check = payload.get("enable_signature_check")
    enable_whitelist = payload.get("enable_whitelist")
    whitelist_open_ids = payload.get("whitelist_open_ids")
    bot_name = payload.get("bot_name")
    public_api_base_url = payload.get("public_api_base_url")
    keep_existing_app_secret = bool(payload.get("keep_existing_app_secret", True))
    keep_existing_verification_token = bool(payload.get("keep_existing_verification_token", True))
    keep_existing_encrypt_key = bool(payload.get("keep_existing_encrypt_key", True))

    await set_config(
        db,
        FEISHU_CONFIG_KEYS["app_id"],
        (str(app_id).strip() if app_id is not None else current["app_id"]) or None,
        is_secret=False,
        description=FEISHU_KEY_DESCRIPTIONS[FEISHU_CONFIG_KEYS["app_id"]],
    )
    if app_secret is not None and str(app_secret).strip():
        app_secret_value: str | None = str(app_secret).strip()
    elif keep_existing_app_secret:
        app_secret_value = await get_config(db, FEISHU_CONFIG_KEYS["app_secret"])
    else:
        app_secret_value = None
    await set_config(
        db,
        FEISHU_CONFIG_KEYS["app_secret"],
        app_secret_value,
        is_secret=True,
        description=FEISHU_KEY_DESCRIPTIONS[FEISHU_CONFIG_KEYS["app_secret"]],
    )

    if verification_token is not None and str(verification_token).strip():
        verification_token_value: str | None = str(verification_token).strip()
    elif keep_existing_verification_token:
        verification_token_value = await get_config(
            db, FEISHU_CONFIG_KEYS["verification_token"]
        )
    else:
        verification_token_value = None
    await set_config(
        db,
        FEISHU_CONFIG_KEYS["verification_token"],
        verification_token_value,
        is_secret=True,
        description=FEISHU_KEY_DESCRIPTIONS[FEISHU_CONFIG_KEYS["verification_token"]],
    )

    if encrypt_key is not None and str(encrypt_key).strip():
        encrypt_key_value: str | None = str(encrypt_key).strip()
    elif keep_existing_encrypt_key:
        encrypt_key_value = await get_config(db, FEISHU_CONFIG_KEYS["encrypt_key"])
    else:
        encrypt_key_value = None
    await set_config(
        db,
        FEISHU_CONFIG_KEYS["encrypt_key"],
        encrypt_key_value,
        is_secret=True,
        description=FEISHU_KEY_DESCRIPTIONS[FEISHU_CONFIG_KEYS["encrypt_key"]],
    )

    if signature_check is not None:
        await set_config(
            db,
            FEISHU_CONFIG_KEYS["signature_check"],
            str(bool(signature_check)).lower(),
            is_secret=False,
            description=FEISHU_KEY_DESCRIPTIONS[FEISHU_CONFIG_KEYS["signature_check"]],
        )
    if enable_whitelist is not None:
        await set_config(
            db,
            FEISHU_CONFIG_KEYS["enable_whitelist"],
            str(bool(enable_whitelist)).lower(),
            is_secret=False,
            description=FEISHU_KEY_DESCRIPTIONS[FEISHU_CONFIG_KEYS["enable_whitelist"]],
        )
    if whitelist_open_ids is not None:
        await set_config(
            db,
            FEISHU_CONFIG_KEYS["whitelist_open_ids"],
            str(whitelist_open_ids).strip(),
            is_secret=False,
            description=FEISHU_KEY_DESCRIPTIONS[FEISHU_CONFIG_KEYS["whitelist_open_ids"]],
        )
    if bot_name is not None:
        await set_config(
            db,
            FEISHU_CONFIG_KEYS["bot_name"],
            str(bot_name).strip(),
            is_secret=False,
            description=FEISHU_KEY_DESCRIPTIONS[FEISHU_CONFIG_KEYS["bot_name"]],
        )
    if public_api_base_url is not None:
        await set_config(
            db,
            FEISHU_CONFIG_KEYS["public_api_base_url"],
            normalize_public_api_base_url(str(public_api_base_url)),
            is_secret=False,
            description=FEISHU_KEY_DESCRIPTIONS[FEISHU_CONFIG_KEYS["public_api_base_url"]],
        )

    return await get_feishu_config(db)
