"""
Ollama 健康检查与预热：应用启动时预热模型，降低首条请求失败率。
不写业务日志、不创建聊天记录，仅做连接与最小推理。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.ai_engine import get_active_config, normalize_ollama_base_url

logger = logging.getLogger(__name__)

# 模块级状态，供 /health 或 /ai/ready 读取（不写 DB）
_ollama_status: dict[str, Any] = {
    "ollama_reachable": False,
    "model_ready": False,
    "last_warmup_at": None,
    "last_error": None,
}


def get_ollama_status() -> dict[str, Any]:
    """返回当前 Ollama 就绪状态（只读）。"""
    return dict(_ollama_status)


def _is_retryable_error(e: Exception) -> bool:
    """是否为连接/冷启动类错误，可重试。"""
    msg = (getattr(e, "message", "") or str(e)).lower()
    if isinstance(e, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout)):
        return True
    if "connection refused" in msg or "connection reset" in msg:
        return True
    if "timeout" in msg or "timed out" in msg:
        return True
    if "not ready" in msg or "loading" in msg or "unavailable" in msg:
        return True
    return False


async def check_ollama_reachable(base_url: str, model_name: str) -> tuple[bool, str | None]:
    """
    检查 Ollama 是否可连接且模型存在。
    返回 (ok, error_message)。
    """
    url = base_url.rstrip("/") + "/api/show"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json={"model": model_name})
            if r.status_code == 200:
                return True, None
            return False, r.text or f"HTTP {r.status_code}"
    except httpx.ConnectError as e:
        return False, f"连接失败: {e!s}"
    except httpx.TimeoutException as e:
        return False, f"超时: {e!s}"
    except Exception as e:
        return False, str(e)


async def warmup_ping(base_url: str, model_name: str) -> tuple[bool, str | None]:
    """
    对当前模型发送一次最小推理请求（ping）。
    返回 (ok, error_message)。
    """
    url = base_url.rstrip("/") + "/api/chat"
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
        "options": {"num_predict": 2},
    }
    warmup_timeout_seconds = max(1, int(settings.OLLAMA_WARMUP_TIMEOUT_SECONDS))
    logger.info(
        "event=ollama_warmup_ping_started base_url=%s model=%s timeout_s=%s",
        base_url,
        model_name,
        warmup_timeout_seconds,
    )
    try:
        async with httpx.AsyncClient(timeout=float(warmup_timeout_seconds)) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            logger.info("event=ollama_warmup_ping_finished base_url=%s model=%s ok=1", base_url, model_name)
            return True, None
    except httpx.ConnectError as e:
        return False, f"连接失败: {e!s}"
    except httpx.TimeoutException as e:
        return False, f"推理超时: {e!s}"
    except Exception as e:
        return False, str(e)


async def run_warmup(db: AsyncSession) -> None:
    """
    执行一次预热：读当前生效配置，检查连接 + 模型存在 + 最小推理。
    若 Ollama 未就绪则延迟重试有限次数，不抛错、不阻塞应用启动。
    """
    global _ollama_status
    config = await get_active_config(db)
    if config is None:
        _ollama_status["last_error"] = "no active AI config"
        _ollama_status["last_warmup_at"] = datetime.now(timezone.utc).isoformat()
        return

    model_name = (config.model_name or "").strip()
    try:
        base_url = normalize_ollama_base_url(config.base_url or "")
    except ValueError as e:
        _ollama_status["last_error"] = f"invalid ollama base_url: {e!s}"
        _ollama_status["last_warmup_at"] = datetime.now(timezone.utc).isoformat()
        return
    if not model_name:
        _ollama_status["last_error"] = "model_name empty"
        _ollama_status["last_warmup_at"] = datetime.now(timezone.utc).isoformat()
        return

    warmup_retries = max(0, int(settings.OLLAMA_WARMUP_RETRIES))
    warmup_retry_delay_sec = max(0, int(settings.OLLAMA_WARMUP_RETRY_DELAY_SECONDS))
    warmup_timeout_seconds = max(1, int(settings.OLLAMA_WARMUP_TIMEOUT_SECONDS))
    total_attempts = warmup_retries + 1
    logger.warning(
        "ollama warmup config base_url=%s timeout=%ss retries=%s retry_delay=%ss model=%s",
        base_url,
        warmup_timeout_seconds,
        warmup_retries,
        warmup_retry_delay_sec,
        model_name,
    )

    last_err: str | None = None
    for attempt in range(1, total_attempts + 1):
        ok, err = await check_ollama_reachable(base_url, model_name)
        if not ok:
            last_err = err
            logger.info(
                "ollama warmup attempt %s/%s: reachable check failed: %s",
                attempt, total_attempts, err,
            )
            if attempt < total_attempts:
                await asyncio.sleep(warmup_retry_delay_sec)
            continue

        _ollama_status["ollama_reachable"] = True
        ok, err = await warmup_ping(base_url, model_name)
        if not ok:
            last_err = err
            logger.info(
                "ollama warmup attempt %s/%s: ping failed: %s",
                attempt, total_attempts, err,
            )
            if attempt < total_attempts:
                await asyncio.sleep(warmup_retry_delay_sec)
            continue

        _ollama_status["model_ready"] = True
        _ollama_status["last_error"] = None
        _ollama_status["last_warmup_at"] = datetime.now(timezone.utc).isoformat()
        logger.info("ollama warmup success after attempt %s", attempt)
        return

    _ollama_status["ollama_reachable"] = False
    _ollama_status["model_ready"] = False
    _ollama_status["last_error"] = last_err
    _ollama_status["last_warmup_at"] = datetime.now(timezone.utc).isoformat()
    logger.warning("ollama warmup failed after %s attempts: %s", total_attempts, last_err)
