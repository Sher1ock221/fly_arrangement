"""
高置信度「本地提醒」快速路径：命中时不走 Ollama 工具规划，直接 create_reminder_task_service 落库。

仅桌面 web（operator_source=web），channel 恒为 local。
"""
from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.reminder_service import create_reminder_task_service

logger = logging.getLogger(__name__)


def _is_calendar_creation_intent(text: str) -> bool:
    t = (text or "").strip()
    if re.search(r"新建会议|新建日程|安排会议|创建会议|创建日程|添加到日历", t):
        return True
    if re.search(r"(新建|创建|新增|安排).{0,12}(会议|日程)", t) and "提醒" not in t:
        return True
    return False


def _is_project_creation_intent(text: str) -> bool:
    t = (text or "").strip()
    if re.search(r"(新建|创建)\s*一个?\s*项目|新建项目|创建项目", t):
        return True
    return False


def _has_reminder_marker(text: str) -> bool:
    t = (text or "").strip()
    if any(x in t for x in ("提醒我", "提醒一下", "记得提醒", "明天提醒", "后天提醒")):
        return True
    if re.search(r"下午\s*[0-9一二三四五六七八九十两]+\s*点提醒", t):
        return True
    return False


def _has_time_clue(text: str) -> bool:
    t = (text or "").strip()
    if any(x in t for x in ("明天", "后天", "今天", "上午", "下午", "晚上", "下周")):
        return True
    if re.search(r"\d{1,2}\s*:\s*\d{2}", t):
        return True
    if re.search(r"\d{1,2}\s*点", t):
        return True
    if re.search(r"[一二三四五六七八九十两]+\s*点", t):
        return True
    return False


async def try_simple_local_reminder_shortcut(
    user_text: str,
    db: AsyncSession,
    operator_user_id: int | None,
    *,
    operator_source: str = "web",
) -> dict[str, Any] | None:
    """
    命中简单本地提醒话术时，返回与 chat_and_execute_tools 兼容的字典；否则 None。
    """
    if (operator_source or "").strip() != "web":
        return None
    if operator_user_id is None:
        return None
    t = (user_text or "").strip()
    if not t:
        return None
    if _is_calendar_creation_intent(t) or _is_project_creation_intent(t):
        return None
    if not _has_reminder_marker(t) or not _has_time_clue(t):
        return None

    logger.info("event=ai_shortcut_matched shortcut=simple_local_reminder user_text_len=%s", len(t))

    res = await create_reminder_task_service(
        db,
        operator_user_id=operator_user_id,
        title=t[:200] if len(t) > 200 else t,
        content=t,
        channel="local",
        reminder_type="one_time",
        schedule_rule=None,
        related_event_id=None,
        related_project_id=None,
        related_customer_id=None,
        end_at=None,
        trigger_at=None,
        operator_source="web",
    )

    er: dict[str, Any] = {
        "success": bool(res.get("success")),
        "tool_name": "create_reminder_task",
        "result": res.get("result"),
        "execution_summary": res.get("execution_summary") or res.get("error") or "",
        "error": res.get("error"),
    }

    if not res.get("success"):
        err = str(res.get("error") or res.get("execution_summary") or "创建提醒失败")
        logger.warning("event=ai_shortcut_failed shortcut=simple_local_reminder err=%s", err)
        return {
            "success": False,
            "shortcut": "simple_local_reminder",
            "message": {"role": "assistant", "content": f"未能创建本地提醒：{err}"},
            "execution_results": [er],
            "detected_intent": "reminder",
            "use_tools": True,
            "template_summary": False,
            "error_status": "simple_local_reminder_failed",
        }

    data = res.get("result") or {}
    rid = data.get("id") or data.get("reminder_task_id")
    title_out = str(data.get("title") or "").strip() or (t[:80] if t else "提醒")
    next_at = data.get("next_trigger_at")
    summary = (
        f"已为你创建本地提醒「{title_out}」（reminder_task_id={rid}，"
        f"下次触发：{next_at or '（已写入计划）'}）。"
    )
    logger.info("event=ai_chat_finished shortcut=simple_local_reminder success=1 task_id=%s", rid)
    return {
        "success": True,
        "shortcut": "simple_local_reminder",
        "message": {"role": "assistant", "content": summary},
        "execution_results": [er],
        "detected_intent": "reminder",
        "use_tools": True,
        "template_summary": True,
    }
