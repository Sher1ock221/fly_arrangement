from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

CST = timezone(timedelta(hours=8))
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 单次飞书提醒：相对触发时间统一解析（与 LLM 传入的 ISO 一并在此收口）
# ---------------------------------------------------------------------------


def _now_cst(now_utc: datetime | None) -> datetime:
    n = now_utc or datetime.now(timezone.utc)
    if n.tzinfo is None:
        n = n.replace(tzinfo=timezone.utc)
    return n.astimezone(CST)


def _combine_reminder_text(trigger_at: str | None, title: str, content: str | None) -> str:
    parts = [str(trigger_at or "").strip(), str(title or "").strip(), str(content or "").strip()]
    return " ".join(p for p in parts if p)


def _explicit_past_reminder_intent(text: str) -> bool:
    """用户明确要过去的时点（不可自动纠正为将来）。"""
    t = text.strip()
    if re.search(r"\d+\s*分钟前", t):
        return True
    if re.search(r"\d+\s*(?:小时|小時|钟头)前", t):
        return True
    if re.search(r"(昨天|前天).{0,6}提醒", t):
        return True
    if "刚才提醒我" in t or "刚刚提醒我" in t:
        return True
    return False


def _parse_iso_or_naive_local(s: str) -> datetime | None:
    s = s.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=CST)
    return dt.astimezone(CST)


def resolve_reminder_oneshot_trigger_datetime(
    *,
    trigger_at: str | None,
    title: str,
    content: str | None,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """
    解析单次提醒的触发时刻（东八区语义），返回 CST 时区的“绝对触发时间”（naive 与 CST tz 均可，由调用方转 UTC）。

    返回:
      - ok=True: { "ok": True, "trigger_cst": datetime(tzinfo=CST), "source": str }
      - ok=False: { "ok": False, "error": str }  （仅明确过去意图或完全无法解析）
    """
    bundle = _combine_reminder_text(trigger_at, title, content)
    if not bundle.strip():
        return {"ok": False, "error": "缺少触发时间和内容，无法解析"}

    if _explicit_past_reminder_intent(bundle):
        return {"ok": False, "error": "您指定的提醒时间早于或等于当前意图时间，请使用未来时间（例如 1 分钟后）。"}

    now = _now_cst(now_utc)

    # —— 相对：N 分钟后 / 小时后 ——
    m = re.search(r"(\d+)\s*(?:分钟|分鐘)[后後]?提醒", bundle)
    if not m:
        m = re.search(r"(?:提醒[^，。]{0,20})?(\d+)\s*(?:分钟|分鐘)[后後]", bundle)
    if not m:
        m = re.search(r"(\d+)\s*(?:分钟|分鐘)[后後]", bundle)
    if m:
        n_min = int(m.group(1))
        if n_min < 0:
            return {"ok": False, "error": "提醒偏移无效"}
        target = now + timedelta(minutes=n_min)
        return {"ok": True, "trigger_cst": target, "source": f"relative_{n_min}min"}

    m = re.search(r"(\d+)\s*(?:小时|小時|钟头)[后後]", bundle)
    if m:
        n_h = int(m.group(1))
        if n_h < 0:
            return {"ok": False, "error": "提醒偏移无效"}
        target = now + timedelta(hours=n_h)
        return {"ok": True, "trigger_cst": target, "source": f"relative_{n_h}h"}

    if any(k in bundle for k in ("马上", "立刻", "立即", "现在提醒", "赶紧提醒")):
        return {"ok": True, "trigger_cst": now, "source": "asap"}

    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today + timedelta(days=1)
    day_after = today + timedelta(days=2)

    if "今天下午" in bundle:
        afternoon_start = today.replace(hour=14, minute=0, second=0, microsecond=0)
        afternoon_end = today.replace(hour=18, minute=0, second=0, microsecond=0)
        if now >= afternoon_end:
            slot = tomorrow.replace(hour=14, minute=0, second=0, microsecond=0)
        elif now >= afternoon_start:
            slot = now
        else:
            slot = afternoon_start
        return {"ok": True, "trigger_cst": slot, "source": "this_afternoon"}

    if "明天上午" in bundle:
        t = tomorrow.replace(hour=9, minute=0, second=0, microsecond=0)
        return {"ok": True, "trigger_cst": t, "source": "tomorrow_morning"}

    if "明天下午" in bundle:
        t = tomorrow.replace(hour=14, minute=0, second=0, microsecond=0)
        return {"ok": True, "trigger_cst": t, "source": "tomorrow_afternoon"}

    m = re.search(r"明天\s*(\d{1,2})\s*(?:点|點)(?:(\d{1,2})\s*分)?", bundle)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2) or 0)
        t = tomorrow.replace(hour=min(hh, 23), minute=min(mm, 59), second=0, microsecond=0)
        return {"ok": True, "trigger_cst": t, "source": "tomorrow_clock"}

    if "后天中午" in bundle or "後天中午" in bundle:
        t = day_after.replace(hour=12, minute=0, second=0, microsecond=0)
        return {"ok": True, "trigger_cst": t, "source": "day_after_noon"}

    # —— ISO / 显式日期时间字符串 ——
    ta = (trigger_at or "").strip()
    if ta:
        parsed = _parse_iso_or_naive_local(ta)
        if parsed:
            return {"ok": True, "trigger_cst": parsed, "source": "iso_trigger_at"}

    return {"ok": False, "error": "无法解析触发时间，请使用如「5 分钟后」「明天上午」或 ISO 时间。"}

