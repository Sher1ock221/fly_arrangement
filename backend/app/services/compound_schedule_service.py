"""
复合行程：从一句话解析主日程、前置/节点子日程与（可选）周期性本地提醒，并顺序落库。

设计为「解析 → 结构化 → 执行」，客户名仅写入描述与提示文案，不阻塞日历创建。
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.calendar_tools import create_calendar_event
from app.services.reminder_service import create_reminder_task_service

logger = logging.getLogger(__name__)
CST = ZoneInfo("Asia/Shanghai")


@dataclass
class MainEventSpec:
    title: str
    start_date: date
    end_date: date
    description: str = ""


@dataclass
class SubEventSpec:
    title: str
    day: date
    start_h: int = 9
    start_m: int = 0
    end_h: int = 18
    end_m: int = 0
    event_type: str = "task"  # task | meeting


@dataclass
class ParsedCompound:
    main: MainEventSpec | None
    sub_events: list[SubEventSpec] = field(default_factory=list)
    wants_daily_feishu_reminder: bool = False
    customer_hints: list[str] = field(default_factory=list)


def _infer_year_for_month_day(month: int, day: int, ref: date) -> int:
    try:
        candidate = date(ref.year, month, day)
    except ValueError:
        return ref.year
    if candidate < ref:
        return ref.year + 1
    return ref.year


def _combine_local(d: date, h: int, mi: int = 0) -> datetime:
    return datetime.combine(d, time(h, mi, 0), tzinfo=CST)


def parse_compound_schedule_request(text: str, ref: date | None = None) -> ParsedCompound:
    """
    从自然语言抽取主日程、子节点与是否需每日提醒（启发式，可迭代扩展）。
    ref：推断年份的基准日，默认今天。
    """
    ref = ref or date.today()
    t = (text or "").strip()
    out = ParsedCompound(main=None, sub_events=[], wants_daily_feishu_reminder=False, customer_hints=[])

    if "飞书提醒" in t or ("每天" in t and "提醒" in t) or ("每日" in t and "提醒" in t):
        out.wants_daily_feishu_reminder = True

    # 客户/单位提示：XX所、公司等（仅写入描述，不调用 resolve_customer）
    for m in re.finditer(r"([\u4e00-\u9fff]{2,12}所)", t):
        name = m.group(1).strip()
        if name not in out.customer_hints:
            out.customer_hints.append(name)

    m_start: date | None = None
    m_end: date | None = None
    title_core = ""

    # 模式：4月8日、9日 / 4月8日，9日
    r_multi = re.search(
        r"(\d{1,2})月(\d{1,2})日[、,，]\s*(\d{1,2})\s*日",
        t,
    )
    if r_multi:
        month = int(r_multi.group(1))
        d1 = int(r_multi.group(2))
        d2 = int(r_multi.group(3))
        y = _infer_year_for_month_day(month, d1, ref)
        m_start = date(y, month, d1)
        m_end = date(y, month, d2)
        tail = t[r_multi.end() :]
        tm = re.match(r"\s*([^，。；]+?(?:组织)?培训)", tail)
        if tm:
            title_core = tm.group(1).strip()
        else:
            tm2 = re.match(r"\s*([^，。；]{2,40}?)，", tail)
            if tm2:
                title_core = (tm2.group(1).strip() + "培训") if "培训" not in tm2.group(1) else tm2.group(1).strip()

    # 模式：4月8日至9日 / 4月8日-9日
    if m_start is None:
        r_range = re.search(r"(\d{1,2})月(\d{1,2})日\s*[至\-～~]\s*(\d{1,2})\s*日", t)
        if r_range:
            month = int(r_range.group(1))
            d1 = int(r_range.group(2))
            d2 = int(r_range.group(3))
            y = _infer_year_for_month_day(month, d1, ref)
            m_start = date(y, month, d1)
            m_end = date(y, month, d2)
            tail = t[r_range.end() :]
            tm = re.search(r"([^，。；]+?(?:组织)?培训)", tail)
            if tm:
                title_core = tm.group(1).strip()

    if m_start and m_end and m_end < m_start:
        m_start, m_end = m_end, m_start

    # 前置节点：需要在4月7日确定……
    prep_title = ""
    prep_day: date | None = None
    r_prep = re.search(
        r"需(?:要)?在\s*(\d{1,2})月(\d{1,2})日\s*([^，。；请]+?)(?=请|，|。|；|$)",
        t,
    )
    if r_prep:
        pm = int(r_prep.group(1))
        pd = int(r_prep.group(2))
        yp = _infer_year_for_month_day(pm, pd, ref)
        prep_day = date(yp, pm, pd)
        prep_title = r_prep.group(3).strip()
        prep_title = re.sub(r"[，、]+$", "", prep_title)

    # 其中9日下午为考试
    exam_title = ""
    exam_day: date | None = None
    slot = ""
    r_exam = re.search(
        r"(?:其中\s*)?(\d{1,2})日\s*(上午|下午|晚上)?\s*为\s*([^，。；]+)",
        t,
    )
    if r_exam:
        day_only = int(r_exam.group(1))
        slot = r_exam.group(2) or ""
        exam_title = r_exam.group(3).strip()
        if m_start:
            month_use = m_start.month
            year_use = m_start.year
        elif prep_day:
            month_use = prep_day.month
            year_use = prep_day.year
        else:
            month_use = ref.month
            year_use = ref.year
        try:
            exam_day = date(year_use, month_use, day_only)
        except ValueError:
            exam_day = None
        if exam_day and exam_title:
            sh, sm, eh, em = 9, 0, 18, 0
            if slot == "下午" or (not slot and "下午" in t[r_exam.start() : r_exam.end()]):
                sh, sm, eh, em = 14, 0, 17, 0
            elif slot == "上午":
                sh, sm, eh, em = 9, 0, 12, 0
            elif slot == "晚上":
                sh, sm, eh, em = 18, 0, 21, 0
            out.sub_events.append(
                SubEventSpec(
                    title=exam_title[:120],
                    day=exam_day,
                    start_h=sh,
                    start_m=sm,
                    end_h=eh,
                    end_m=em,
                    event_type="meeting",
                )
            )

    if prep_day and prep_title:
        out.sub_events.insert(
            0,
            SubEventSpec(
                title=prep_title[:120],
                day=prep_day,
                start_h=9,
                start_m=0,
                end_h=18,
                end_m=0,
                event_type="task",
            ),
        )

    if m_start and m_end:
        main_title = (title_core or "培训安排").strip()
        if main_title and "培训" not in main_title and ("培训" in t or "训练" in t):
            main_title = f"{main_title}培训" if not main_title.endswith("训") else main_title
        desc_parts: list[str] = []
        if out.customer_hints:
            desc_parts.append("参与/相关单位：" + "、".join(out.customer_hints))
        if r_exam and exam_title:
            desc_parts.append(f"关键节点：{r_exam.group(1)}日{f'({slot})' if slot else ''}{exam_title}")
        if prep_title and prep_day:
            desc_parts.append(f"前置事项：{prep_day.strftime('%Y-%m-%d')}{prep_title}")
        out.main = MainEventSpec(
            title=main_title[:250],
            start_date=m_start,
            end_date=m_end,
            description="\n".join(desc_parts),
        )

    return out


def is_compound_shortcut_candidate(text: str) -> bool:
    """是否与「培训/行程 + 多日期 + 前置或飞书提醒」类复合话术高度相关（走本地快捷执行）。"""
    if not text or len(text) < 8:
        return False
    t = text.strip()
    has_span = bool(re.search(r"\d{1,2}月\d{1,2}日[、,，]\s*\d{1,2}\s*日", t)) or bool(
        re.search(r"\d{1,2}月\d{1,2}日\s*[至\-～~]\s*\d{1,2}\s*日", t)
    )
    has_prep = bool(re.search(r"需(?:要)?在\s*\d{1,2}月\d{1,2}日", t))
    has_training = any(k in t for k in ("培训", "训练", "集训", "行程", "日程"))
    has_rem = ("飞书提醒" in t) or ("每天" in t and "提醒" in t) or ("每日" in t and "提醒" in t)
    if not has_span:
        return False
    if has_training and (has_prep or has_rem):
        return True
    if has_training and has_span:
        return True
    return False


def build_customer_note(hints: list[str]) -> str:
    if not hints:
        return ""
    return f"未在系统中自动关联客户「{'、'.join(hints)}」；相关信息已写入日程描述，不影响日程创建。"


async def execute_compound_schedule_plan(
    db: AsyncSession,
    text: str,
    *,
    operator_user_id: int | None,
    project_id: int | None = None,
    ref_date: date | None = None,
    operator_source: str | None = None,
) -> dict[str, Any]:
    """
    解析并执行复合行程。返回单条工具风格结果（tool_name=execute_compound_schedule），
    供 execution_results 与快捷路径复用。
    """
    if operator_user_id is None:
        return {
            "success": False,
            "error": "需要用户身份才能创建日程与提醒",
            "execution_summary": "缺少用户身份",
            "tool_name": "execute_compound_schedule",
            "result": {},
        }

    parsed = parse_compound_schedule_request(text, ref=ref_date or date.today())
    if not parsed.main:
        return {
            "success": False,
            "error": "未能从话术中解析出主日程日期范围",
            "execution_summary": "复合行程解析未命中主日程",
            "tool_name": "execute_compound_schedule",
            "result": {"parsed": False},
        }

    main = parsed.main
    lines_ok: list[str] = []
    lines_fail: list[str] = []
    warnings: list[str] = []
    if parsed.customer_hints:
        warnings.append(build_customer_note(parsed.customer_hints))

    main_start = _combine_local(main.start_date, 9, 0)
    main_end = _combine_local(main.end_date, 18, 0)
    main_desc = (main.description or "").strip()

    main_res = await create_calendar_event(
        db,
        title=main.title,
        start_time=main_start.isoformat(),
        end_time=main_end.isoformat(),
        description=main_desc or None,
        type="meeting",
        project_id=project_id,
        owner_user_id=operator_user_id,
    )
    main_id: int | None = None
    if main_res.get("success") and isinstance(main_res.get("result"), dict):
        main_id = int(main_res["result"]["id"])
        lines_ok.append(
            f"已创建主日程「{main.title}」({main.start_date.isoformat()}～{main.end_date.isoformat()})，id={main_id}"
        )
    else:
        lines_fail.append(f"主日程创建失败：{main_res.get('error') or main_res.get('execution_summary')}")

    sub_ids: list[int] = []
    for sub in parsed.sub_events:
        st = _combine_local(sub.day, sub.start_h, sub.start_m)
        et = _combine_local(sub.day, sub.end_h, sub.end_m)
        if et <= st:
            et = st + timedelta(hours=1)
        sub_desc = f"复合行程子节点（关联主活动：{main.title}）"
        sr = await create_calendar_event(
            db,
            title=sub.title,
            start_time=st.isoformat(),
            end_time=et.isoformat(),
            description=sub_desc,
            type=sub.event_type if sub.event_type in ("task", "meeting", "event") else "task",
            project_id=project_id,
            owner_user_id=operator_user_id,
        )
        if sr.get("success") and isinstance(sr.get("result"), dict):
            sid = int(sr["result"]["id"])
            sub_ids.append(sid)
            lines_ok.append(f"已创建子日程「{sub.title}」({sub.day.isoformat()})，id={sid}")
        else:
            lines_fail.append(
                f"子日程「{sub.title}」失败：{sr.get('error') or sr.get('execution_summary')}"
            )

    reminder_id: int | None = None
    execution_results_extras: list[dict[str, Any]] = []
    if parsed.wants_daily_feishu_reminder and main_id:
        until_dt = _combine_local(main.end_date, 23, 59).replace(second=59)
        rem_content = (
            f"提醒：「{main.title}」进行中。"
            + (f" 请关注前置事项与节点安排。" if parsed.sub_events else "")
        )
        rem_channel = "local" if (operator_source or "").strip() == "web" else "feishu_private"
        rr = await create_reminder_task_service(
            db,
            operator_user_id=operator_user_id,
            title=f"{main.title} — 每日提醒",
            content=rem_content,
            channel=rem_channel,
            reminder_type="recurring",
            schedule_rule={"freq": "daily", "trigger_time": "09:00"},
            related_event_id=main_id,
            related_project_id=project_id,
            end_at=until_dt.isoformat(),
            operator_source=operator_source,
        )
        if rr.get("success") and isinstance(rr.get("result"), dict):
            reminder_id = int(rr["result"].get("reminder_task_id") or rr["result"].get("id") or 0)
            if (operator_source or "").strip() == "web":
                lines_ok.append(
                    f"已创建每日本地提醒至 {until_dt.date().isoformat()}，reminder_task_id={reminder_id}"
                )
            else:
                lines_ok.append(f"已创建每日飞书提醒至 {until_dt.date().isoformat()}，reminder_task_id={reminder_id}")
        else:
            rlabel = "本地提醒" if (operator_source or "").strip() == "web" else "飞书提醒"
            fail_msg = f"{rlabel}未创建：{rr.get('error') or rr.get('execution_summary')}"
            lines_fail.append(fail_msg)
            execution_results_extras.append(
                {
                    "success": False,
                    "tool_name": "create_reminder_task",
                    "error": rr.get("error") or fail_msg,
                    "execution_summary": fail_msg,
                }
            )

    success = main_id is not None
    result_obj: dict[str, Any] = {
        "main_event_id": main_id,
        "sub_event_ids": sub_ids,
        "reminder_task_id": reminder_id,
        "customer_hints": parsed.customer_hints,
        "lines_ok": lines_ok,
        "lines_fail": lines_fail,
        "warnings": warnings,
    }
    summary = " ".join(lines_ok) if lines_ok else (lines_fail[0] if lines_fail else "无操作")

    assistant_lines = ["已按复合行程处理，分项结果如下："]
    for i, s in enumerate(lines_ok, 1):
        assistant_lines.append(f"{i}. {s}")
    off = len(lines_ok) + 1
    for j, s in enumerate(lines_fail, off):
        assistant_lines.append(f"{j}. 未完成：{s}")
    if warnings:
        assistant_lines.append("")
        assistant_lines.extend(warnings)

    return {
        "success": success,
        "tool_name": "execute_compound_schedule",
        "execution_summary": summary,
        "error": None if success else (lines_fail[0] if lines_fail else "执行失败"),
        "result": result_obj,
        "assistant_text": "\n".join(assistant_lines),
        "execution_results_extras": execution_results_extras,
    }


async def try_compound_schedule_shortcut(
    db: AsyncSession,
    user_text: str,
    operator_user_id: int | None,
    *,
    operator_source: str | None = None,
) -> dict[str, Any] | None:
    """
    若命中复合话术且解析成功创建主日程，返回与 chat_and_execute_tools 相同的外层结构；
    否则返回 None（继续走 Agent）。
    """
    if not operator_user_id or not is_compound_shortcut_candidate(user_text):
        return None
    raw = await execute_compound_schedule_plan(
        db, user_text, operator_user_id=operator_user_id, operator_source=operator_source
    )
    if not raw.get("success"):
        logger.info("compound shortcut skipped: parse ok but main failed or no main: %s", raw.get("error"))
        return None
    er = {
        "success": raw.get("success"),
        "tool_name": "execute_compound_schedule",
        "result": raw.get("result"),
        "execution_summary": raw.get("execution_summary"),
        "error": raw.get("error"),
    }
    extras = list(raw.get("execution_results_extras") or [])
    return {
        "message": {"role": "assistant", "content": raw.get("assistant_text") or raw.get("execution_summary", "")},
        "execution_results": [er, *extras],
    }


def _simple_calendar_has_reminder_marker(text: str) -> bool:
    t = (text or "").strip()
    if any(x in t for x in ("提醒我", "提醒一下", "记得提醒", "定时提醒")):
        return True
    if re.search(r"(?:明天|后天|今天|下周).{0,12}提醒", t):
        return True
    return False


def _simple_calendar_has_project_creation_marker(text: str) -> bool:
    t = (text or "").strip()
    if re.search(r"(新建|创建|新增)\s*一个?\s*项目", t):
        return True
    if "新建项目" in t or "创建项目" in t or "新增项目" in t:
        return True
    return False


def _simple_calendar_topic_keyword(text: str) -> bool:
    t = (text or "").strip()
    return any(k in t for k in ("日程", "会议", "开会", "行程", "预约"))


def _simple_calendar_action_keyword(text: str) -> bool:
    t = (text or "").strip()
    if re.search(r"(新建|新增|创建|安排)", t):
        return True
    if "帮我加" in t or "帮我建" in t or "帮我安排" in t:
        return True
    return False


def _simple_calendar_time_clue(text: str) -> bool:
    t = (text or "").strip()
    if any(x in t for x in ("今天", "明天", "后天")):
        return True
    if any(x in t for x in ("上午", "下午", "晚上", "中午", "凌晨")):
        return True
    if "下周" in t:
        return True
    if re.search(r"周[一二三四五六日天]", t) and ("下周" in t or "本周" in t or "这周" in t):
        return True
    if re.search(r"\d{1,2}\s*[:\：]\s*\d{2}", t):
        return True
    if re.search(r"\d{1,2}\s*点半?", t):
        return True
    if re.search(r"[零一二三四五六七八九十两]+\s*点", t):
        return True
    return False


def _extract_simple_calendar_title(text: str) -> str:
    t = (text or "").strip()
    m = re.search(r"关于\s*(.+?)\s*的(?:会议|日程)", t)
    if m:
        core = m.group(1).strip()
        return core[:200] if core else ""
    m2 = re.search(r"会议内容(?:是|为)?\s*([^，。；]+)", t)
    if m2:
        return m2.group(1).strip()[:200]
    m3 = re.search(r"内容是\s*([^，。；]+)", t)
    if m3:
        return m3.group(1).strip()[:200]
    m4 = re.search(r"[，,]\s*([^，。；]{2,80}(?:开会|会议|日程))\s*$", t)
    if m4:
        return m4.group(1).strip()[:200]
    m5 = re.search(r"(?:商讨|讨论)\s*([^，。；]{2,40}?)(?:的)?(?:会议|架构)", t)
    if m5:
        s = m5.group(1).strip()
        return (s + "会议")[:200] if s else ""
    return ""


async def try_simple_calendar_event_shortcut(
    user_text: str,
    db: AsyncSession,
    operator_user_id: int,
    operator_source: str = "web",
) -> dict[str, Any] | None:
    """
    明确「新建/安排 + 时间 + 会议或日程」类话术：直接走 auto_schedule_event，不经 Ollama 工具规划。
    与 simple_local_reminder 互斥（须无「提醒我」等）；不与项目创建话术抢道。
    """
    if (operator_source or "").strip() != "web":
        return None
    if not operator_user_id:
        return None
    if not getattr(settings, "AI_SIMPLE_CALENDAR_SHORTCUT_ENABLED", True):
        return None
    t = (user_text or "").strip()
    if len(t) < 6 or len(t) > 220:
        return None
    if _simple_calendar_has_reminder_marker(t):
        return None
    if _simple_calendar_has_project_creation_marker(t):
        return None
    if not _simple_calendar_topic_keyword(t):
        return None
    if not _simple_calendar_time_clue(t):
        return None
    if not _simple_calendar_action_keyword(t):
        return None

    title = _extract_simple_calendar_title(t)
    if not title or len(title.strip()) < 2:
        title = "日程事项"

    from app.services.schedule_suggestion_service import auto_schedule_event

    raw = await auto_schedule_event(
        db,
        actor_user_id=operator_user_id,
        text=t,
        title=title,
        event_type="meeting",
    )

    res = raw.get("result") if isinstance(raw.get("result"), dict) else {}
    if raw.get("success") and res.get("time_semantic_type") == "candidate_dates_with_explicit_time":
        logger.info("simple_calendar_event shortcut skipped: candidate_dates flow needs user follow-up")
        return None

    er: dict[str, Any] = {
        "success": bool(raw.get("success")),
        "tool_name": "auto_schedule_event",
        "result": raw.get("result"),
        "execution_summary": str(raw.get("execution_summary") or raw.get("message") or "").strip()
        or ("已处理日程请求" if raw.get("success") else "日程创建未成功"),
        "error": None if raw.get("success") else str(raw.get("message") or raw.get("execution_summary") or "失败"),
    }

    assistant_body = str(raw.get("message") or "").strip() or er["execution_summary"]
    if not raw.get("success"):
        assistant_body = assistant_body or "未能根据描述创建日程，请补充更具体的时间段（例如「明天下午3点」）后再试。"

    logger.info(
        "event=ai_shortcut_matched shortcut=simple_calendar_event success=%s title=%r",
        raw.get("success"),
        title[:80],
    )
    return {
        "message": {"role": "assistant", "content": assistant_body},
        "execution_results": [er],
        "detected_intent": "calendar",
        "use_tools": True,
        "shortcut": "simple_calendar_event",
        "success": bool(raw.get("success")),
    }
