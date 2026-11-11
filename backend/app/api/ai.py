"""
AI 配置与对话 API：动态配置、连接测试、带 Function Calling 的对话。
统一调度：前端聊天通过 AIConfig 表获取当前生效的模型配置。
意图执行：AI 解析出 update_project 等指令后，后端执行数据库操作并写入 AuditLog。
飞书相关 HTTP 路由见 app.api.ai_feishu（仅服务端部署注册）。
"""
import asyncio
import logging
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.models import AIConfig, SystemLog
from app.models.log import ChatRecord
from app.schemas.ai_config import (
    AIConfigConnectionTestResult,
    AIConfigCreate,
    AIConfigGetResponse,
    AIConfigInDB,
    AIConfigTestRequest,
)
from app.api.auth import get_current_user
from app.models.user import User
from app.services.ai_engine import (
    chat_and_execute_tools,
    get_active_config,
    get_ai_chat_timeout_stage,
    normalize_ollama_base_url,
    OllamaUserFacingError,
    test_connection,
)

router = APIRouter(prefix="/ai", tags=["ai"])
logger = logging.getLogger(__name__)

# 同一用户并发 AI chat：避免重复点击导致多条长耗时 Ollama 请求叠压
_ai_chat_busy_user_ids: set[int] = set()
_ai_chat_busy_guard = asyncio.Lock()


@router.get("/config", response_model=AIConfigGetResponse)
async def get_ai_config(db: AsyncSession = Depends(get_db)) -> AIConfigGetResponse:
    """获取当前生效的 AI 配置；未配置时返回默认空值（空字符串地址等），避免前端报错。"""
    config = await get_active_config(db)
    if config is None:
        return AIConfigGetResponse(id=0, model_name="", base_url="", is_active=False)
    return AIConfigGetResponse(
        id=config.id,
        model_name=config.model_name,
        base_url=config.base_url or "",
        is_active=config.is_active,
    )