_EXPLICIT_HINT_PATTERN = re.compile(
    r"(今天|明天|后天|下周[一二三四五六日天]|(?:周|星期)[一二三四五六日天]|\d{1,2}月\d{1,2}日|\d{1,2}[:：]\d{2}|\d{1,2}点|上午|下午|晚上)"
)

_WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 轻量节日锚点：固定日期 + 常见农历节日在近年映射（可继续扩展）
_FIXED_HOLIDAYS = {
    "元旦": (1, 1),
    "五一": (5, 1),
    "劳动节": (5, 1),
    "国庆": (10, 1),
}
_LUNAR_HOLIDAY_APPROX: dict[int, dict[str, tuple[int, int]]] = {
    2025: {"春节": (1, 29), "端午": (5, 31), "中秋": (10, 6)},
    2026: {"春节": (2, 17), "端午": (6, 19), "中秋": (9, 25)},
    2027: {"春节": (2, 6), "端午": (6, 9), "中秋": (9, 15)},
    2028: {"春节": (1, 26), "端午": (5, 28), "中秋": (10, 3)},
}


def _to_cst(now: datetime) -> datetime:
    if now.tzinfo is None:
        return now.replace(tzinfo=CST)
    return now.astimezone(CST)


def _day_start(d: datetime) -> datetime:
    return d.replace(hour=0, minute=0, second=0, microsecond=0)


def _workday_start(d: datetime) -> datetime:
    return d.replace(hour=9, minute=0, second=0, microsecond=0)


def _workday_end(d: datetime) -> datetime:
    return d.replace(hour=18, minute=0, second=0, microsecond=0)


def _is_workday(d: datetime) -> bool:
    return d.weekday() < 5


def _next_workday(d: datetime) -> datetime:
    cur = _day_start(d)
    while not _is_workday(cur):
        cur += timedelta(days=1)
    return cur


def _prev_workday(d: datetime) -> datetime:
    cur = _day_start(d)
    while not _is_workday(cur):
        cur -= timedelta(days=1)
    return cur


def _add_workdays(d: datetime, days: int) -> datetime:
    cur = _day_start(d)
    step = 1 if days >= 0 else -1
    left = abs(days)
    while left > 0:
        cur += timedelta(days=step)
        if _is_workday(cur):
            left -= 1
    return cur


def _qingming_date(year: int) -> datetime:
    # 轻量近似，避免“清明节后”被排到节前
    day = 4 if year % 4 == 0 else 5
    return datetime(year, 4, day, tzinfo=CST)


def _holiday_anchor(text: str, now: datetime) -> tuple[str, datetime] | None:
    year = now.year
    if "清明" in text:
        return "qingming", _qingming_date(year)
    for k, (m, d) in _FIXED_HOLIDAYS.items():
        if k in text:
            return k, datetime(year, m, d, tzinfo=CST)
    for k, md in _LUNAR_HOLIDAY_APPROX.get(year, {}).items():
        if k in text:
            return k, datetime(year, md[0], md[1], tzinfo=CST)
    return None


