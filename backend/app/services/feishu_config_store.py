"""
飞书非敏感配置存储（用于后台页面管理）。
持久化到本地 JSON 文件，不包含任何密钥信息。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config import settings

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "data" / "feishu_config.json"


def _ensure_parent() -> None:
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)


def _default_config() -> dict[str, Any]:
    return {
        "enable_whitelist": bool(settings.FEISHU_ENABLE_WHITELIST),
        "whitelist_open_ids": str(settings.FEISHU_WHITELIST_OPEN_IDS or ""),
        "enable_signature_check": bool(settings.FEISHU_ENABLE_SIGNATURE_CHECK),
        "bot_name": str(settings.FEISHU_BOT_NAME or ""),
    }


def get_feishu_runtime_config() -> dict[str, Any]:
    base = _default_config()
    if not _CONFIG_PATH.exists():
        return base
    try:
        data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return base
        base.update({
            "enable_whitelist": bool(data.get("enable_whitelist", base["enable_whitelist"])),
            "whitelist_open_ids": str(data.get("whitelist_open_ids", base["whitelist_open_ids"]) or ""),
            "enable_signature_check": bool(data.get("enable_signature_check", base["enable_signature_check"])),
            "bot_name": str(data.get("bot_name", base["bot_name"]) or ""),
        })
        return base
    except Exception:
        return base


def save_feishu_runtime_config(payload: dict[str, Any]) -> dict[str, Any]:
    current = get_feishu_runtime_config()
    next_config = {
        "enable_whitelist": bool(payload.get("enable_whitelist", current["enable_whitelist"])),
        "whitelist_open_ids": str(payload.get("whitelist_open_ids", current["whitelist_open_ids"]) or ""),
        "enable_signature_check": bool(payload.get("enable_signature_check", current["enable_signature_check"])),
        "bot_name": str(payload.get("bot_name", current["bot_name"]) or ""),
    }
    _ensure_parent()
    _CONFIG_PATH.write_text(
        json.dumps(next_config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return next_config