@router.post("/config", response_model=AIConfigInDB)
async def save_ai_config(
    body: AIConfigCreate,
    db: AsyncSession = Depends(get_db),
) -> AIConfig:
    """保存 AI 配置；若 body.is_active 为 True，会将其他记录的 is_active 置为 False。"""
    try:
        normalized_base = normalize_ollama_base_url(body.base_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if body.is_active:
        await db.execute(update(AIConfig).values(is_active=False))
        await db.flush()
    orm = AIConfig(
        model_name=body.model_name.strip(),
        base_url=normalized_base,
        is_active=body.is_active,
    )
    db.add(orm)
    await db.flush()
    await db.refresh(orm)
    return orm


@router.post("/test-connection", response_model=AIConfigConnectionTestResult)
async def ai_test_connection(body: AIConfigTestRequest) -> dict[str, Any]:
    """测试 base_url + model_name；无论成败均返回结构化诊断（HTTP 200）。"""
    return await test_connection(body.base_url, body.model_name)


@router.post("/chat")
async def ai_chat(
    body: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    发送对话；使用 AIConfig 统一调度。
    若 AI 返回 tool_calls，则执行数据库操作并写入 AuditLog，再返回执行结果。
    请求体: { "messages": [ {"role": "user", "content": "..." }, ... ] }
    需登录：创建日程/提醒等工具依赖当前用户的 operator_user_id。
    """
    messages = body.get("messages")
    if not messages or not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="请提供 messages 数组")

    uid = int(current_user.id)
    async with _ai_chat_busy_guard:
        if uid in _ai_chat_busy_user_ids:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "上一条 AI 请求仍在处理中，请稍候或取消后重试。",
                    "status": "busy",
                    "timeout_stage": "unknown",
                    "elapsed_ms": 0,
                    "error_status": "busy",
                },
            )
        _ai_chat_busy_user_ids.add(uid)

    max_total = max(10, int(getattr(settings, "AI_OLLAMA_MAX_TOTAL_SECONDS", 120)))
    t_wall = time.perf_counter()
    try:
        try:
            async with asyncio.timeout(max_total):
                out = await chat_and_execute_tools(
                    db,
                    messages,
                    operator_source="web",
                    operator_user_id=current_user.id,
                )
        except asyncio.TimeoutError:
            elapsed_ms = int((time.perf_counter() - t_wall) * 1000)
            logger.warning(
                "event=ai_chat_failed module=ai.chat status=timeout timeout_stage=%s elapsed_ms=%s user_id=%s",
                get_ai_chat_timeout_stage(),
                elapsed_ms,
                uid,
            )
            raise HTTPException(
                status_code=504,
                detail={
                    "message": "本次对话总耗时超过上限，已终止以保护界面不长期卡住。",
                    "status": "timeout",
                    "timeout_stage": get_ai_chat_timeout_stage(),
                    "elapsed_ms": elapsed_ms,
                    "error_status": "timeout",
                },
            )
    except OllamaUserFacingError as e:
        db.add(
            SystemLog(
                level="ERROR",
                module="ai.chat",
                message=(
                    f"ollama_request_failed status={e.status} base_url={e.base_url} "
                    f"model_name={e.model_name} timeout_stage={getattr(e, 'timeout_stage', None)} "
                    f"summary={e.message}"
                ),
            )
        )
        await db.flush()
        logger.warning(
            "event=ai_chat_failed module=ai.chat status=%s timeout_stage=%s diagnostic=%s",
            e.status,
            getattr(e, "timeout_stage", None),
            getattr(e, "diagnostic", None),
        )
        diag_e = dict(getattr(e, "diagnostic", None) or {})
        diag_e.setdefault("elapsed_ms", None)
        raise HTTPException(
            status_code=503,
            detail={
                "message": e.message,
                "status": e.status,
                "base_url": e.base_url,
                "model_name": e.model_name,
                "timeout_stage": getattr(e, "timeout_stage", None),
                "error_status": getattr(e, "error_status", e.status),
                "partial_results": getattr(e, "partial_results", None),
                **diag_e,
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
        db.add(
            SystemLog(
                level="ERROR",
                module="ai.chat",
                message=f"ai upstream connection/timeout (unexpected path): {e!s}",
            )
        )
        await db.flush()
        raise HTTPException(
            status_code=503,
            detail={
                "message": "无法连接 AI 服务，请确认 Ollama 已启动且地址正确。",
                "status": "unknown_error",
                "base_url": "",
                "model_name": "",
                "timeout_stage": "ollama_first_call",
            },
        )
    except httpx.TimeoutException as e:
        db.add(
            SystemLog(
                level="ERROR",
                module="ai.chat",
                message=f"ai upstream timeout: {e!s}",
            )
        )
        await db.flush()
        raise HTTPException(
            status_code=504,
            detail={
                "message": "AI 服务响应超时，请稍后重试",
                "status": "timeout",
                "base_url": "",
                "model_name": "",
                "timeout_stage": "unknown",
            },
        )
    except httpx.HTTPStatusError as e:
        msg = (e.response.text or "").lower()
        if e.response.status_code == 503 or "not ready" in msg or "loading" in msg:
            raise HTTPException(
                status_code=503,
                detail="AI 模型正在预热，请 3～5 秒后重试",
            )
        db.add(
            SystemLog(
                level="ERROR",
                module="ai.chat",
                message=f"ai upstream http error: {e!s}",
            )
        )
        await db.flush()
        raise HTTPException(status_code=502, detail="AI 服务暂时不可用，请稍后重试")
    except httpx.HTTPError as e:
        db.add(
            SystemLog(
                level="ERROR",
                module="ai.chat",
                message=f"ai upstream http error: {e!s}",
            )
        )
        await db.flush()
        raise HTTPException(status_code=502, detail="AI 服务暂时不可用，请稍后重试")
    finally:
        async with _ai_chat_busy_guard:
            _ai_chat_busy_user_ids.discard(uid)

    # 记录对话：用户问题 + AI 回复 + tool_calls / execution_results
    try:
        assistant_message = out.get("message") or {}
        assistant_text = (assistant_message.get("content") or "").strip() if isinstance(assistant_message, dict) else ""
        tool_calls = (assistant_message.get("tool_calls") or []) if isinstance(assistant_message, dict) else []
        execution_results = out.get("execution_results") or []
        last_user_text = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user_text = (m.get("content") or "").strip()
                break
        db.add(
            ChatRecord(
                user_message=last_user_text or "",
                ai_response=assistant_text or "",
                tool_calls={
                    "tool_calls": tool_calls,
                    "execution_results": execution_results,
                },
                channel="web",
            )
        )
        await db.flush()
    except Exception:
        # 记录失败不影响主流程
        pass
    return out
