"""
动态 AI 引擎：从 AIConfig 表读取 is_active=True 的配置，使用 httpx 调用 Ollama。
支持连接测试与 Function Calling（基于 Project/Customer Schema）。
统一调度：各入口通过 get_active_config 获取模型配置。
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse

import httpx
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.intent import detect_action_intent
from app.agent.skill_loader import load_skills
from app.agent.tool_dedupe import build_tool_dedupe_key
from app.agent.tool_schemas import build_tool_schemas_for_intent
from app.core.config import settings

# 日程意图下禁止执行的项目/客户/协作类工具（模型偶发幻觉时的执行层兜底）
_CALENDAR_INTENT_FORBIDDEN_TOOLS = frozenset({
    "list_all_projects",
    "list_projects",
    "add_resource_activity",
    "create_project",
    "upsert_project",
    "update_project",
    "update_project_fields",
    "resolve_project",
    "manage_collaborator",
    "transfer_owner",
    "confirm_or_cancel_transfer",
    "resolve_user",
    "create_customer",
    "update_customer",
    "create_customer_interaction",
})

# 工具执行成功后可用模板总结、跳过二次 Ollama 的工具名白名单
_TEMPLATE_ACTION_SUMMARY_TOOLS = frozenset({
    "create_project",
    "upsert_project",
    "create_customer",
    "create_customer_interaction",
    "create_calendar_event",
    "auto_schedule_event",
    "create_reminder_task",
    "confirm_or_cancel_schedule",
    "execute_compound_schedule",
    "execute_candidate_schedule_strategy",
})
from app.models import AIConfig, Project
from app.schemas.ai_config import AIConfigInDB
from app.services.tool_executor import execute_tool_call, execute_tool_calls

logger = logging.getLogger(__name__)

# 供 /api/v1/ai/chat 外层 asyncio.timeout 捕获时回传「当前卡住的阶段」
_ai_chat_timeout_stage: contextvars.ContextVar[str] = contextvars.ContextVar(
    "ai_chat_timeout_stage", default="unknown"
)


def get_ai_chat_timeout_stage() -> str:
    return _ai_chat_timeout_stage.get()


def set_ai_chat_timeout_stage(stage: str) -> None:
    _ai_chat_timeout_stage.set(stage)


# CST（东八区）语义：提醒与相对时间解析默认使用该语义基准
CST_TZ = timezone(timedelta(hours=8))

# Ollama 连接测试：tags 列表过长时仅返回前 N 个名，避免响应体过大
_OLLAMA_TEST_MAX_MODEL_NAMES = 80


def normalize_ollama_base_url(base_url: str) -> str:
    """
    规范化 Ollama 根地址：去空白、去尾斜杠、补全 scheme、剥离误填的 /api* 路径。
    非法或空地址抛出 ValueError（明确中文说明）。
    """
    s = (base_url or "").strip()
    if not s:
        raise ValueError("Ollama 服务地址（base_url）不能为空")

    # 先去掉末尾多余斜杠，便于后缀判断
    s = s.rstrip("/")

    lowered_full = s.lower()
    api_path_suffixes = (
        "/api/tags",
        "/api/chat",
        "/api/show",
        "/api/generate",
        "/api/version",
        "/api/ps",
        "/api/pull",
    )
    for suf in api_path_suffixes:
        if lowered_full.endswith(suf):
            s = s[: -len(suf)].rstrip("/")
            lowered_full = s.lower()
            break

    if "://" not in s:
        if s.startswith("/"):
            raise ValueError("Ollama 服务地址格式无效，请填写主机与端口，例如 http://127.0.0.1:11434")
        s = "http://" + s

    parsed = urlparse(s)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise ValueError("Ollama 地址仅支持 http 或 https 协议")
    if not parsed.netloc:
        raise ValueError("Ollama 服务地址缺少有效主机名（请检查是否漏写端口或协议）")

    path = (parsed.path or "").rstrip("/")
    path_lower = path.lower()
    if path_lower in ("", "/"):
        path_out = ""
    elif path_lower == "/api" or path_lower.startswith("/api/"):
        path_out = ""
    else:
        raise ValueError(
            "base_url 应只填写 Ollama 服务根地址，不要包含路径。"
            " 正确示例：http://127.0.0.1:11434"
        )

    out = urlunparse((parsed.scheme, parsed.netloc, path_out, "", "", "")).rstrip("/")
    return out


class OllamaUserFacingError(Exception):
    """Ollama 请求失败，携带可安全返回给前端的字段（不含 prompt/token）。"""

    def __init__(
        self,
        *,
        status: str,
        message: str,
        base_url: str,
        model_name: str,
        timeout_stage: str | None = None,
        error_status: str | None = None,
        partial_results: list[dict[str, Any]] | None = None,
        diagnostic: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.base_url = base_url
        self.model_name = model_name
        self.timeout_stage = timeout_stage or (
            "ollama_first_call" if status == "timeout" else "unknown"
        )
        self.error_status = error_status or status
        self.partial_results = partial_results
        self.diagnostic = dict(diagnostic or {})


def _is_likely_connection_refused(exc: BaseException) -> bool:
    msg = str(exc).lower()
    if "10061" in msg or "connection refused" in msg:
        return True
    if "econnrefused" in msg or "errno 61" in msg:
        return True
    if "actively refused" in msg:
        return True
    return False


def _httpx_exc_summary(exc: BaseException, max_len: int = 400) -> str:
    s = f"{type(exc).__name__}: {exc!s}"
    return s if len(s) <= max_len else s[:max_len] + "...(truncated)"


def _template_action_summary_text(step_results: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for r in step_results:
        t = str(r.get("tool_name") or "")
        s = str(r.get("execution_summary") or "").strip()
        if s:
            parts.append(f"- {t}：{s}")
    if not parts:
        return "操作已完成。"
    return "已完成以下操作：\n" + "\n".join(parts)


def _finalize_diag_total(diag: dict[str, Any] | None, t_start: float) -> None:
    if diag is None:
        return
    pe = diag.setdefault("phase_elapsed_ms", {})
    pe["total_ms"] = int((time.perf_counter() - t_start) * 1000)


# ---------- System Prompt 模块（按需组合） ----------

# 仅保留填参锚点与映射；业务意图、工具择选、假成功规则见已加载 Skill。
SYSTEM_PROMPT_FIELD_MAPPING_TEMPLATE = """【字段映射补充】
- 时间锚点（CST）：{current_datetime_iso}；今天 {current_date_iso}；明天 {tomorrow_iso}。
- 项目：优先匹配清单中的 no/project_no；编号（如 P001）优先于纯名称。
- 相对日期（明天、下周五等）按 {current_date_iso} 推算为具体 ISO 再传入 deadline 等字段。
- 中文→参数：负责人→owner；截止→deadline；目标→goal；内需→requirements；名称→name。
- 勿传 owner_user_id；归属由后端按当前登录用户补全。"""

def _agent_core_skill_names() -> list[str]:
    """Agent 路径固定前置 Skill（与 desktop_mode / tool_usage / diagnostics 分工一致）。"""
    return ["base", "desktop_mode", "reply_rules", "tool_usage", "diagnostics"]


def _intent_domain_skill_names(intent: str | None) -> list[str]:
    """按业务意图追加领域 Skill（含复合能力说明，供 Agent 与 fallback 理解边界）。"""
    mapping = {
        "calendar": ["calendar", "compound_schedule"],
        "project": ["project", "compound_business"],
        "customer": ["customer", "compound_business"],
        "reminder": ["reminder"],
        "collaboration": ["collaboration"],
    }
    return mapping.get(intent or "", [])


def _agent_loaded_skill_names(intent: str | None) -> list[str]:
    return [*_agent_core_skill_names(), *_intent_domain_skill_names(intent)]


def _build_system_prompt(
    snapshot_block: str,
    *,
    now_utc: datetime | None = None,
    intent: str | None = None,
    operator_source: str = "web",
) -> tuple[str, list[str]]:
    """基于技能文件拼装 system prompt，返回 (prompt_text, loaded_skills)。"""
    _ = operator_source  # 预留：非 web 入口可切换 core 列表而不改签名
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    now_cst = now_utc.astimezone(CST_TZ)
    current_date_iso = now_cst.strftime("%Y-%m-%d")
    tomorrow_iso = (now_cst.date() + timedelta(days=1)).isoformat()
    current_datetime_iso = now_cst.isoformat(timespec="seconds")
    field_mapping = SYSTEM_PROMPT_FIELD_MAPPING_TEMPLATE.format(
        current_datetime_iso=current_datetime_iso,
        current_date_iso=current_date_iso,
        tomorrow_iso=tomorrow_iso,
    )
    loaded_skills = _agent_loaded_skill_names(intent)
    skill_text = load_skills(loaded_skills)
    prompt_parts = [
        skill_text,
        snapshot_block,
        field_mapping,
    ]
    system_prompt = "\n\n".join(p for p in prompt_parts if p.strip())
    return system_prompt, loaded_skills


def _user_intent_suggests_action(user_text: str) -> bool:
    """检测用户消息是否包含数据操作意图（建、改、定、删等动词或客户沟通归档场景）。"""
    if not user_text or not isinstance(user_text, str):
        return False
    t = user_text.strip()
    action_keywords = (
        "建", "改", "定", "删", "新增", "修改", "删除", "创建", "设定", "更新",
        "添加", "改成", "改为", "设为", "新建", "增加", "总结", "统计", "查看",
        "列出", "改一下", "帮我", "请", "把", "给",
        "见了面", "聊了", "碰了", "沟通", "拜访", "聊一下", "跟客户", "和客户",
        "共享", "分享", "转移", "转给", "转交", "协作", "取消共享", "移除协作",
        "确认转移", "取消转移", "确认",
    )
    return any(kw in t for kw in action_keywords)


def _user_intent_suggests_creation(user_text: str) -> bool:
    if not user_text:
        return False
    creation_keywords = (
        "新建", "创建", "安排", "行程", "日程", "提醒", "每日提醒", "添加到日历", "约时间", "培训", "考试",
    )
    return any(k in user_text for k in creation_keywords)


def _user_intent_suggests_reminder(user_text: str) -> bool:
    if not user_text:
        return False
    return any(k in user_text for k in ("提醒", "每日提醒", "每天提醒"))


def _is_confirm_like_utterance(user_text: str) -> bool:
    """是否为「好的/可以/确认」这类纯确认短句。"""
    if not user_text or not isinstance(user_text, str):
        return False
    normalized = user_text.strip().strip("。.!！?？,，~～")
    if not normalized:
        return False
    confirm_words = {
        "好",
        "好的",
        "可以",
        "行",
        "确认",
        "确认了",
        "ok",
        "OK",
        "嗯",
        "嗯嗯",
    }
    return normalized in confirm_words


def _contains_success_claim(text: str) -> bool:
    if not text:
        return False
    # 「已创建待确认...」属于未真正落地，不应按成功落地识别
    if "待确认" in text:
        return False
    claims = (
        "已创建成功",
        "已安排成功",
        "已添加到日历",
        "已创建",
        "已安排",
        "飞书提醒已创建",
        "已创建飞书提醒",
        "已为您创建飞书",
    )
    return any(k in text for k in claims)


async def _has_pending_confirmable_action(db: AsyncSession, actor_user_id: int | None) -> bool:
    """检查当前用户是否存在待确认动作（如待确认日程/转移等）。"""
    if not actor_user_id:
        return False
    from app.models.pending_ai_action import PendingAiAction

    now = datetime.now(timezone.utc)
    row = (
        await db.execute(
            select(PendingAiAction.id).where(
                PendingAiAction.actor_user_id == actor_user_id,
                PendingAiAction.status == "pending",
                PendingAiAction.expires_at > now,
            ).limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


def _has_successful_creation_result(execution_results: list[dict[str, Any]]) -> bool:
    creation_tools = {
        "create_calendar_event",
        "auto_schedule_event",
        "confirm_or_cancel_schedule",
        "create_project",
        "upsert_project",
        "create_customer",
        "create_customer_interaction",
        "create_reminder_task",
        "execute_compound_schedule",
        "execute_candidate_schedule_strategy",
    }
    for r in execution_results:
        if not r.get("success"):
            continue
        tool_name = str(r.get("tool_name") or "")
        if tool_name not in creation_tools and tool_name != "suggest_schedule":
            continue
        result = r.get("result")
        if tool_name == "create_customer_interaction":
            if isinstance(result, dict) and (
                result.get("interaction_id") is not None or result.get("id") is not None
            ):
                return True
            continue
        if tool_name == "create_reminder_task":
            if isinstance(result, dict) and (result.get("reminder_task_id") is not None or result.get("id") is not None):
                return True
            continue
        if tool_name == "execute_compound_schedule":
            if isinstance(result, dict) and result.get("main_event_id") is not None:
                return True
            continue
        if tool_name in ("confirm_or_cancel_schedule", "suggest_schedule", "auto_schedule_event"):
            if isinstance(result, dict) and ("event_id" in result or "final_start" in result):
                return True
            continue
        return True
    return False


def _format_execution_results_for_prompt(execution_results: list[dict[str, Any]]) -> str:
    """将工具执行结果格式化为可读文本，供回传给模型做二次总结。"""
    parts = []
    for i, one in enumerate(execution_results, 1):
        if one.get("success"):
            summary = one.get("execution_summary")
            result = one.get("result")
            if summary:
                parts.append(f"工具{i}执行成功：{summary}")
            elif result is not None:
                try:
                    parts.append(f"工具{i}执行成功，返回数据：{json.dumps(result, ensure_ascii=False, default=str)}")
                except (TypeError, ValueError):
                    parts.append(f"工具{i}执行成功，返回：{result!s}")
            else:
                parts.append(f"工具{i}执行成功")
        else:
            parts.append(f"工具{i}执行失败：{one.get('error') or one.get('message', '未知错误')}")
    return "\n".join(parts) if parts else "（无结果）"


def _default_summary_from_results(execution_results: list[dict[str, Any]]) -> str:
    """根据 execution_results 生成默认摘要，用于工具成功但模型未返回文字时的兜底。"""
    success_count = sum(1 for r in execution_results if r.get("success"))
    if not execution_results:
        return "未执行任何工具。"
    if success_count == 0:
        return "工具执行均未成功，请检查参数或稍后重试。"
    summaries = []
    for r in execution_results:
        if not r.get("success"):
            continue
        s = r.get("execution_summary")
        if s:
            summaries.append(s)
        elif isinstance(r.get("result"), list):
            n = len(r["result"])
            summaries.append(f"共 {n} 条数据")
        else:
            summaries.append("执行成功")
    return "根据查询，" + "；".join(summaries) + "。"


async def get_active_config(db: AsyncSession) -> AIConfigInDB | None:
    """
    从数据库读取当前生效的 AI 配置（is_active=True），不存在则返回 None。
    若存在多条 active，按 id 降序取最新一条，并打 warning 日志。
    返回的 base_url 在内存中做规范化（不写库）。
    """
    count_stmt = select(func.count(AIConfig.id)).where(AIConfig.is_active.is_(True))
    active_count = int((await db.execute(count_stmt)).scalar_one() or 0)
    if active_count == 0:
        return None
    if active_count > 1:
        logger.warning(
            "multiple active AI configs detected count=%s; selecting latest by id desc",
            active_count,
        )

    result = await db.execute(
        select(AIConfig)
        .where(AIConfig.is_active.is_(True))
        .order_by(desc(AIConfig.id))
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    cfg = AIConfigInDB.model_validate(row)
    try:
        normalized = normalize_ollama_base_url(cfg.base_url)
    except ValueError as e:
        logger.warning(
            "active_ai_config_selected id=%s model_name=%s base_url=(invalid) is_active=%s normalize_error=%s",
            cfg.id,
            cfg.model_name,
            cfg.is_active,
            e,
        )
        return cfg
    logger.info(
        "active_ai_config_selected id=%s model_name=%s base_url=%s is_active=%s",
        cfg.id,
        cfg.model_name,
        normalized,
        cfg.is_active,
    )
    return cfg.model_copy(update={"base_url": normalized})


async def _get_projects_snapshot(db: AsyncSession) -> list[dict[str, str]]:
    """查询当前所有项目的 project_no 与 name，作为对话前的环境快照。"""
    result = await db.execute(select(Project).order_by(Project.id))
    rows = result.scalars().all()
    return [
        {"no": (r.project_no or "").strip(), "name": (r.name or "").strip()}
        for r in rows
    ]


def _tags_list_model_names(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return []
    models = data.get("models")
    if not isinstance(models, list):
        return []
    names: list[str] = []
    for m in models:
        if isinstance(m, dict):
            n = m.get("name")
            if isinstance(n, str) and n.strip():
                names.append(n.strip())
    return names


def _model_available_in_tags(model_name: str, tag_names: list[str]) -> bool:
    if not model_name or not tag_names:
        return False
    if model_name in tag_names:
        return True
    # 常见：用户写 qwen2.5:7b，Ollama 展示为带 digest 的变体；仍以精确匹配为主，辅以 :latest
    candidate = f"{model_name}:latest"
    if candidate in tag_names:
        return True
    return any(t == model_name or t.startswith(f"{model_name}:") for t in tag_names)


async def test_connection(base_url: str, model_name: str) -> dict[str, Any]:
    """
    诊断 Ollama：GET /api/tags，检查模型是否在列表中。
    返回统一结构（不抛异常），由 API 层决定 HTTP 状态码。
    """
    t0 = time.perf_counter()
    model_trim = (model_name or "").strip()
    empty: list[str] = []

    try:
        normalized = normalize_ollama_base_url(base_url)
    except ValueError as e:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        logger.info(
            "ollama_connection_test status=invalid_base_url base_url=(raw) model_name=%s elapsed_ms=%s available_models_count=0",
            model_trim,
            elapsed_ms,
        )
        return {
            "ok": False,
            "status": "invalid_base_url",
            "detail": str(e),
            "base_url": "",
            "model_name": model_trim,
            "available_models": empty,
            "elapsed_ms": elapsed_ms,
            "model_found": False,
            "available_models_count": 0,
        }

    tags_url = normalized + "/api/tags"
    conn_sec = max(1.0, float(settings.AI_OLLAMA_CONNECT_TIMEOUT_SECONDS))
    read_sec = min(15.0, max(3.0, float(settings.AI_OLLAMA_READ_TIMEOUT_SECONDS) * 0.2))
    timeout = httpx.Timeout(read_sec, connect=conn_sec)
    available_full: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(tags_url)
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            if r.status_code != 200:
                snippet = (r.text or "")[:200].replace("\n", " ")
                logger.info(
                    "ollama_connection_test status=http_error base_url=%s model_name=%s elapsed_ms=%s available_models_count=0 http_status=%s",
                    normalized,
                    model_trim,
                    elapsed_ms,
                    r.status_code,
                )
                return {
                    "ok": False,
                    "status": "http_error",
                    "detail": f"Ollama 返回 HTTP {r.status_code}，请检查服务版本与地址。",
                    "base_url": normalized,
                    "model_name": model_trim,
                    "available_models": empty,
                    "elapsed_ms": elapsed_ms,
                    "model_found": False,
                    "available_models_count": 0,
                }
            try:
                payload = r.json()
            except json.JSONDecodeError:
                logger.info(
                    "ollama_connection_test status=http_error base_url=%s model_name=%s elapsed_ms=%s available_models_count=0",
                    normalized,
                    model_trim,
                    elapsed_ms,
                )
                return {
                    "ok": False,
                    "status": "http_error",
                    "detail": "Ollama 响应不是合法 JSON，请确认目标为 Ollama 服务地址。",
                    "base_url": normalized,
                    "model_name": model_trim,
                    "available_models": empty,
                    "elapsed_ms": elapsed_ms,
                    "model_found": False,
                    "available_models_count": 0,
                }
            available_full = _tags_list_model_names(payload)
            available_trim = available_full[:_OLLAMA_TEST_MAX_MODEL_NAMES]

            if not _model_available_in_tags(model_trim, available_full):
                logger.info(
                    "ollama_connection_test status=model_not_found base_url=%s model_name=%s elapsed_ms=%s available_models_count=%s",
                    normalized,
                    model_trim,
                    elapsed_ms,
                    len(available_full),
                )
                preview = ", ".join(available_trim[:20])
                if len(available_trim) > 20:
                    preview += "，…"
                detail = (
                    f"当前 Ollama 中未找到模型「{model_trim}」。"
                    f"可用模型示例：{preview if preview else '（无）'}"
                )
                return {
                    "ok": False,
                    "status": "model_not_found",
                    "detail": detail,
                    "base_url": normalized,
                    "model_name": model_trim,
                    "available_models": available_trim,
                    "elapsed_ms": elapsed_ms,
                    "model_found": False,
                    "available_models_count": len(available_full),
                }

            # 可选：短超时 POST /api/show（失败不阻断 tags 成功）
            show_url = normalized + "/api/show"
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(4.0, connect=3.0)) as show_client:
                    sr = await show_client.post(show_url, json={"model": model_trim})
                if sr.status_code != 200:
                    logger.info(
                        "ollama_connection_test optional_show_non_200 status=%s base_url=%s model_name=%s",
                        sr.status_code,
                        normalized,
                        model_trim,
                    )
            except Exception as show_exc:
                logger.info(
                    "ollama_connection_test optional_show_skipped base_url=%s model_name=%s err=%s",
                    normalized,
                    model_trim,
                    _httpx_exc_summary(show_exc),
                )

            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            logger.info(
                "ollama_connection_test status=ok base_url=%s model_name=%s elapsed_ms=%s available_models_count=%s",
                normalized,
                model_trim,
                elapsed_ms,
                len(available_full),
            )
            return {
                "ok": True,
                "status": "ok",
                "detail": "模型可用，Ollama 服务响应正常。",
                "base_url": normalized,
                "model_name": model_trim,
                "available_models": available_trim,
                "elapsed_ms": elapsed_ms,
                "model_found": True,
                "available_models_count": len(available_full),
            }

    except httpx.ConnectTimeout as e:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        logger.info(
            "ollama_connection_test status=timeout base_url=%s model_name=%s elapsed_ms=%s available_models_count=0",
            normalized,
            model_trim,
            elapsed_ms,
        )
        return {
            "ok": False,
            "status": "timeout",
            "detail": "Ollama 服务响应超时，可能正在加载模型或机器资源不足。",
            "base_url": normalized,
            "model_name": model_trim,
            "available_models": empty,
            "elapsed_ms": elapsed_ms,
            "model_found": False,
            "available_models_count": 0,
        }
    except httpx.ReadTimeout as e:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        logger.info(
            "ollama_connection_test status=timeout base_url=%s model_name=%s elapsed_ms=%s available_models_count=0",
            normalized,
            model_trim,
            elapsed_ms,
        )
        return {
            "ok": False,
            "status": "timeout",
            "detail": "Ollama 服务响应超时，可能正在加载模型或机器资源不足。",
            "base_url": normalized,
            "model_name": model_trim,
            "available_models": empty,
            "elapsed_ms": elapsed_ms,
            "model_found": False,
            "available_models_count": 0,
        }
    except httpx.ConnectError as e:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        st = "connection_refused" if _is_likely_connection_refused(e) else "unknown_error"
        detail = (
            "无法连接 Ollama 服务，请确认 Ollama 已启动，地址和端口正确，并允许局域网访问。"
            if st == "connection_refused"
            else "连接 Ollama 失败，请检查网络与地址是否正确。"
        )
        logger.info(
            "ollama_connection_test status=%s base_url=%s model_name=%s elapsed_ms=%s available_models_count=0",
            st,
            normalized,
            model_trim,
            elapsed_ms,
        )
        return {
            "ok": False,
            "status": st,
            "detail": detail,
            "base_url": normalized,
            "model_name": model_trim,
            "available_models": empty,
            "elapsed_ms": elapsed_ms,
            "model_found": False,
            "available_models_count": 0,
        }
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        logger.info(
            "ollama_connection_test status=unknown_error base_url=%s model_name=%s elapsed_ms=%s available_models_count=0 err=%s",
            normalized,
            model_trim,
            elapsed_ms,
            _httpx_exc_summary(e),
        )
        return {
            "ok": False,
            "status": "unknown_error",
            "detail": "连接测试出现未知错误，请稍后重试或检查后端日志。",
            "base_url": normalized,
            "model_name": model_trim,
            "available_models": empty,
            "elapsed_ms": elapsed_ms,
            "model_found": False,
            "available_models_count": 0,
        }


async def generate_conversation_title(
    db: AsyncSession,
    messages: list[dict[str, Any]],
) -> str:
    """
    根据对话前几条消息生成 5-10 字标题。
    messages: [{"role": "user"|"assistant", "content": "..."}, ...]
    返回生成的标题字符串，失败时返回「新对话」。
    """
    config = await get_active_config(db)
    if config is None or not messages:
        return "新对话"
    snippet = "\n".join(
        f"{'用户' if m.get('role') == 'user' else '助手'}：{(m.get('content') or '')[:200]}"
        for m in messages[:4]
    )
    if not snippet.strip():
        return "新对话"
    try:
        base = normalize_ollama_base_url(config.base_url)
    except ValueError:
        return "新对话"
    system = "用5到10个字总结以下对话的标题。只输出标题本身，不要引号、不要解释、不要标点。"
    url = base + "/api/chat"
    payload = {
        "model": config.model_name,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": snippet},
        ],
        "stream": False,
        "options": {"temperature": 0.3},
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            data = r.json()
        msg = data.get("message") or data
        if isinstance(msg, dict):
            content = (msg.get("content") or "").strip()
        else:
            content = str(msg).strip()
        if content:
            return content[:50]
    except Exception as e:
        logger.warning("generate_conversation_title failed: %s", e)
    return "新对话"


def _strip_role_messages(messages: list[dict[str, Any]], role: str) -> list[dict[str, Any]]:
    return [m for m in messages if m.get("role") != role]


def _model_name_suggests_qwen_thinking(model_name: str) -> bool:
    m = (model_name or "").lower()
    return "qwen" in m


def try_local_smalltalk_shortcut(user_text: str) -> Optional[dict[str, Any]]:
    """
    高置信本地闲聊：不调用 Ollama，毫秒级返回。
    """
    if not getattr(settings, "AI_LOCAL_SMALLTALK_SHORTCUT_ENABLED", True):
        return None
    raw = (user_text or "").strip()
    if not raw or len(raw) > 48:
        return None
    # 稍复杂或带业务关键词的不抢答
    if any(
        k in raw
        for k in (
            "新建",
            "创建",
            "删除",
            "修改",
            "项目",
            "客户",
            "日程",
            "会议安排",
            "提醒",
            "数据库",
            "导出",
        )
    ):
        return None

    intro = (
        "你好，我是 Fly Arrangement 的本地 AI 助手，可以帮你创建项目、记录客户沟通、安排日程和设置本地提醒。"
    )
    caps = (
        "我可以帮你管理本地项目、客户、日程和提醒。例如：新建项目、记录客户沟通、安排明天会议、设置提醒。"
    )
    usage = "在左侧或各模块中操作即可；需要时用自然语言告诉我你想创建或修改的内容。"

    replies: dict[str, str] = {
        "你好": intro,
        "您好": intro,
        "hi": intro,
        "hello": intro,
        "哈喽": intro,
        "在吗": "我在，请直接说你想处理的项目、客户、日程或提醒。",
        "在么": "我在，请直接说你想处理的项目、客户、日程或提醒。",
        "谢谢": "不客气，有需要随时说。",
        "多谢": "不客气，有需要随时说。",
        "感谢": "不客气，有需要随时说。",
        "好的": "好的，有需要再告诉我。",
        "ok": "好的，有需要再告诉我。",
        "okay": "好的，有需要再告诉我。",
        "你是谁": "我是本机运行的 Fly Arrangement 助手，帮你管理项目、客户、日程与提醒，数据默认保存在本机。",
        "你能做什么": caps,
        "你能干什么": caps,
        "你会什么": caps,
        "你有什么功能": caps,
        "怎么使用": usage,
        "如何使用": usage,
        "怎么用": usage,
        "帮我介绍一下功能": caps,
        "介绍一下功能": caps,
        "功能介绍": caps,
    }
    norm = raw.strip().strip("。.!！?？,，~～")
    lk = norm.lower() if norm.isascii() else norm
    content = replies.get(norm) or replies.get(lk)
    if not content:
        return None
    return {
        "message": {"role": "assistant", "content": content},
        "execution_results": [],
        "use_tools": False,
        "shortcut": "local_smalltalk",
        "detected_intent": None,
    }


async def plain_ollama_chat_for_web(
    db: AsyncSession,
    messages: list[dict[str, Any]],
    *,
    diag: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], int]:
    """
    桌面 web：无业务动作意图时的直连对话，不附带 tools 与项目快照，降低首包延迟与 token 体积。
    """
    t0 = time.perf_counter()
    config = await get_active_config(db)
    if config is None:
        raise ValueError("未配置生效的 AI 模型，请先在「AI 配置」中保存并激活")
    base_url = normalize_ollama_base_url(config.base_url)
    system = "你是 Fly Arrangement 中文助手。回答简短务实；勿编造已写入数据库的操作；勿提飞书。"
    apply_no_think = bool(
        getattr(settings, "AI_OLLAMA_DISABLE_THINKING", True)
        and _model_name_suggests_qwen_thinking(config.model_name or "")
    )
    if apply_no_think:
        system += "请直接给出最终回答，不要输出思考过程。"
    conv = _strip_role_messages(list(messages), "system")
    max_plain_turns = 4
    if len(conv) > max_plain_turns:
        conv = conv[-max_plain_turns:]
    # 仅对最后一条 user 可附加 /no_think（Qwen 系）
    conv_adj: list[dict[str, Any]] = []
    for i, m in enumerate(conv):
        if i == len(conv) - 1 and m.get("role") == "user" and apply_no_think:
            u = str(m.get("content") or "")
            conv_adj.append({"role": "user", "content": "/no_think\n" + u})
        else:
            conv_adj.append(dict(m))
    plain_messages = [{"role": "system", "content": system}] + conv_adj
    if diag is not None:
        diag["plain_history_count"] = len(conv_adj)
        diag["plain_prompt_chars"] = sum(
            len(str(m.get("content") or "")) + len(str(m.get("role") or "")) for m in plain_messages
        )
        diag["local_smalltalk_hit"] = False
        diag["disable_thinking_applied"] = bool(apply_no_think)
    url = base_url + "/api/chat"
    last_user_len = 0
    for m in reversed(conv_adj):
        if m.get("role") == "user":
            last_user_len = len(str(m.get("content") or ""))
            break
    if last_user_len <= 20:
        num_predict = max(16, min(512, int(getattr(settings, "AI_DESKTOP_SHORT_REPLY_NUM_PREDICT", 64))))
    else:
        num_predict = max(32, min(512, int(settings.AI_DESKTOP_SIMPLE_NUM_PREDICT)))
    temp = 0.2
    if diag is not None:
        diag["plain_num_predict"] = num_predict
    chat_timeout_seconds = max(
        1,
        int(getattr(settings, "AI_PLAIN_CHAT_TIMEOUT_SECONDS", settings.AI_OLLAMA_READ_TIMEOUT_SECONDS)),
    )
    conn_timeout = max(1.0, float(settings.AI_OLLAMA_CONNECT_TIMEOUT_SECONDS))
    timeout = httpx.Timeout(chat_timeout_seconds, connect=conn_timeout)
    payload = {
        "model": config.model_name,
        "messages": plain_messages,
        "stream": False,
        "options": {
            "temperature": temp,
            "top_p": 0.9,
            "num_predict": num_predict,
        },
    }
    logger.info(
        "event=ollama_chat_started phase=plain_chat base_url=%s model=%s connect_timeout_s=%s read_timeout_s=%s num_predict=%s plain_history_count=%s plain_prompt_chars=%s",
        base_url,
        config.model_name,
        conn_timeout,
        chat_timeout_seconds,
        num_predict,
        len(conv),
        (diag or {}).get("plain_prompt_chars", 0),
    )
    chat_retries = max(0, int(settings.OLLAMA_CHAT_RETRIES))
    chat_retry_delay_seconds = max(0, int(settings.OLLAMA_CHAT_RETRY_DELAY_SECONDS))
    total_attempts = chat_retries + 1

    def _fail_timeout(exc: httpx.TimeoutException) -> OllamaUserFacingError:
        set_ai_chat_timeout_stage("ollama_first_call")
        elapsed_ms: int | None = None
        if diag and isinstance(diag.get("_perf_start"), (int, float)):
            elapsed_ms = int((time.perf_counter() - float(diag["_perf_start"])) * 1000)
        logger.error(
            "ollama_plain_chat_failed status=timeout base_url=%s model_name=%s summary=%s elapsed_ms=%s",
            base_url,
            config.model_name,
            _httpx_exc_summary(exc),
            elapsed_ms,
        )
        d = {"request_id": (diag or {}).get("request_id")} if diag else {}
        if elapsed_ms is not None:
            d["elapsed_ms"] = elapsed_ms
        return OllamaUserFacingError(
            status="timeout",
            message="Ollama 服务响应超时，可能正在加载模型或机器资源不足。",
            base_url=base_url,
            model_name=config.model_name,
            timeout_stage="ollama_first_call",
            error_status="timeout",
            diagnostic=d,
        )

    for attempt in range(total_attempts):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(url, json=payload)
                r.raise_for_status()
                data = r.json()
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                msg = data.get("message") or data
                if not isinstance(msg, dict):
                    msg = {"role": "assistant", "content": str(msg)}
                raw_content = str(msg.get("content") or "").strip()
                think_raw = msg.get("thinking")
                if think_raw is None and isinstance(data.get("message"), dict):
                    think_raw = data["message"].get("thinking")
                if think_raw is None:
                    think_raw = data.get("thinking")
                thinking_s = str(think_raw).strip() if think_raw is not None else ""
                if not raw_content:
                    if thinking_s:
                        msg["content"] = "模型本次没有生成可展示的正式回答，请换一种问法或重试。"
                        if diag is not None:
                            diag["empty_content"] = True
                            diag["has_thinking"] = True
                    else:
                        msg["content"] = "模型本次没有返回有效内容，请稍后重试。"
                        if diag is not None:
                            diag["empty_content"] = True
                            diag["has_thinking"] = False
                    if "thinking" in msg:
                        del msg["thinking"]
                if diag is not None:
                    diag.setdefault("phase_elapsed_ms", {})["ollama_first_call_ms"] = int(
                        (time.perf_counter() - t0) * 1000
                    )
                    diag["ollama_elapsed_ms_plain"] = elapsed_ms
                    diag["total_elapsed_ms_plain"] = int((time.perf_counter() - t0) * 1000)
                logger.info(
                    "event=ollama_chat_finished phase=plain_chat base_url=%s model=%s elapsed_ms=%s read_timeout_s=%s num_predict=%s plain_history_count=%s plain_prompt_chars=%s",
                    base_url,
                    config.model_name,
                    elapsed_ms,
                    chat_timeout_seconds,
                    num_predict,
                    len(conv),
                    (diag or {}).get("plain_prompt_chars", 0),
                )
                return msg, elapsed_ms
        except httpx.ConnectError as e:
            if isinstance(e, httpx.ConnectTimeout):
                if attempt < total_attempts - 1:
                    await asyncio.sleep(chat_retry_delay_seconds)
                    continue
                raise _fail_timeout(e) from e
            st = "connection_refused" if _is_likely_connection_refused(e) else "unknown_error"
            msg_e = (
                "无法连接 Ollama 服务，请确认 Ollama 已启动，地址和端口正确，并允许局域网访问。"
                if st == "connection_refused"
                else "连接 Ollama 失败，请检查网络与地址是否正确。"
            )
            raise OllamaUserFacingError(
                status=st,
                message=msg_e,
                base_url=base_url,
                model_name=config.model_name,
                timeout_stage="ollama_first_call",
                diagnostic={"request_id": (diag or {}).get("request_id")} if diag else {},
            ) from e
        except httpx.ReadTimeout as e:
            if attempt < total_attempts - 1:
                await asyncio.sleep(chat_retry_delay_seconds)
                continue
            raise _fail_timeout(e) from e
        except httpx.TimeoutException as e:
            if attempt < total_attempts - 1:
                await asyncio.sleep(chat_retry_delay_seconds)
                continue
            raise _fail_timeout(e) from e
        except httpx.HTTPStatusError as e:
            if attempt < total_attempts - 1 and (
                "not ready" in (e.response.text or "").lower()
                or "loading" in (e.response.text or "").lower()
                or e.response.status_code == 503
            ):
                await asyncio.sleep(chat_retry_delay_seconds)
                continue
            raise OllamaUserFacingError(
                status="http_error",
                message=f"Ollama 返回 HTTP {e.response.status_code}，无法完成对话。",
                base_url=base_url,
                model_name=config.model_name,
                timeout_stage="ollama_first_call",
                diagnostic={"request_id": (diag or {}).get("request_id")} if diag else {},
            ) from e
    raise RuntimeError("ollama plain chat failed")


async def chat_with_tools(
    db: AsyncSession,
    messages: list[dict[str, Any]],
    *,
    stream: bool = False,
    operator_source: str = "ai",
    agent_business_intent: str | None = None,
    ollama_diag_phase: str = "ollama_first_call",
    diag: dict[str, Any] | None = None,
) -> dict[str, Any] | Any:
    """
    使用当前生效的 AIConfig 调用 Ollama /api/chat，并注入 Project/Customer 相关的 tools。
    每次调用前从数据库读取 is_active=True 的配置，不再依赖环境变量。
    messages: [{"role": "user"|"assistant"|"system", "content": "..."}]
    返回 Ollama 的响应体（含 message 或 tool_calls）。
    """
    config = await get_active_config(db)
    if config is None:
        raise ValueError("未配置生效的 AI 模型，请先在「AI 配置」中保存并激活")
    try:
        base_url = normalize_ollama_base_url(config.base_url)
    except ValueError as e:
        raise ValueError(f"当前生效的 AI 配置中 Ollama 地址无效：{e}") from e

    # 动态数据快照：用户发指令前先查库，注入当前项目清单
    projects_snapshot = await _get_projects_snapshot(db)
    snapshot_json = json.dumps(projects_snapshot, ensure_ascii=False)
    snapshot_block = f"""【当前环境快照】当前系统中存在的项目清单：{snapshot_json}