def parse_time_semantics(text: str, now: datetime | None = None) -> dict[str, Any]:
    if now is None:
        now = datetime.now(CST)
    now = _to_cst(now)
    today = _day_start(now)

    result: dict[str, Any] = {
        "time_intent_type": "range",
        "range_start": _workday_start(today),
        "range_end": _workday_end(_add_workdays(today, 7)),
        "preferred_days": [],
        "preferred_slots": ["morning", "afternoon"],
        "urgency_level": "normal",
        "semantic_label": "default_next_7_workdays",
        "confidence": 0.55,
    }
    t = (text or "").strip()

    candidate_m = re.search(r"(\d{1,2})号\s*(?:或者|或)\s*(\d{1,2})号", t)
    if candidate_m and re.search(r"(?:\d{1,2}[:：]\d{2}|\d{1,2}点(?:半)?)", t):
        d1 = int(candidate_m.group(1))
        d2 = int(candidate_m.group(2))
        candidates: list[str] = []
        for day in (d1, d2):
            try:
                dt = today.replace(day=day)
                if dt < today:
                    dt = dt.replace(year=dt.year + 1)
                candidates.append(dt.strftime("%Y-%m-%d"))
            except ValueError:
                continue
        if candidates:
            tm = re.search(r"(\d{1,2})[:：](\d{2})", t)
            if tm:
                hh = int(tm.group(1))
                mm = int(tm.group(2))
            else:
                hm = re.search(r"(\d{1,2})点(半)?", t)
                hh = int(hm.group(1)) if hm else 9
                mm = 30 if hm and hm.group(2) else 0
            if "晚上" in t and 1 <= hh <= 11:
                hh += 12
            result["time_intent_type"] = "explicit"
            result["semantic_label"] = "candidate_dates_with_explicit_time"
            result["date_candidates"] = candidates
            result["time_point"] = f"{min(max(hh,0),23):02d}:{min(max(mm,0),59):02d}"
            result["confidence"] = 0.96
            return result

    # 先处理高确定性的中文相对日期/时间点，避免落入默认“未来7个工作日”窗口
    day_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
    if "后天" in t:
        target = today + timedelta(days=2)
        result["time_intent_type"] = "explicit"
        result["semantic_label"] = "day_after_tomorrow"
        result["range_start"] = _workday_start(target)
        result["range_end"] = _workday_end(target)
        result["confidence"] = 0.95
    elif "明天" in t:
        target = today + timedelta(days=1)
        result["time_intent_type"] = "explicit"
        if "上午" in t:
            result["semantic_label"] = "tomorrow_morning"
            result["preferred_slots"] = ["morning"]
        elif "下午" in t:
            result["semantic_label"] = "tomorrow_afternoon"
            result["preferred_slots"] = ["afternoon"]
        elif "今晚" in t:
            result["semantic_label"] = "tomorrow_evening"
            result["preferred_slots"] = ["evening"]
        else:
            result["semantic_label"] = "tomorrow"
        result["range_start"] = _workday_start(target)
        result["range_end"] = _workday_end(target)
        result["confidence"] = 0.95
    elif "今天" in t:
        result["time_intent_type"] = "explicit"
        if "今晚" in t or "晚上" in t:
            result["semantic_label"] = "today_evening"
            result["preferred_slots"] = ["evening"]
        elif "上午" in t:
            result["semantic_label"] = "today_morning"
            result["preferred_slots"] = ["morning"]
        elif "下午" in t:
            result["semantic_label"] = "today_afternoon"
            result["preferred_slots"] = ["afternoon"]
        else:
            result["semantic_label"] = "today"
        result["range_start"] = _workday_start(today)
        result["range_end"] = _workday_end(today)
        result["confidence"] = 0.92
    else:
        m = re.search(r"下周([一二三四五六日天])", t)
        if m:
            target_wd = day_map[m.group(1)]
            next_mon = today + timedelta(days=(7 - today.weekday()))
            target = next_mon + timedelta(days=target_wd)
            result["time_intent_type"] = "explicit"
            result["semantic_label"] = f"next_weekday_{m.group(1)}"
            result["range_start"] = _workday_start(target)
            result["range_end"] = _workday_end(target)
            result["preferred_days"] = [f"周{m.group(1)}" if m.group(1) != "天" else "周日"]
            result["confidence"] = 0.94

    logger.info(
        "time_semantic parsed text=%r cst_today=%s semantic_label=%s range_start=%s range_end=%s",
        t,
        today.date().isoformat(),
        result.get("semantic_label"),
        result.get("range_start"),
        result.get("range_end"),
    )

    # 紧急度
    if any(k in t for k in ("尽快",)):
        result["time_intent_type"] = "urgency"
        result["urgency_level"] = "high"
        result["semantic_label"] = "asap"
        result["range_start"] = _workday_start(_next_workday(today))
        result["range_end"] = _workday_end(_add_workdays(today, 3))
        result["confidence"] = 0.8
    elif any(k in t for k in ("提前约", "提前定", "提前安排")):
        result["urgency_level"] = "high"
        result["semantic_label"] = "book_in_advance"
        result["range_end"] = _workday_end(_add_workdays(today, 5))
        result["confidence"] = max(result["confidence"], 0.72)
    elif any(k in t for k in ("抽空", "找个时间", "找时间", "找个空档")):
        result["time_intent_type"] = "relative"
        result["semantic_label"] = "find_a_slot"
        result["range_end"] = _workday_end(_add_workdays(today, 7))
        result["confidence"] = max(result["confidence"], 0.68)

    # 显式时间 hint
    if _EXPLICIT_HINT_PATTERN.search(t) and result.get("semantic_label") == "default_next_7_workdays":
        result["time_intent_type"] = "explicit"
        result["semantic_label"] = "explicit_hint"
        result["confidence"] = max(result["confidence"], 0.9)

    # 时段偏好
    slots: list[str] = []
    if "上午" in t:
        slots.append("morning")
    if "中午" in t:
        slots.append("noon")
    if "下午" in t:
        slots.append("afternoon")
    if "晚上" in t:
        slots.append("evening")
    if slots:
        result["preferred_slots"] = slots

    # 节前/节后
    anchor = _holiday_anchor(t, today)
    if anchor:
        holiday_key, day = anchor
        if any(k in t for k in ("节后", "假期后", "后")):
            s = _next_workday(day + timedelta(days=1))
            result["time_intent_type"] = "relative"
            result["semantic_label"] = f"{holiday_key}_after"
            result["range_start"] = _workday_start(s)
            result["range_end"] = _workday_end(_add_workdays(s, 5))
            result["confidence"] = 0.92
        elif any(k in t for k in ("节前", "假期前", "放假前", "前")):
            e_day = _prev_workday(day - timedelta(days=1))
            result["time_intent_type"] = "relative"
            result["semantic_label"] = f"{holiday_key}_before"
            result["range_start"] = _workday_start(_next_workday(today))
            result["range_end"] = _workday_end(e_day)
            result["confidence"] = 0.9

    # 周语义
    weekday = today.weekday()
    next_mon = today + timedelta(days=(7 - weekday))
    this_mon = today - timedelta(days=weekday)
    if "下周前半周" in t:
        result["semantic_label"] = "next_week_first_half"
        result["time_intent_type"] = "range"
        result["range_start"] = _workday_start(next_mon)
        result["range_end"] = _workday_end(next_mon + timedelta(days=2))
        result["preferred_days"] = ["周二", "周三"]
        result["confidence"] = 0.9
    elif "下周后半周" in t:
        result["semantic_label"] = "next_week_second_half"
        result["time_intent_type"] = "range"
        result["range_start"] = _workday_start(next_mon + timedelta(days=3))
        result["range_end"] = _workday_end(next_mon + timedelta(days=4))
        result["preferred_days"] = ["周四", "周五"]
        result["confidence"] = 0.9
    elif "这周前半周" in t:
        result["semantic_label"] = "this_week_first_half"
        result["time_intent_type"] = "range"
        start = max(today, this_mon)
        end = this_mon + timedelta(days=2)
        if start > end:
            start = _next_workday(today)
            end = _add_workdays(start, 2)
        result["range_start"] = _workday_start(start)
        result["range_end"] = _workday_end(end)
        result["confidence"] = 0.88
    elif "这周后半周" in t:
        result["semantic_label"] = "this_week_second_half"
        result["time_intent_type"] = "range"
        start = max(today, this_mon + timedelta(days=3))
        end = this_mon + timedelta(days=4)
        if start > end:
            start = _next_workday(today)
            end = _add_workdays(start, 2)
        result["range_start"] = _workday_start(start)
        result["range_end"] = _workday_end(end)
        result["confidence"] = 0.88
    elif "下周内" in t:
        result["semantic_label"] = "next_week"
        result["range_start"] = _workday_start(next_mon)
        result["range_end"] = _workday_end(next_mon + timedelta(days=4))
        result["confidence"] = 0.85
    elif "本周内" in t:
        result["semantic_label"] = "this_week"
        result["range_start"] = _workday_start(_next_workday(today))
        result["range_end"] = _workday_end(this_mon + timedelta(days=4))
        result["confidence"] = 0.83
    elif "周内" in t:
        result["semantic_label"] = "within_week"
        result["range_start"] = _workday_start(_next_workday(today))
        result["range_end"] = _workday_end(this_mon + timedelta(days=4))
        result["confidence"] = 0.8

    # 月语义
    if "下个月月初" in t:
        nm = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
        result["semantic_label"] = "next_month_beginning"
        result["range_start"] = _workday_start(_next_workday(nm))
        result["range_end"] = _workday_end(nm + timedelta(days=6))
        result["confidence"] = 0.9
    elif "下个月月中" in t:
        nm = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
        s = nm.replace(day=10)
        e = nm.replace(day=20)
        result["semantic_label"] = "next_month_middle"
        result["range_start"] = _workday_start(_next_workday(s))
        result["range_end"] = _workday_end(_prev_workday(e))
        result["confidence"] = 0.9
    elif "月底后" in t:
        nm = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
        result["semantic_label"] = "month_end_after"
        result["range_start"] = _workday_start(_next_workday(nm))
        result["range_end"] = _workday_end(_add_workdays(nm, 5))
        result["confidence"] = 0.86
    elif "月底前" in t or "月底" in t:
        month_last = (today.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        start_day = today.replace(day=min(25, month_last.day))
        result["semantic_label"] = "month_end"
        result["range_start"] = _workday_start(_next_workday(start_day))
        result["range_end"] = _workday_end(_prev_workday(month_last))
        result["confidence"] = 0.87
    elif "月初" in t:
        m1 = today.replace(day=1)
        result["semantic_label"] = "month_beginning"
        result["range_start"] = _workday_start(_next_workday(m1))
        result["range_end"] = _workday_end(m1 + timedelta(days=6))
        result["confidence"] = 0.84
    elif "月中" in t:
        s = today.replace(day=10)
        e = today.replace(day=20)
        result["semantic_label"] = "month_middle"
        result["range_start"] = _workday_start(_next_workday(s))
        result["range_end"] = _workday_end(_prev_workday(e))
        result["confidence"] = 0.84

    # 近期语义
    if "这两天" in t:
        s = today if now.hour < 17 else today + timedelta(days=1)
        result["semantic_label"] = "next_two_days"
        result["time_intent_type"] = "relative"
        result["range_start"] = _workday_start(_next_workday(s))
        result["range_end"] = _workday_end(_next_workday(today + timedelta(days=2)))
        result["confidence"] = 0.85
    elif "这几天" in t:
        result["semantic_label"] = "next_five_days"
        result["time_intent_type"] = "relative"
        result["range_start"] = _workday_start(_next_workday(today))
        result["range_end"] = _workday_end(_add_workdays(today, 5))
        result["confidence"] = 0.82
    elif "近期" in t or "最近" in t:
        result["semantic_label"] = "recent"
        result["time_intent_type"] = "relative"
        result["range_start"] = _workday_start(_next_workday(today))
        result["range_end"] = _workday_end(_add_workdays(today, 7))
        result["confidence"] = 0.8
    elif "过几天" in t:
        s = _add_workdays(today, 2)
        result["semantic_label"] = "in_a_few_days"
        result["time_intent_type"] = "relative"
        result["range_start"] = _workday_start(s)
        result["range_end"] = _workday_end(_add_workdays(today, 7))
        result["confidence"] = 0.8

    # 工作日/周末语义
    if "工作日" in t or "上班时间" in t or "工作时间" in t:
        result["preferred_slots"] = ["morning", "afternoon"]
    if "周末" in t:
        sat = today + timedelta(days=(5 - today.weekday()) % 7)
        sun = sat + timedelta(days=1)
        result["semantic_label"] = "weekend"
        result["time_intent_type"] = "range"
        result["range_start"] = sat.replace(hour=10, minute=0, second=0, microsecond=0)
        result["range_end"] = sun.replace(hour=17, minute=0, second=0, microsecond=0)
        result["preferred_slots"] = ["morning", "afternoon"]
        result["confidence"] = max(result["confidence"], 0.82)

    # 合法区间兜底
    if result["range_end"] <= result["range_start"]:
        s = _next_workday(today)
        result["range_start"] = _workday_start(s)
        result["range_end"] = _workday_end(_add_workdays(s, 3))
        result["semantic_label"] = "fallback_window"
        result["confidence"] = min(result["confidence"], 0.6)

    # preferred_days 为空时给出窗口内日名提示
    if not result["preferred_days"]:
        start_d = result["range_start"]
        end_d = result["range_end"]
        cur = _day_start(start_d)
        seen: list[str] = []
        while cur <= end_d and len(seen) < 5:
            if _is_workday(cur):
                seen.append(_WEEKDAY_NAMES[cur.weekday()])
            cur += timedelta(days=1)
        result["preferred_days"] = seen

    return result