（清单为空表示尚无项目；请根据用户指令调用 list_projects 或直接执行新建/修改。）"""

    now_utc = datetime.now(timezone.utc)
    last_user_message = next(
        (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
        "",
    )
    detected_intent = (
        agent_business_intent
        if agent_business_intent is not None
        else detect_action_intent(last_user_message)
    )
    t_bp0 = time.perf_counter()
    system_prompt, loaded_skills = _build_system_prompt(
        snapshot_block,
        now_utc=now_utc,
        intent=detected_intent,
        operator_source=operator_source,
    )
    if diag is not None:
        diag["loaded_skills"] = list(loaded_skills)
        diag["prompt_chars"] = len(system_prompt)
        diag.setdefault("phase_elapsed_ms", {})["build_prompt_ms"] = int(
            (time.perf_counter() - t_bp0) * 1000
        )
    if not any(m.get("role") == "system" for m in messages):
        messages = [{"role": "system", "content": system_prompt}] + list(messages)

    url = base_url + "/api/chat"
    tools = build_tool_schemas_for_intent(
        detected_intent,
        operator_source=operator_source,
    )
    if diag is not None:
        diag["tool_schema_count"] = len(tools)
    logger.info(
        "event=ai_tools_prepared intent=%s loaded_skills=%s prompt_chars=%d tools_count=%d base_url=%s model=%s operator_source=%s",
        detected_intent,
        ",".join(loaded_skills),
        len(system_prompt),
        len(tools),
        base_url,
        config.model_name,
        operator_source,
    )
    tp = (
        float(settings.AI_TOOL_CHAT_TEMPERATURE)
        if operator_source == "web"
        else float(settings.AI_CHAT_TEMPERATURE)
    )
    np_tool = max(64, int(settings.AI_TOOL_CHAT_NUM_PREDICT))
    payload = {
        "model": config.model_name,
        "messages": messages,
        "stream": stream,
        "tools": tools,
        "options": {
            "temperature": tp,
            "top_p": 0.9,
            "repeat_penalty": 1.1,
            "num_predict": np_tool,
        },
    }

    stage = (
        "ollama_summary"
        if str(ollama_diag_phase or "") == "ollama_summary"
        else "ollama_first_call"
    )
    tool_plan_sec = int(
        getattr(settings, "AI_TOOL_PLANNING_TIMEOUT_SECONDS", settings.AI_OLLAMA_TOOL_PLANNING_TIMEOUT_SECONDS)
    )
    read_sec = (
        max(1, int(settings.AI_OLLAMA_SUMMARY_TIMEOUT_SECONDS))
        if stage == "ollama_summary"
        else max(1, tool_plan_sec)
    )
    conn_sec = max(1.0, float(settings.AI_OLLAMA_CONNECT_TIMEOUT_SECONDS))
    chat_retries = max(0, int(settings.OLLAMA_CHAT_RETRIES))
    chat_retry_delay_seconds = max(0, int(settings.OLLAMA_CHAT_RETRY_DELAY_SECONDS))
    total_attempts = chat_retries + 1
    timeout = httpx.Timeout(read_sec, connect=conn_sec)
    logger.info(
        "event=ollama_chat_started phase=%s base_url=%s model=%s read_timeout_s=%s connect_timeout_s=%s retries=%s tools=%s",
        stage,
        base_url,
        config.model_name,
        read_sec,
        conn_sec,
        chat_retries,
        len(tools),
    )

    def _fail_timeout(exc: httpx.TimeoutException) -> OllamaUserFacingError:
        set_ai_chat_timeout_stage(stage)
        elapsed_ms: int | None = None
        if diag and isinstance(diag.get("_perf_start"), (int, float)):
            elapsed_ms = int((time.perf_counter() - float(diag["_perf_start"])) * 1000)
        logger.error(
            "ollama_request_failed status=timeout phase=%s base_url=%s model_name=%s summary=%s elapsed_ms=%s",
            stage,
            base_url,
            config.model_name,
            _httpx_exc_summary(exc),
            elapsed_ms,
        )
        if stage == "ollama_summary":
            msg = "AI 在总结执行结果时超时（模型生成过慢或机器资源不足）。"
        else:
            msg = "AI 在理解并规划工具调用时超时（已超过规划时限）。可稍后重试，或拆成更短的分步指令。"
            di = (diag or {}).get("detected_intent")
            if di == "calendar":
                msg += (
                    " 若句子已是明确日程（含「明天」「下午三点」等），通常可由本地 simple_calendar_event 快捷创建；"
                    "本次未命中快捷时请检查时间表述是否完整。"
                )
        d = {"request_id": (diag or {}).get("request_id")} if diag else {}
        if diag and diag.get("detected_intent") is not None:
            d["detected_intent"] = diag.get("detected_intent")
        if elapsed_ms is not None:
            d["elapsed_ms"] = elapsed_ms
        return OllamaUserFacingError(
            status="timeout",
            message=msg,
            base_url=base_url,
            model_name=config.model_name,
            timeout_stage=stage,
            error_status="timeout",
            diagnostic=d,
        )

    for attempt in range(total_attempts):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                t_ollama = time.perf_counter()
                r = await client.post(url, json=payload)
                r.raise_for_status()
                elapsed_ollama = int((time.perf_counter() - t_ollama) * 1000)
                if diag is not None:
                    key = "ollama_summary_ms" if stage == "ollama_summary" else "ollama_first_call_ms"
                    pe = diag.setdefault("phase_elapsed_ms", {})
                    pe[key] = pe.get(key, 0) + elapsed_ollama
                logger.info(
                    "event=ollama_chat_finished phase=%s elapsed_ms=%s model=%s",
                    stage,
                    elapsed_ollama,
                    config.model_name,
                )
                return r.json()
        except httpx.ConnectError as e:
            if isinstance(e, httpx.ConnectTimeout):
                if attempt < total_attempts - 1:
                    logger.warning(
                        "ollama request attempt %s ConnectTimeout (retry): %s",
                        attempt + 1,
                        e,
                    )
                    await asyncio.sleep(chat_retry_delay_seconds)
                    continue
                raise _fail_timeout(e) from e
            st = "connection_refused" if _is_likely_connection_refused(e) else "unknown_error"
            msg = (
                "无法连接 Ollama 服务，请确认 Ollama 已启动，地址和端口正确，并允许局域网访问。"
                if st == "connection_refused"
                else "连接 Ollama 失败，请检查网络与地址是否正确。"
            )
            logger.error(
                "ollama_request_failed status=%s base_url=%s model_name=%s summary=%s",
                st,
                base_url,
                config.model_name,
                _httpx_exc_summary(e),
            )
            raise OllamaUserFacingError(
                status=st,
                message=msg,
                base_url=base_url,
                model_name=config.model_name,
                timeout_stage=stage,
                diagnostic={"request_id": (diag or {}).get("request_id")} if diag else {},
            ) from e
        except httpx.ReadTimeout as e:
            if attempt < total_attempts - 1:
                logger.warning("ollama request attempt %s ReadTimeout (retry): %s", attempt + 1, e)
                await asyncio.sleep(chat_retry_delay_seconds)
                continue
            raise _fail_timeout(e) from e
        except httpx.TimeoutException as e:
            if attempt < total_attempts - 1:
                logger.warning("ollama request attempt %s timeout (retry): %s", attempt + 1, e)
                await asyncio.sleep(chat_retry_delay_seconds)
                continue
            raise _fail_timeout(e) from e
        except httpx.HTTPStatusError as e:
            msg_l = (e.response.text or str(e)).lower()
            if attempt < total_attempts - 1 and (
                "not ready" in msg_l or "loading" in msg_l or "unavailable" in msg_l or e.response.status_code == 503
            ):
                logger.warning("ollama request attempt %s failed (model loading): %s", attempt + 1, e)
                await asyncio.sleep(chat_retry_delay_seconds)
                continue
            http_code = e.response.status_code
            logger.error(
                "ollama_request_failed status=http_error base_url=%s model_name=%s http_status=%s summary=%s",
                base_url,
                config.model_name,
                http_code,
                _httpx_exc_summary(e),
            )
            raise OllamaUserFacingError(
                status="http_error",
                message=(
                    f"Ollama 返回 HTTP {http_code}，无法完成对话。"
                    " 请确认 Ollama 已启动，地址和端口正确，并允许局域网访问。"
                ),
                base_url=base_url,
                model_name=config.model_name,
                timeout_stage=stage,
                diagnostic={"request_id": (diag or {}).get("request_id")} if diag else {},
            ) from e
    raise RuntimeError("ollama request failed")


async def _append_auto_customer_interaction_if_needed(
    db: AsyncSession,
    *,
    last_user_message: str,
    detected_action_intent: str | None,
    operator_source: str,
    operator_external_id: str | None,
    operator_user_id: int | None,
    step_results: list[dict[str, Any]],
    execution_results: list[dict[str, Any]],
) -> None:
    """customer 意图且用户明确要求沟通归档时：若模型只 create_customer，自动补 create_customer_interaction。"""
    from app.services.compound_business_service import (
        parse_talk_summary_for_interaction_record,
        user_text_suggests_customer_communication_record,
    )

    if detected_action_intent != "customer" or operator_source != "web" or operator_user_id is None:
        return
    if not user_text_suggests_customer_communication_record(last_user_message):
        return
    if any(str(r.get("tool_name") or "") == "create_customer_interaction" for r in execution_results):
        return
    if any(str(r.get("tool_name") or "") == "create_customer_interaction" for r in step_results):
        return
    if not step_results or not all(r.get("success") for r in step_results):
        return
    talk = parse_talk_summary_for_interaction_record(last_user_message)
    if not talk:
        return
    customer_id: int | None = None
    for r in reversed(step_results):
        if not r.get("success"):
            continue
        if str(r.get("tool_name") or "") == "create_customer":
            res = r.get("result")
            if isinstance(res, dict) and res.get("id") is not None:
                customer_id = int(res["id"])
                break
    if customer_id is None:
        for r in reversed(step_results):
            if not r.get("success"):
                continue
            if str(r.get("tool_name") or "") != "resolve_customer":
                continue
            cid_raw = r.get("customer_id")
            if cid_raw is None and isinstance(r.get("result"), dict):
                cid_raw = r["result"].get("customer_id")
            if cid_raw is not None:
                customer_id = int(cid_raw)
                break
    if customer_id is None:
        return
    auto = await execute_tool_call(
        db,
        "create_customer_interaction",
        {
            "customer_id": customer_id,
            "talk_summary": talk[:2000],
            "raw_input": last_user_message,
        },
        operator_source=operator_source,
        operator_external_id=operator_external_id,
        operator_user_id=operator_user_id,
    )
    auto = {
        **auto,
        "tool_name": "create_customer_interaction",
        "tool_call_id": "auto_customer_interaction_backfill",
    }
    step_results.append(auto)
    execution_results.append(auto)
    logger.info(
        "event=ai_customer_interaction_backfill customer_id=%s talk_len=%s",
        customer_id,
        len(talk),
    )


async def run_agent_loop(
    db: AsyncSession,
    messages: list[dict[str, Any]],
    *,
    max_steps: int = 6,
    operator_source: str = "ai",
    operator_external_id: str | None = None,
    operator_user_id: int | None = None,
    diag: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Agent Loop（ReAct 循环）：多轮调用 Ollama，执行 tool_calls 后将结果加入 messages，
    直到 AI 不再调用工具或达到 max_steps。返回最终 message 与 execution_results。
    operator_user_id：非 web 通道时传入绑定的系统用户 id，工具按此用户做数据隔离。
    """
    # 使用副本避免修改调用方传入的 messages
    messages = list(messages)
    execution_results: list[dict[str, Any]] = []
    failed_tool_call_ids: set[str] = set()
    executed_create_tool_results: dict[str, dict[str, Any]] = {}
    last_user_message = next(
        (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
        "",
    )
    from app.services.compound_business_service import user_text_suggests_customer_communication_record

    detected_action_intent = detect_action_intent(last_user_message)
    intent_skill_excerpt = load_skills(_intent_domain_skill_names(detected_action_intent))
    second_prompt_triggered = False
    first_model_has_tool_calls: bool | None = None
    second_model_has_tool_calls: bool | None = None

    for step in range(max_steps):
        ollama_phase = "ollama_summary" if step > 0 else "ollama_first_call"
        set_ai_chat_timeout_stage(ollama_phase)
        try:
            response = await chat_with_tools(
                db,
                messages,
                stream=False,
                operator_source=operator_source,
                agent_business_intent=detected_action_intent,
                ollama_diag_phase=ollama_phase,
                diag=diag,
            )
        except OllamaUserFacingError as oe:
            if step > 0 and execution_results:
                logger.warning(
                    "event=ai_chat_failed request_id=%s timeout_stage=%s partial_recovery=1",
                    (diag or {}).get("request_id"),
                    getattr(oe, "timeout_stage", None),
                )
                final_content = (
                    "工具已执行，但 AI 在总结执行结果时超时。以下是已完成的步骤：\n"
                    + _template_action_summary_text(execution_results)
                )
                return {
                    "message": {"role": "assistant", "content": final_content},
                    "execution_results": execution_results,
                    "detected_intent": detected_action_intent,
                    "use_tools": True,
                    "timeout_stage": getattr(oe, "timeout_stage", "ollama_summary"),
                    "error_status": "timeout",
                    "partial_results": execution_results,
                }
            rid = (diag or {}).get("request_id")
            if rid:
                oe.diagnostic.setdefault("request_id", rid)
            logger.warning(
                "event=ai_chat_failed request_id=%s timeout_stage=%s",
                rid,
                getattr(oe, "timeout_stage", None),
            )
            raise
        message = response.get("message") or response
        if not isinstance(message, dict):
            message = {"role": "assistant", "content": str(message)}

        tool_calls = message.get("tool_calls") or []
        if step == 0:
            first_model_has_tool_calls = bool(tool_calls)
        elif second_prompt_triggered and second_model_has_tool_calls is None:
            second_model_has_tool_calls = bool(tool_calls)

        if not tool_calls:
            if detected_action_intent and not second_prompt_triggered:
                forced_tool_prompt = (
                    f"当前用户请求属于 {detected_action_intent} 动作类请求。\n"
                    "必须选择一个可用工具完成真实操作。\n"
                    "如果信息不足，请调用合适工具或明确说明缺少字段。\n"
                    "不得只用自然语言声称已经完成。\n"
                    + (
                        f"\n领域 Skill 摘录：\n{intent_skill_excerpt[:900]}\n"
                        if intent_skill_excerpt
                        else ""
                    )
                )
                messages.append({
                    "role": "system",
                    "content": forced_tool_prompt,
                })
                second_prompt_triggered = True
                continue

            diagnosis_kwargs = (
                (last_user_message or "")[:100],
                detected_action_intent,
                first_model_has_tool_calls,
                second_prompt_triggered,
                second_model_has_tool_calls,
                0,
                len(execution_results),
            )
            if detected_action_intent:
                logger.warning(
                    "ai_tool_diagnosis last_user_message=%r detected_action_intent=%s first_model_has_tool_calls=%s second_prompt_triggered=%s second_model_has_tool_calls=%s final_tool_call_count=%d execution_results_count=%d",
                    *diagnosis_kwargs,
                )
            else:
                logger.info(
                    "ai_tool_diagnosis last_user_message=%r detected_action_intent=%s first_model_has_tool_calls=%s second_prompt_triggered=%s second_model_has_tool_calls=%s final_tool_call_count=%d execution_results_count=%d",
                    *diagnosis_kwargs,
                )
            return {
                "message": message,
                "execution_results": execution_results,
                "detected_intent": detected_action_intent,
                "use_tools": detected_action_intent is not None,
            }

        step_results: list[dict[str, Any]] = []
        t_tools = time.perf_counter()
        set_ai_chat_timeout_stage("tool_execution")
        logger.info(
            "event=ai_tool_execution_started step=%s tool_calls_count=%s",
            step + 1,
            len(tool_calls),
        )
        for tc in tool_calls:
            tc_id = tc.get("id")
            fn = tc.get("function") or tc.get("function_call")
            if not fn:
                continue
            tool_name = fn.get("name") if isinstance(fn, dict) else getattr(fn, "name", None)
            if tc_id and tc_id in failed_tool_call_ids:
                step_results.append({
                    "success": False,
                    "error": "tool execution failed",
                    "execution_summary": "tool execution failed",
                    "tool_call_id": tc_id,
                    "tool_name": tool_name,
                })
                execution_results.append(step_results[-1])
                continue
            raw_args = fn.get("arguments") if isinstance(fn, dict) else getattr(fn, "arguments", "{}")
            if isinstance(raw_args, str):
                try:
                    arguments = json.loads(raw_args)
                except json.JSONDecodeError:
                    arguments = {}
            else:
                arguments = raw_args or {}

            dedupe_key = build_tool_dedupe_key(str(tool_name or ""), arguments if isinstance(arguments, dict) else {})
            if dedupe_key and dedupe_key in executed_create_tool_results:
                logger.info("ai_tool_deduped tool_name=%s dedupe_key=%s", tool_name, dedupe_key)
                previous_result = executed_create_tool_results[dedupe_key]
                previous_success = bool(previous_result.get("success"))
                if previous_success:
                    deduped_result = {
                        "success": True,
                        "skipped": True,
                        "tool_name": tool_name,
                        "tool_call_id": tc_id,
                        "execution_summary": "已跳过本轮重复的创建类工具调用，避免重复创建。",
                        "result": {"deduped": True, "previous_success": True},
                    }
                else:
                    previous_error = (
                        previous_result.get("error")
                        or previous_result.get("execution_summary")
                        or "前一次相同工具调用已失败，本次跳过重复执行。"
                    )
                    deduped_result = {
                        "success": False,
                        "skipped": True,
                        "tool_name": tool_name,
                        "tool_call_id": tc_id,
                        "error": previous_error,
                        "execution_summary": "前一次相同创建类工具调用已失败，本次跳过重复执行，失败原因沿用前一次结果。",
                        "result": {"deduped": True, "previous_success": False},
                    }
                step_results.append(deduped_result)
                execution_results.append(deduped_result)
                continue

            args_summary = json.dumps(arguments, ensure_ascii=False, default=str)
            if len(args_summary) > 500:
                args_summary = args_summary[:500] + "...(truncated)"
            logger.info("AI tool call: %s params=%s", tool_name, args_summary)
            if detected_action_intent == "calendar" and str(tool_name or "") in _CALENDAR_INTENT_FORBIDDEN_TOOLS:
                logger.warning(
                    "calendar_intent_blocked_non_calendar_tool tool_name=%s",
                    tool_name,
                )
                result = {
                    "success": False,
                    "error": "calendar_intent_blocked_non_calendar_tool",
                    "execution_summary": (
                        "当前识别为会议/日程意图，已拒绝执行项目或客户类工具；"
                        "请改用 auto_schedule_event 或 create_calendar_event 等日历工具。"
                    ),
                }
            else:
                result = await execute_tool_call(
                    db=db,
                    tool_name=tool_name,
                    arguments=arguments,
                    operator_source=operator_source,
                    operator_external_id=operator_external_id,
                    operator_user_id=operator_user_id,
                )
            if not result.get("success") and tc_id:
                failed_tool_call_ids.add(tc_id)
            result_summary = str(
                result.get("execution_summary") or result.get("error") or result.get("message") or ""
            )
            if len(result_summary) > 300:
                result_summary = result_summary[:300] + "...(truncated)"
            logger.info(
                "AI tool result: %s success=%s summary=%s",
                tool_name,
                result.get("success"),
                result_summary,
            )

            result_with_meta = {**result, "tool_call_id": tc_id, "tool_name": tool_name}
            if dedupe_key:
                executed_create_tool_results[dedupe_key] = result_with_meta
            step_results.append(result_with_meta)
            execution_results.append(result_with_meta)

        await _append_auto_customer_interaction_if_needed(
            db,
            last_user_message=last_user_message,
            detected_action_intent=detected_action_intent,
            operator_source=operator_source,
            operator_external_id=operator_external_id,
            operator_user_id=operator_user_id,
            step_results=step_results,
            execution_results=execution_results,
        )

        if diag is not None:
            pe = diag.setdefault("phase_elapsed_ms", {})
            pe["tool_execution_ms"] = pe.get("tool_execution_ms", 0) + int(
                (time.perf_counter() - t_tools) * 1000
            )
        logger.info(
            "event=ai_tool_execution_finished step=%s tools=%s",
            step + 1,
            ",".join(str(r.get("tool_name") or "") for r in step_results),
        )

        customer_communication_incomplete = (
            detected_action_intent == "customer"
            and operator_source == "web"
            and user_text_suggests_customer_communication_record(last_user_message)
            and not any(str(r.get("tool_name") or "") == "create_customer_interaction" for r in step_results)
        )

        if (
            bool(getattr(settings, "AI_ACTION_SUMMARY_USE_TEMPLATE", True))
            and operator_source == "web"
            and step_results
            and all(r.get("success") for r in step_results)
            and all(str(r.get("tool_name") or "") in _TEMPLATE_ACTION_SUMMARY_TOOLS for r in step_results)
            and not customer_communication_incomplete
        ):
            final_content = _template_action_summary_text(step_results)
            logger.info(
                "event=ai_chat_finished template_summary=1 request_id=%s",
                (diag or {}).get("request_id"),
            )
            return {
                "message": {"role": "assistant", "content": final_content},
                "execution_results": execution_results,
                "detected_intent": detected_action_intent,
                "use_tools": detected_action_intent is not None,
                "template_summary": True,
            }

        tool_result_text = _format_execution_results_for_prompt(step_results)
        messages.append(message)
        messages.append({
            "role": "user",
            "content": (
                f"工具执行结果如下。\n{tool_result_text}\n\n"
                "请只基于这些结果继续，不得声称未成功的操作已完成。"
                "未完成则继续 tool_calls；已全部完成则仅用自然语言总结且勿再调用工具。"
            ),
        })
        tool_names = [str(r.get("tool_name") or "") for r in step_results]
        success_count = sum(1 for r in step_results if r.get("success"))
        failed_count = len(step_results) - success_count
        logger.info(
            "ai_tool_step_summary step=%d tool_calls_count=%d step_results_count=%d total_execution_results_count=%d tool_names=%s success_count=%d failed_count=%d",
            step + 1,
            len(tool_calls),
            len(step_results),
            len(execution_results),
            ",".join(tool_names),
            success_count,
            failed_count,
        )

    diagnosis_kwargs = (
        (last_user_message or "")[:100],
        detected_action_intent,
        first_model_has_tool_calls,
        second_prompt_triggered,
        second_model_has_tool_calls,
        len(execution_results),
        len(execution_results),
    )
    if detected_action_intent and len(execution_results) == 0:
        logger.warning(
            "ai_tool_diagnosis last_user_message=%r detected_action_intent=%s first_model_has_tool_calls=%s second_prompt_triggered=%s second_model_has_tool_calls=%s final_tool_call_count=%d execution_results_count=%d",
            *diagnosis_kwargs,
        )
    else:
        logger.info(
            "ai_tool_diagnosis last_user_message=%r detected_action_intent=%s first_model_has_tool_calls=%s second_prompt_triggered=%s second_model_has_tool_calls=%s final_tool_call_count=%d execution_results_count=%d",
            *diagnosis_kwargs,
        )
    return {
        "message": {
            "role": "assistant",
            "content": _default_summary_from_results(execution_results) if execution_results else "任务执行步骤过多，已停止。",
        },
        "execution_results": execution_results,
        "detected_intent": detected_action_intent,
        "use_tools": detected_action_intent is not None,
    }


def dedupe_create_reminder_task_execution_results(
    execution_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    同一轮对话中模型可能对 create_reminder_task 先失败后重试，导致「部分成功」与重复展示。
    仅保留一条：优先保留最后一次成功；若均失败则保留最后一次失败。
    """
    indices = [i for i, r in enumerate(execution_results) if str(r.get("tool_name") or "") == "create_reminder_task"]
    if len(indices) <= 1:
        return execution_results
    successes = [i for i in indices if execution_results[i].get("success")]
    keep_i = successes[-1] if successes else indices[-1]
    return [
        r
        for i, r in enumerate(execution_results)
        if str(r.get("tool_name") or "") != "create_reminder_task" or i == keep_i
    ]


def _finalize_assistant_message_and_results(
    message: dict[str, Any],
    execution_results: list[dict[str, Any]],
    *,
    last_user: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """对助手回复与 execution_results 统一套用假成功/部分成功/提醒等守卫逻辑。"""
    execution_results = dedupe_create_reminder_task_execution_results(execution_results)
    if _user_intent_suggests_action(last_user) and not execution_results:
        assistant_content = (message.get("content") or "").strip() if isinstance(message, dict) else ""
        vague_replies = ("已处理", "好的", "收到", "完成", "搞定", "明白", "知道了")
        if not assistant_content or any(x in assistant_content for x in vague_replies):
            override_content = (
                "抱歉，我未能正确执行您的指令。请尝试更具体地说明操作，"
                "例如：「新建项目 XXX」「把项目 A 的负责人改为张三」。"
            )
            if isinstance(message, dict):
                message = {**message, "content": override_content}
            else:
                message = {"role": "assistant", "content": override_content}

    assistant_content = (message.get("content") or "").strip() if isinstance(message, dict) else str(message)
    original_assistant_content = assistant_content
    has_creation_success = _has_successful_creation_result(execution_results)
    blocked_fake_success = False

    # 强约束：无真实创建结果时，禁止任何“已创建/已安排成功”文案（不依赖用户意图判断）
    if (not has_creation_success) and _contains_success_claim(assistant_content):
        guarded = "我已经理解你的需求，但这次没有真正完成创建。请让我重新执行，或你可以补充更明确的时间与对象。"
        if isinstance(message, dict):
            message = {**message, "content": guarded}
        else:
            message = {"role": "assistant", "content": guarded}
        assistant_content = guarded
        blocked_fake_success = True

    # 创建型意图且没有任何执行结果：进一步收口，避免“口头完成”
    if _user_intent_suggests_creation(last_user) and (not has_creation_success) and (not execution_results):
        guarded = "我已经理解你的需求，但这次没有真正完成创建。请稍后重试，或让我分步为你处理。"
        if isinstance(message, dict):
            message = {**message, "content": guarded}
        else:
            message = {"role": "assistant", "content": guarded}
        assistant_content = guarded
        blocked_fake_success = True

    if blocked_fake_success:
        logger.warning(
            "fake success claim blocked: last_user=%r assistant_content=%r execution_results_count=%d",
            last_user,
            original_assistant_content,
            len(execution_results),
        )

    # 部分成功：明确哪些完成、哪些未完成
    success_items = [r for r in execution_results if r.get("success")]
    failed_items = [r for r in execution_results if not r.get("success")]
    if success_items and failed_items:
        success_text = "；".join(
            [str(r.get("execution_summary") or r.get("tool_name") or "成功项") for r in success_items[:3]]
        )
        failed_text = "；".join(
            [str(r.get("error") or r.get("execution_summary") or r.get("tool_name") or "失败项") for r in failed_items[:3]]
        )
        compound_partial = any(
            r.get("success") and str(r.get("tool_name") or "") == "execute_compound_schedule" for r in success_items
        )
        if compound_partial and isinstance(message, dict) and "已按复合行程处理" in str(message.get("content") or ""):
            content = (message.get("content") or "").strip()
            message = {
                **message,
                "content": f"{content}\n\n未完成项：{failed_text}。",
            }
            assistant_content = message.get("content") or ""
        else:
            partial_msg = f"部分任务已完成：{success_text}。未完成项：{failed_text}。"
            if isinstance(message, dict):
                message = {**message, "content": partial_msg}
            else:
                message = {"role": "assistant", "content": partial_msg}
            assistant_content = partial_msg

    # 提醒需求但无提醒类工具成功：明确未创建自动提醒
    if _user_intent_suggests_reminder(last_user):
        reminder_success = any(
            r.get("success")
            and str(r.get("tool_name") or "")
            in ("create_reminder_task", "update_reminder_task", "cancel_reminder_task")
            for r in execution_results
        )
        had_reminder_attempt = any(
            str(r.get("tool_name") or "") == "create_reminder_task" for r in execution_results
        )
        if not reminder_success and not had_reminder_attempt:
            reminder_note = "已记录您的提醒需求，但尚未真正创建或更新提醒任务（需成功调用 create_reminder_task 并落库）。"
            if isinstance(message, dict):
                if reminder_note not in str(message.get("content") or ""):
                    message = {**message, "content": f"{message.get('content') or ''}\n\n{reminder_note}".strip()}
            else:
                message = {"role": "assistant", "content": reminder_note}

    return message, execution_results


async def chat_and_execute_tools(
    db: AsyncSession,
    messages: list[dict[str, Any]],
    *,
    operator_source: str = "ai",
    operator_external_id: str | None = None,
    operator_user_id: int | None = None,
) -> dict[str, Any]:
    """
    统一调度：通过 run_agent_loop 执行 Agent Loop（ReAct 循环），
    多轮调用工具直到 AI 不再调用工具，返回最终 message 与 execution_results。
    operator_user_id：非 web 通道时传入绑定用户 id，工具层按此用户隔离数据（查询/修改归属）。
    Web 端须传入当前登录用户 id，否则创建类工具无法落库。
    """
    request_id = uuid.uuid4().hex
    t_total = time.perf_counter()
    diag: dict[str, Any] = {
        "request_id": request_id,
        "model_name": "",
        "base_url": "",
        "user_text_length": 0,
        "detected_intent": None,
        "use_tools": None,
        "tool_schema_count": 0,
        "loaded_skills": [],
        "prompt_chars": 0,
        "phase_elapsed_ms": {},
        "timeout_stage": None,
        "error_status": None,
    }
    diag["_perf_start"] = time.perf_counter()
    diag["operator_user_id"] = operator_user_id
    set_ai_chat_timeout_stage("config")

    def _attach_diag(out: dict[str, Any]) -> dict[str, Any]:
        _finalize_diag_total(diag, t_total)
        merged = dict(out)
        merged["request_id"] = request_id
        merged["model_name"] = diag.get("model_name") or merged.get("model_name", "")
        merged["base_url"] = diag.get("base_url") or merged.get("base_url", "")
        merged["user_text_length"] = diag.get("user_text_length", 0)
        merged["detected_intent"] = merged.get("detected_intent", diag.get("detected_intent"))
        merged["use_tools"] = merged.get("use_tools", diag.get("use_tools"))
        merged["tool_schema_count"] = diag.get("tool_schema_count", 0)
        merged["loaded_skills"] = list(diag.get("loaded_skills") or [])
        merged["prompt_chars"] = diag.get("prompt_chars", 0)
        merged["phase_elapsed_ms"] = dict(diag.get("phase_elapsed_ms") or {})
        if diag.get("timeout_stage"):
            merged["timeout_stage"] = diag["timeout_stage"]
        if diag.get("error_status"):
            merged["error_status"] = diag["error_status"]
        max_total = int(getattr(settings, "AI_OLLAMA_MAX_TOTAL_SECONDS", 120) or 120)
        merged["diagnostic"] = {
            "request_id": request_id,
            "model_name": merged.get("model_name", ""),
            "base_url": merged.get("base_url", ""),
            "user_text_length": int(merged.get("user_text_length") or 0),
            "detected_intent": merged.get("detected_intent"),
            "use_tools": merged.get("use_tools"),
            "tool_schema_count": int(merged.get("tool_schema_count") or 0),
            "loaded_skills": list(merged.get("loaded_skills") or []),
            "prompt_chars": int(merged.get("prompt_chars") or 0),
            "phase_elapsed_ms": dict(merged.get("phase_elapsed_ms") or {}),
            "timeout_stage": merged.get("timeout_stage"),
            "error_status": merged.get("error_status"),
            "shortcut": merged.get("shortcut"),
            "timeout_settings": {
                "connect": float(settings.AI_OLLAMA_CONNECT_TIMEOUT_SECONDS),
                "read": int(settings.AI_OLLAMA_READ_TIMEOUT_SECONDS),
                "plain_chat": int(
                    getattr(settings, "AI_PLAIN_CHAT_TIMEOUT_SECONDS", settings.AI_OLLAMA_READ_TIMEOUT_SECONDS)
                ),
                "tool_planning": int(
                    getattr(settings, "AI_TOOL_PLANNING_TIMEOUT_SECONDS", settings.AI_OLLAMA_TOOL_PLANNING_TIMEOUT_SECONDS)
                ),
                "tool_planning_legacy": int(settings.AI_OLLAMA_TOOL_PLANNING_TIMEOUT_SECONDS),
                "summary": int(settings.AI_OLLAMA_SUMMARY_TIMEOUT_SECONDS),
                "max_total": max_total,
            },
            "num_predict_desktop": int(settings.AI_DESKTOP_SIMPLE_NUM_PREDICT),
            "num_predict_tool": int(settings.AI_TOOL_CHAT_NUM_PREDICT),
        }
        if diag:
            if diag.get("empty_content"):
                merged["diagnostic"]["empty_content"] = True
            if "has_thinking" in diag:
                merged["diagnostic"]["has_thinking"] = bool(diag.get("has_thinking"))
            for _k in (
                "plain_prompt_chars",
                "plain_history_count",
                "plain_num_predict",
                "ollama_elapsed_ms_plain",
                "total_elapsed_ms_plain",
                "local_smalltalk_hit",
                "disable_thinking_applied",
            ):
                if _k in diag:
                    merged["diagnostic"][_k] = diag[_k]
        pe = dict(merged.get("phase_elapsed_ms") or {})
        total_ms = int(pe.get("total_ms") or 0)
        logger.info(
            "event=ai_chat_done request_id=%s user_id=%s model_name=%s base_url=%s detected_intent=%s use_tools=%s shortcut=%s tool_schema_count=%s loaded_skills=%s prompt_chars=%s num_predict_desktop=%s num_predict_tool=%s timeouts_s={connect:%s,read:%s,plan:%s,summary:%s,max_total:%s} phase_elapsed_ms=%s total_ms=%s timeout_stage=%s error_status=%s",
            request_id,
            operator_user_id,
            merged.get("model_name", ""),
            merged.get("base_url", ""),
            merged.get("detected_intent"),
            merged.get("use_tools"),
            merged.get("shortcut"),
            merged.get("tool_schema_count", 0),
            ",".join(merged.get("loaded_skills") or []),
            int(merged.get("prompt_chars") or 0),
            int(settings.AI_DESKTOP_SIMPLE_NUM_PREDICT),
            int(settings.AI_TOOL_CHAT_NUM_PREDICT),
            float(settings.AI_OLLAMA_CONNECT_TIMEOUT_SECONDS),
            int(settings.AI_OLLAMA_READ_TIMEOUT_SECONDS),
            int(settings.AI_OLLAMA_TOOL_PLANNING_TIMEOUT_SECONDS),
            int(settings.AI_OLLAMA_SUMMARY_TIMEOUT_SECONDS),
            max_total,
            pe,
            total_ms,
            merged.get("timeout_stage"),
            merged.get("error_status"),
        )
        return merged

    last_user = next(
        (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
        "",
    )
    diag["user_text_length"] = len(last_user or "")
    logger.info(
        "event=ai_chat_started request_id=%s user_id=%s user_len=%s operator_source=%s",
        request_id,
        operator_user_id,
        diag["user_text_length"],
        operator_source,
    )

    t_lc = time.perf_counter()
    cfg0 = await get_active_config(db)
    diag["phase_elapsed_ms"]["load_config_ms"] = int((time.perf_counter() - t_lc) * 1000)
    if cfg0:
        diag["model_name"] = cfg0.model_name or ""
        try:
            diag["base_url"] = normalize_ollama_base_url(cfg0.base_url or "")
        except ValueError:
            diag["base_url"] = (cfg0.base_url or "").strip()

    t_id = time.perf_counter()
    route_intent = detect_action_intent(last_user)
    diag["phase_elapsed_ms"]["detect_intent_ms"] = int((time.perf_counter() - t_id) * 1000)
    diag["detected_intent"] = route_intent
    logger.info("event=ai_intent_detected request_id=%s intent=%s", request_id, route_intent)
    set_ai_chat_timeout_stage("intent")

    # 「好的/确认」类短回复仅在确有 pending 动作时才允许进入确认链路。
    if _is_confirm_like_utterance(last_user):
        has_pending = await _has_pending_confirmable_action(db, operator_user_id)
        if not has_pending:
            logger.warning(
                "confirm-like utterance without pending action: user_text=%r operator_user_id=%s",
                last_user,
                operator_user_id,
            )
            diag["use_tools"] = False
            logger.info("event=ai_chat_finished request_id=%s reason=confirm_no_pending", request_id)
            return _attach_diag({
                "message": {
                    "role": "assistant",
                    "content": "当前没有待确认的安排、转移或提醒任务。若你希望我现在创建，请重新明确说一次需求。",
                },
                "execution_results": [],
                "detected_intent": route_intent,
                "use_tools": False,
            })

    from app.services.compound_schedule_service import try_compound_schedule_shortcut

    set_ai_chat_timeout_stage("shortcut")
    shortcut = await try_compound_schedule_shortcut(
        db, last_user, operator_user_id, operator_source=operator_source
    )
    if shortcut is not None:
        message, execution_results = _finalize_assistant_message_and_results(
            shortcut["message"],
            shortcut["execution_results"],
            last_user=last_user,
        )
        diag["use_tools"] = bool(execution_results)
        logger.info("event=ai_chat_finished request_id=%s shortcut=compound_schedule", request_id)
        return _attach_diag({
            "message": message,
            "execution_results": execution_results,
            "detected_intent": route_intent,
            "use_tools": bool(execution_results),
            "shortcut": "compound_schedule",
        })

    from app.services.compound_schedule_service import try_simple_calendar_event_shortcut

    if operator_user_id is not None:
        cal_hit = await try_simple_calendar_event_shortcut(
            last_user,
            db,
            operator_user_id,
            operator_source=operator_source,
        )
        if cal_hit is not None:
            message, execution_results = _finalize_assistant_message_and_results(
                cal_hit["message"],
                cal_hit.get("execution_results") or [],
                last_user=last_user,
            )
            diag["use_tools"] = bool(cal_hit.get("use_tools", True))
            diag["detected_intent"] = cal_hit.get("detected_intent", "calendar")
            if cal_hit.get("error_status"):
                diag["error_status"] = cal_hit["error_status"]
            logger.info(
                "event=ai_chat_finished request_id=%s shortcut=simple_calendar_event success=%s",
                request_id,
                cal_hit.get("success"),
            )
            out_cal: dict[str, Any] = {
                "message": message,
                "execution_results": execution_results,
                "detected_intent": cal_hit.get("detected_intent", "calendar"),
                "use_tools": bool(cal_hit.get("use_tools", True)),
                "shortcut": "simple_calendar_event",
            }
            if cal_hit.get("error_status"):
                out_cal["error_status"] = cal_hit["error_status"]
            return _attach_diag(out_cal)

    from app.services.compound_business_service import try_compound_business_shortcut

    biz = await try_compound_business_shortcut(
        db, last_user, operator_user_id, operator_source=operator_source
    )
    if biz is not None:
        message, execution_results = _finalize_assistant_message_and_results(
            biz["message"],
            biz["execution_results"],
            last_user=last_user,
        )
        diag["use_tools"] = biz.get("use_tools", False)
        diag["detected_intent"] = biz.get("detected_intent", "compound_project_customer")
        if biz.get("error_status"):
            diag["error_status"] = biz.get("error_status")
        logger.info(
            "event=ai_chat_finished request_id=%s shortcut=%s success=%s",
            request_id,
            biz.get("shortcut"),
            biz.get("success"),
        )
        out_b: dict[str, Any] = {
            "message": message,
            "execution_results": execution_results,
            "detected_intent": biz.get("detected_intent", "compound_project_customer"),
            "use_tools": biz.get("use_tools", False),
            "shortcut": biz.get("shortcut"),
            "template_summary": biz.get("template_summary"),
        }
        if biz.get("partial_results") is not None:
            out_b["partial_results"] = biz["partial_results"]
        if biz.get("error_status"):
            out_b["error_status"] = biz["error_status"]
        return _attach_diag(out_b)

    from app.services.compound_reminder_service import try_simple_local_reminder_shortcut

    rem_hit = await try_simple_local_reminder_shortcut(
        last_user, db, operator_user_id, operator_source=operator_source
    )
    if rem_hit is not None:
        message, execution_results = _finalize_assistant_message_and_results(
            rem_hit["message"],
            rem_hit["execution_results"],
            last_user=last_user,
        )
        diag["use_tools"] = rem_hit.get("use_tools", True)
        diag["detected_intent"] = rem_hit.get("detected_intent", "reminder")
        if rem_hit.get("error_status"):
            diag["error_status"] = rem_hit["error_status"]
        logger.info(
            "event=ai_chat_finished request_id=%s shortcut=%s success=%s",
            request_id,
            rem_hit.get("shortcut"),
            rem_hit.get("success"),
        )
        out_r: dict[str, Any] = {
            "message": message,
            "execution_results": execution_results,
            "detected_intent": rem_hit.get("detected_intent", "reminder"),
            "use_tools": rem_hit.get("use_tools", True),
            "shortcut": rem_hit.get("shortcut"),
            "template_summary": rem_hit.get("template_summary"),
        }
        if rem_hit.get("error_status"):
            out_r["error_status"] = rem_hit["error_status"]
        return _attach_diag(out_r)

    from app.services.compound_business_service import try_customer_interaction_shortcut

    cust_hit = await try_customer_interaction_shortcut(
        last_user, db, operator_user_id, operator_source=operator_source
    )
    if cust_hit is not None:
        message, execution_results = _finalize_assistant_message_and_results(
            cust_hit["message"],
            cust_hit["execution_results"],
            last_user=last_user,
        )
        diag["use_tools"] = cust_hit.get("use_tools", True)
        diag["detected_intent"] = cust_hit.get("detected_intent", "customer")
        if cust_hit.get("error_status"):
            diag["error_status"] = cust_hit["error_status"]
        logger.info(
            "event=ai_chat_finished request_id=%s shortcut=%s success=%s",
            request_id,
            cust_hit.get("shortcut"),
            cust_hit.get("success"),
        )
        out_c: dict[str, Any] = {
            "message": message,
            "execution_results": execution_results,
            "detected_intent": cust_hit.get("detected_intent", "customer"),
            "use_tools": cust_hit.get("use_tools", True),
            "shortcut": cust_hit.get("shortcut"),
            "template_summary": cust_hit.get("template_summary"),
        }
        if cust_hit.get("error_status"):
            out_c["error_status"] = cust_hit["error_status"]
        return _attach_diag(out_c)

    from app.services.compound_business_service import try_simple_customer_create_shortcut

    simple_cust = await try_simple_customer_create_shortcut(
        last_user, db, operator_user_id, operator_source=operator_source
    )
    if simple_cust is not None:
        message, execution_results = _finalize_assistant_message_and_results(
            simple_cust["message"],
            simple_cust["execution_results"],
            last_user=last_user,
        )
        diag["use_tools"] = simple_cust.get("use_tools", True)
        diag["detected_intent"] = simple_cust.get("detected_intent", "customer")
        if simple_cust.get("error_status"):
            diag["error_status"] = simple_cust["error_status"]
        logger.info(
            "event=ai_chat_finished request_id=%s shortcut=%s success=%s",
            request_id,
            simple_cust.get("shortcut"),
            simple_cust.get("success"),
        )
        out_s: dict[str, Any] = {
            "message": message,
            "execution_results": execution_results,
            "detected_intent": simple_cust.get("detected_intent", "customer"),
            "use_tools": simple_cust.get("use_tools", True),
            "shortcut": simple_cust.get("shortcut"),
            "template_summary": simple_cust.get("template_summary"),
        }
        if simple_cust.get("error_status"):
            out_s["error_status"] = simple_cust["error_status"]
        return _attach_diag(out_s)

    t_sm = time.perf_counter()
    sm = try_local_smalltalk_shortcut(last_user)
    if sm is not None:
        message, execution_results = _finalize_assistant_message_and_results(
            sm["message"],
            sm.get("execution_results") or [],
            last_user=last_user,
        )
        diag["use_tools"] = False
        diag["detected_intent"] = None
        diag.setdefault("phase_elapsed_ms", {})["local_smalltalk_ms"] = int((time.perf_counter() - t_sm) * 1000)
        logger.info("event=ai_chat_finished request_id=%s shortcut=local_smalltalk", request_id)
        return _attach_diag({
            "message": message,
            "execution_results": execution_results,
            "detected_intent": None,
            "use_tools": False,
            "shortcut": "local_smalltalk",
        })

    if operator_source == "web" and route_intent is None:
        set_ai_chat_timeout_stage("ollama_first_call")
        assistant_msg, elapsed_ms = await plain_ollama_chat_for_web(db, messages, diag=diag)
        diag["use_tools"] = False
        diag["detected_intent"] = None
        logger.info("event=ai_chat_finished request_id=%s path=plain_chat elapsed_ms=%s", request_id, elapsed_ms)
        return _attach_diag({
            "message": assistant_msg,
            "execution_results": [],
            "detected_intent": None,
            "use_tools": False,
            "elapsed_ms": elapsed_ms,
        })

    if operator_source == "web" and route_intent == "collaboration":
        diag["use_tools"] = False
        logger.info("event=ai_chat_finished request_id=%s path=collaboration_blocked", request_id)
        return _attach_diag({
            "message": {
                "role": "assistant",
                "content": (
                    "桌面单机版暂不支持跨账号协作类自动操作（如外部通道上的转移/通知）。"
                    "请在「项目」中本地调整负责人与协作者，或使用本机账号完成数据维护。"
                ),
            },
            "execution_results": [],
            "detected_intent": "collaboration",
            "use_tools": False,
        })

    t_agent = time.perf_counter()
    set_ai_chat_timeout_stage("ollama_first_call")
    out = await run_agent_loop(
        db,
        messages,
        max_steps=6,
        operator_source=operator_source,
        operator_external_id=operator_external_id,
        operator_user_id=operator_user_id,
        diag=diag,
    )
    message, execution_results = _finalize_assistant_message_and_results(
        out["message"],
        out["execution_results"],
        last_user=last_user,
    )
    elapsed_ms = int((time.perf_counter() - t_agent) * 1000)
    diag["phase_elapsed_ms"]["agent_loop_ms"] = elapsed_ms
    diag["use_tools"] = out.get("use_tools")
    diag["detected_intent"] = out.get("detected_intent")
    if out.get("timeout_stage"):
        diag["timeout_stage"] = out.get("timeout_stage")
    if out.get("error_status"):
        diag["error_status"] = out.get("error_status")
    cfg = await get_active_config(db)
    bu = ""
    mn = ""
    try:
        if cfg:
            mn = cfg.model_name or ""
            bu = normalize_ollama_base_url(cfg.base_url or "")
    except ValueError:
        bu = cfg.base_url or "" if cfg else ""
    logger.info(
        "event=ai_chat_finished request_id=%s base_url=%s model_name=%s intent=%s use_tools=%s agent_loop_ms=%s",
        request_id,
        bu,
        mn,
        out.get("detected_intent"),
        out.get("use_tools"),
        elapsed_ms,
    )
    ret: dict[str, Any] = {
        "message": message,
        "execution_results": execution_results,
        "detected_intent": out.get("detected_intent"),
        "use_tools": out.get("use_tools"),
        "elapsed_ms": elapsed_ms,
    }
    for k in ("timeout_stage", "partial_results", "template_summary", "error_status"):
        if out.get(k) is not None:
            ret[k] = out[k]
    return _attach_diag(ret)
