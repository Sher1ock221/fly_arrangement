"""
智能排程服务：分析用户日程空档，给出候选时间建议。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone, time as dtime
from uuid import uuid4
from typing import Any

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.calendar_event import CalendarEvent
from app.models.pending_ai_action import PendingAiAction
from app.services.calendar_service import create_event
from app.services.time_semantic_service import parse_time_semantics
from app.schemas.calendar_event import CalendarEventCreate

logger = logging.getLogger(__name__)

# ── 时区与工作时间配置 ──
CST = timezone(timedelta(hours=8))  # China Standard Time UTC+8
WORK_MORNING = (dtime(9, 0), dtime(12, 0))
WORK_AFTERNOON = (dtime(13, 30), dtime(18, 0))
BUFFER_MINUTES = 15
DEFAULT_DURATION_MINUTES = 60
DEFAULT_MORNING_SLOT = (dtime(9, 30), dtime(11, 0))
DEFAULT_NOON_SLOT = (dtime(12, 0), dtime(13, 0))
DEFAULT_AFTERNOON_SLOT = (dtime(14, 0), dtime(15, 30))
DEFAULT_EVENING_SLOT = (dtime(19, 0), dtime(20, 30))

# ── 时长关键词 ──
DURATION_PATTERNS: list[tuple[re.Pattern, int]] = [
    (re.compile(r"一个半小时"), 90),
    (re.compile(r"1\.5\s*[个小]?时"), 90),
    (re.compile(r"半[个小]?时"), 30),
    (re.compile(r"30\s*分钟"), 30),
    (re.compile(r"45\s*分钟"), 45),
    (re.compile(r"2\s*[个小]?时"), 120),
    (re.compile(r"两[个小]?时"), 120),
    (re.compile(r"1\s*[个小]?时"), 60),
    (re.compile(r"一[个小]?时"), 60),
    (re.compile(r"(\d+)\s*分钟"), 0),
]

# 类型暗示→默认时长
SHORT_KEYWORDS = ["回访", "简短", "快速", "简单", "碰一下"]
LONG_KEYWORDS = ["复盘", "评审", "培训"]
MEETING_90_KEYWORDS = ["交流", "沟通", "会谈", "来访"]
REPORT_60_KEYWORDS = ["汇报"]
RECOMMEND_INTENT_KEYWORDS = ["推荐", "空闲时间", "合适时间", "找个时间", "智能安排", "帮我找"]


def ensure_aware_datetime(dt: datetime, default_tz: timezone = CST) -> datetime:
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=default_tz)
    return dt.astimezone(default_tz)


def parse_duration_minutes(text: str) -> int:
    for pat, mins in DURATION_PATTERNS:
        m = pat.search(text)
        if m:
            if mins == 0:
                return int(m.group(1))
            return mins
    for kw in SHORT_KEYWORDS:
        if kw in text:
            return 30
    for kw in LONG_KEYWORDS:
        if kw in text:
            return 120
    for kw in MEETING_90_KEYWORDS:
        if kw in text:
            return 90
    for kw in REPORT_60_KEYWORDS:
        if kw in text:
            return 60
    return DEFAULT_DURATION_MINUTES


def _contains_recommend_intent(text: str) -> bool:
    return any(k in text for k in RECOMMEND_INTENT_KEYWORDS)


def _weekday_from_text(text: str, now: datetime) -> datetime | None:
    day_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
    today = now.astimezone(CST).replace(hour=0, minute=0, second=0, microsecond=0)
    weekday = today.weekday()

    m = re.search(r"下周([一二三四五六日天])", text)
    if m:
        target_wd = day_map[m.group(1)]
        next_mon = today + timedelta(days=(7 - weekday))
        return next_mon + timedelta(days=target_wd)

    m = re.search(r"(?:本|这)?(?:周|星期)([一二三四五六日天])", text)
    if m:
        target_wd = day_map[m.group(1)]
        d = today + timedelta(days=(target_wd - weekday) % 7)
        return d
    return None


def _date_from_text(text: str, now: datetime) -> datetime | None:
    now = now.astimezone(CST)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if "今晚" in text:
        return today
    if "今天" in text:
        return today
    if "明天" in text:
        return today + timedelta(days=1)
    if "后天" in text:
        return today + timedelta(days=2)

    m = re.search(r"(\d{1,2})月(\d{1,2})日", text)
    if m:
        month = int(m.group(1))
        day = int(m.group(2))
        year = today.year
        try:
            d = datetime(year, month, day, tzinfo=CST)
        except ValueError:
            return None
        if d < today:
            try:
                d = datetime(year + 1, month, day, tzinfo=CST)
            except ValueError:
                return None
        return d

    wd = _weekday_from_text(text, now)
    if wd:
        return wd
    return None


def _explicit_time_point(text: str) -> tuple[dtime, dtime] | None:
    def normalize_hour(raw_hour: int) -> int:
        h = raw_hour
        if any(k in text for k in ("晚上", "今晚", "夜里", "夜间")):
            if 1 <= h <= 11:
                h += 12
        elif any(k in text for k in ("下午", "傍晚")):
            if 1 <= h <= 11:
                h += 12
        elif "中午" in text and h < 11:
            h += 12
        return min(max(h, 0), 23)

    # HH:MM
    m = re.search(r"(\d{1,2})[:：](\d{2})", text)
    if m:
        h = normalize_hour(int(m.group(1)))
        mm = int(m.group(2))
        if 0 <= h <= 23 and 0 <= mm <= 59:
            start = dtime(h, mm)
            m2 = re.search(r"(?:到|至|-|~)\s*(\d{1,2})(?:[:：](\d{2}))?", text)
            if m2:
                eh = int(m2.group(1))
                emm = int(m2.group(2) or "0")
                return start, dtime(eh, emm)
            return start, start

    # X点半 / X点
    m = re.search(r"(\d{1,2})点(半)?", text)
    if m:
        h = normalize_hour(int(m.group(1)))
        mm = 30 if m.group(2) else 0
        if 0 <= h <= 23:
            start = dtime(h, mm)
            m2 = re.search(r"(?:到|至|-|~)\s*(\d{1,2})(?:点|[:：](\d{2}))?", text)
            if m2:
                eh = int(m2.group(1))
                emm = int(m2.group(2) or "0")
                return start, dtime(eh, emm)
            return start, start
    return None


def _extract_candidate_dates(text: str, now: datetime) -> list[datetime]:
    today = now.astimezone(CST).replace(hour=0, minute=0, second=0, microsecond=0)
    candidates: list[datetime] = []
    seen: set[str] = set()

    def push(dt: datetime | None):
        if dt is None:
            return
        key = dt.strftime("%Y-%m-%d")
        if key not in seen:
            seen.add(key)
            candidates.append(dt)

    m = re.search(r"(\d{1,2})号\s*(?:或者|或)\s*(\d{1,2})号", text)
    if m:
        d1, d2 = int(m.group(1)), int(m.group(2))
        for day in (d1, d2):
            try:
                dt = datetime(today.year, today.month, day, tzinfo=CST)
                if dt < today:
                    dt = datetime(today.year + 1, today.month, day, tzinfo=CST)
                push(dt)
            except ValueError:
                continue

    if re.search(r"明天\s*(?:或者|或)\s*后天", text):
        push(today + timedelta(days=1))
        push(today + timedelta(days=2))

    m = re.search(r"(?:这周|本周)?\s*(?:周|星期)([一二三四五六日天])\s*(?:或者|或)\s*(?:周|星期)?([一二三四五六日天])", text)
    if m:
        day_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
        wd_now = today.weekday()
        for g in (m.group(1), m.group(2)):
            target = day_map[g]
            dt = today + timedelta(days=(target - wd_now) % 7)
            push(dt)

    return candidates


def parse_candidate_dates_with_explicit_time(text: str, now: datetime, duration_minutes: int) -> dict[str, Any]:
    date_candidates = _extract_candidate_dates(text, now)
    tp = _explicit_time_point(text)
    if len(date_candidates) < 2 or not tp:
        return {"success": False}
    st_time, ed_time = tp
    start_list: list[datetime] = []
    end_list: list[datetime] = []
    for d in date_candidates:
        st = d.replace(hour=st_time.hour, minute=st_time.minute, second=0, microsecond=0)
        if ed_time != st_time:
            ed = d.replace(hour=ed_time.hour, minute=ed_time.minute, second=0, microsecond=0)
        else:
            ed = st + timedelta(minutes=duration_minutes)
        if ed <= st:
            ed = st + timedelta(minutes=duration_minutes)
        start_list.append(st)
        end_list.append(ed)
    return {
        "success": True,
        "time_semantic_type": "candidate_dates_with_explicit_time",
        "date_candidates": [d.strftime("%Y-%m-%d") for d in date_candidates],
        "time_point": f"{st_time.hour:02d}:{st_time.minute:02d}",
        "start_candidates": start_list,
        "end_candidates": end_list,
    }


def _contains_create_all_candidates_intent(text: str) -> bool:
    return any(
        k in text
        for k in ("两天都安排上", "都安排上", "都排上", "都建上", "都创建", "先都排上", "先都安排")
    )


def _contains_auto_cancel_rule_intent(text: str) -> bool:
    return any(k in text for k in ("自动取消", "完成后取消", "确认完成", "互斥"))


def parse_explicit_schedule_slot(
    text: str,
    now: datetime,
    duration_minutes: int,
) -> dict[str, Any]:
    """
    尝试解析“可直接创建”的明确时间表达。
    返回 {"success": bool, "start": datetime|None, "end": datetime|None, "reason": str, "confidence": float}
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=CST)
    else:
        now = now.astimezone(CST)

    d = _date_from_text(text, now)
    if d is None:
        return {"success": False, "start": None, "end": None, "reason": "missing explicit date", "confidence": 0.0}

    tp = _explicit_time_point(text)
    if tp:
        st_time, ed_time = tp
        start = d.replace(hour=st_time.hour, minute=st_time.minute, second=0, microsecond=0)
        if ed_time != st_time:
            end = d.replace(hour=ed_time.hour, minute=ed_time.minute, second=0, microsecond=0)
        else:
            end = start + timedelta(minutes=duration_minutes)
        if end <= start:
            end = start + timedelta(minutes=duration_minutes)
        return {"success": True, "start": start, "end": end, "reason": "explicit time point", "confidence": 0.95}

    if "上午" in text:
        st, ed = DEFAULT_MORNING_SLOT
    elif "中午" in text:
        st, ed = DEFAULT_NOON_SLOT
    elif "下午" in text:
        st, ed = DEFAULT_AFTERNOON_SLOT
    elif "晚上" in text:
        st, ed = DEFAULT_EVENING_SLOT
    else:
        return {"success": False, "start": None, "end": None, "reason": "missing explicit period", "confidence": 0.0}

    start = d.replace(hour=st.hour, minute=st.minute, second=0, microsecond=0)
    end = d.replace(hour=ed.hour, minute=ed.minute, second=0, microsecond=0)
    # 若用户显式给了时长，优先用时长覆盖默认时段长度
    if duration_minutes > 0:
        end = start + timedelta(minutes=duration_minutes)
    return {"success": True, "start": start, "end": end, "reason": "explicit day period", "confidence": 0.85}


def has_slot_conflict(
    busy: list[tuple[datetime, datetime]],
    start: datetime,
    end: datetime,
    buffer_minutes: int = BUFFER_MINUTES,
) -> bool:
    start = ensure_aware_datetime(start, CST)
    end = ensure_aware_datetime(end, CST)
    buf = timedelta(minutes=buffer_minutes)
    for bs, be in busy:
        bs = ensure_aware_datetime(bs, CST)
        be = ensure_aware_datetime(be, CST)
        if start < be + buf and end > bs - buf:
            return True
    return False


def parse_date_range(text: str, now: datetime) -> tuple[datetime, datetime]:
    """Parse natural language date range from text. Returns (start, end) in CST."""
    semantic = parse_time_semantics(text, now)
    range_start = semantic.get("range_start")
    range_end = semantic.get("range_end")
    if isinstance(range_start, datetime) and isinstance(range_end, datetime):
        return range_start, range_end
    if now.tzinfo is None:
        now = now.replace(tzinfo=CST)
    else:
        now = now.astimezone(CST)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    weekday = today.weekday()  # 0=Monday

    if "明天" in text:
        d = today + timedelta(days=1)
        return d, d + timedelta(days=1)

    if "后天" in text:
        d = today + timedelta(days=2)
        return d, d + timedelta(days=1)

    if "今天" in text:
        return today, today + timedelta(days=1)

    if "这两天" in text:
        return today, today + timedelta(days=2)

    day_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}

    # 下周X（具体日）必须在"下周"之前匹配
    m = re.search(r"下周([一二三四五六日天])", text)
    if m:
        target_wd = day_map.get(m.group(1), 0)
        next_mon = today + timedelta(days=(7 - weekday))
        d = next_mon + timedelta(days=target_wd)
        return d, d + timedelta(days=1)

    if "下周" in text:
        next_mon = today + timedelta(days=(7 - weekday))
        return next_mon, next_mon + timedelta(days=5)

    # 本周X / 这周X / 周X（具体日）
    m = re.search(r"(?:本|这)?周([一二三四五六日天])", text)
    if m:
        target_wd = day_map.get(m.group(1), 0)
        d = today + timedelta(days=(target_wd - weekday) % 7)
        if d < today:
            d += timedelta(days=7)
        return d, d + timedelta(days=1)

    # 本周/这周（剩余工作日）
    if "本周" in text or "这周" in text:
        this_mon = today - timedelta(days=weekday)
        this_sat = this_mon + timedelta(days=5)
        start = max(today, this_mon)
        return start, this_sat

    # Default: this week and next week (10 working days)
    return today, today + timedelta(days=10)


async def get_busy_slots(
    db: AsyncSession, owner_user_id: int, start: datetime, end: datetime,
) -> list[tuple[datetime, datetime]]:
    """Fetch existing events for the user in [start, end)."""
    start = ensure_aware_datetime(start, CST)
    end = ensure_aware_datetime(end, CST)
    from app.services.collaboration_service import calendar_event_visible_filter
    stmt = (
        select(CalendarEvent)
        .where(
            calendar_event_visible_filter(owner_user_id),
            CalendarEvent.end_time > start,
            CalendarEvent.start_time < end,
        )
        .order_by(CalendarEvent.start_time)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        (ensure_aware_datetime(r.start_time, CST), ensure_aware_datetime(r.end_time, CST))
        for r in rows
        if r.start_time is not None and r.end_time is not None
    ]


def _work_windows_for_date(d: datetime) -> list[tuple[datetime, datetime]]:
    """Return work time windows for a given date in CST."""
    base = d.replace(hour=0, minute=0, second=0, microsecond=0)
    if base.tzinfo is None:
        base = base.replace(tzinfo=CST)
    if base.weekday() >= 5:
        return []
    return [
        (base.replace(hour=WORK_MORNING[0].hour, minute=WORK_MORNING[0].minute),
         base.replace(hour=WORK_MORNING[1].hour, minute=WORK_MORNING[1].minute)),
        (base.replace(hour=WORK_AFTERNOON[0].hour, minute=WORK_AFTERNOON[0].minute),
         base.replace(hour=WORK_AFTERNOON[1].hour, minute=WORK_AFTERNOON[1].minute)),
    ]


def find_free_slots(
    busy: list[tuple[datetime, datetime]],
    range_start: datetime,
    range_end: datetime,
    duration_minutes: int,
    max_results: int = 3,
    buffer_minutes: int = BUFFER_MINUTES,
) -> list[tuple[datetime, datetime]]:
    """Find free time slots within work hours, avoiding busy slots with buffer."""
    needed = timedelta(minutes=duration_minutes)
    buf = timedelta(minutes=buffer_minutes)
    results: list[tuple[datetime, datetime]] = []

    current = range_start
    while current.date() < range_end.date() and len(results) < max_results:
        windows = _work_windows_for_date(current)
        for win_start, win_end in windows:
            if win_end <= range_start:
                continue
            if win_start >= range_end:
                break
            effective_start = max(win_start, range_start)
            effective_end = min(win_end, range_end)

            cursor = effective_start
            while cursor + needed <= effective_end and len(results) < max_results:
                slot_start = cursor
                slot_end = cursor + needed

                conflict = False
                for bs, be in busy:
                    if slot_start < be + buf and slot_end > bs - buf:
                        conflict = True
                        cursor = be + buf
                        break

                if not conflict:
                    results.append((slot_start, slot_end))
                    cursor = slot_end + buf
                    break  # one slot per work window to spread across days

        current = current + timedelta(days=1)
        current = current.replace(hour=0, minute=0, second=0, microsecond=0)

    return results


def _fallback_single_day_slot(
    busy: list[tuple[datetime, datetime]],
    day_start: datetime,
    duration_minutes: int,
    preferred_slots: list[str] | None = None,
) -> tuple[datetime, datetime] | None:
    base = ensure_aware_datetime(day_start, CST).replace(hour=0, minute=0, second=0, microsecond=0)
    slot_pref = preferred_slots or []
    if "evening" in slot_pref:
        candidate = base.replace(hour=19, minute=0)
    elif "afternoon" in slot_pref:
        candidate = base.replace(hour=14, minute=0)
    elif "morning" in slot_pref:
        candidate = base.replace(hour=9, minute=0)
    else:
        candidate = base.replace(hour=9, minute=0)

    end_limit = base.replace(hour=22, minute=0)
    step = timedelta(minutes=30)
    duration_delta = timedelta(minutes=max(1, duration_minutes))
    while candidate + duration_delta <= end_limit:
        candidate_end = candidate + duration_delta
        if not has_slot_conflict(busy, candidate, candidate_end):
            return candidate, candidate_end
        candidate += step
    return None


def format_slot(start: datetime, end: datetime) -> str:
    if start.tzinfo is not None:
        start = start.astimezone(CST)
    if end.tzinfo is not None:
        end = end.astimezone(CST)
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    wd = weekday_names[start.weekday()]
    date_str = start.strftime("%m月%d日")
    start_time = start.strftime("%H:%M")
    end_time = end.strftime("%H:%M")
    return f"{date_str}（{wd}）{start_time}–{end_time}"


def build_suggestion_message(
    slots: list[tuple[datetime, datetime]],
    title: str,
    duration_minutes: int,
) -> str:
    if not slots:
        return f"抱歉，在你指定的时间范围内没有找到合适的空闲时段来安排「{title}」。你可以尝试放宽时间范围，例如看看下周的安排？"

    lines = [f"我分析了你现有的日程安排，为「{title}」（约 {duration_minutes} 分钟）找到了以下候选时间：\n"]

    for i, (s, e) in enumerate(slots):
        label = "✦ 首选" if i == 0 else f"  备选{i}"
        lines.append(f"{label}：{format_slot(s, e)}")

    lines.append(f"\n建议安排在 **{format_slot(*slots[0])}**，这个时段前后比较宽松。")
    lines.append("你觉得合适吗？回复「可以」确认，或「换一个时间」重新建议。")
    return "\n".join(lines)


async def save_candidate_schedule_context(
    db: AsyncSession,
    *,
    actor_user_id: int,
    title: str,
    candidate_dates: list[str],
    time_point: str,
    duration_minutes: int,
    event_type: str,
    original_text: str,
) -> None:
    old = (
        await db.execute(
            select(PendingAiAction).where(
                PendingAiAction.actor_user_id == actor_user_id,
                PendingAiAction.action_type == "candidate_schedule_context",
                PendingAiAction.status == "pending",
            )
        )
    ).scalars().all()
    for o in old:
        o.status = "cancelled"
    row = PendingAiAction(
        actor_user_id=actor_user_id,
        resource_type="calendar_event",
        resource_id=0,
        action_type="candidate_schedule_context",
        target_user_id=None,
        payload_json={
            "title": title,
            "candidate_dates": candidate_dates,
            "time_point": time_point,
            "duration_minutes": duration_minutes,
            "event_type": event_type,
            "original_text": original_text,
        },
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=12),
    )
    db.add(row)
    await db.flush()


async def _load_latest_candidate_context(db: AsyncSession, actor_user_id: int) -> dict[str, Any] | None:
    row = (
        await db.execute(
            select(PendingAiAction).where(
                PendingAiAction.actor_user_id == actor_user_id,
                PendingAiAction.action_type == "candidate_schedule_context",
                PendingAiAction.status == "pending",
            ).order_by(PendingAiAction.id.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return row.payload_json or None


async def execute_candidate_schedule_strategy(
    db: AsyncSession,
    *,
    actor_user_id: int,
    base_event_id: int | None,
    candidate_dates: list[str] | None,
    time_point: str | None,
    title: str | None,
    strategy: str = "create_all_candidates",
    auto_cancel_others_on_complete: bool = False,
    event_type: str = "meeting",
    original_text: str | None = None,
) -> dict[str, Any]:
    if strategy != "create_all_candidates":
        return {"success": False, "message": f"不支持的候选策略: {strategy}", "execution_summary": "候选策略不支持"}

    ctx = await _load_latest_candidate_context(db, actor_user_id)
    title = (title or (ctx or {}).get("title") or "").strip()
    candidate_dates = candidate_dates or (ctx or {}).get("candidate_dates") or []
    time_point = (time_point or (ctx or {}).get("time_point") or "").strip()
    event_type = event_type or (ctx or {}).get("event_type") or "meeting"
    duration_minutes = parse_duration_minutes(original_text or (ctx or {}).get("original_text") or "")
    if duration_minutes <= 0:
        duration_minutes = DEFAULT_DURATION_MINUTES

    if not title:
        return {"success": False, "message": "缺少标题，无法创建候选日程", "execution_summary": "候选创建失败：缺少标题"}
    if len(candidate_dates) < 2:
        return {"success": False, "message": "缺少候选日期，无法创建候选日程", "execution_summary": "候选创建失败：缺少日期"}
    if not time_point or ":" not in time_point:
        return {"success": False, "message": "缺少明确时间点，无法创建候选日程", "execution_summary": "候选创建失败：缺少时间点"}

    hh, mm = time_point.split(":", 1)
    sh = min(max(int(hh), 0), 23)
    sm = min(max(int(mm), 0), 59)
    group_id = f"cand_{uuid4().hex[:12]}"
    created_ids: list[int] = []
    created_labels: list[str] = []
    for ds in candidate_dates:
        d = datetime.fromisoformat(ds)
        if d.tzinfo is None:
            d = d.replace(tzinfo=CST)
        st = d.replace(hour=sh, minute=sm, second=0, microsecond=0)
        ed = st + timedelta(minutes=duration_minutes)
        body = CalendarEventCreate(
            title=title,
            description=(f"[候选日程组:{group_id}] " + (original_text or "")).strip() or None,
            start_time=st,
            end_time=ed,
            type=event_type,
            status="scheduled",
            candidate_group_id=group_id,
            candidate_policy="mutually_exclusive" if auto_cancel_others_on_complete else "candidate",
            auto_cancel_others_on_complete=auto_cancel_others_on_complete,
        )
        event = await create_event(db, body, owner_user_id=actor_user_id)
        created_ids.append(event.id)
        created_labels.append(format_slot(st, ed))

    return {
        "success": True,
        "message": (
            "已为您创建候选日程：\n"
            + "\n".join([f"{i+1}. {label}" for i, label in enumerate(created_labels)])
            + (
                "\n并已设置互斥规则：任一候选日程确认完成后，将自动取消同组其他未来候选日程。"
                if auto_cancel_others_on_complete
                else ""
            )
        ),
        "result": {
            "created_event_ids": created_ids,
            "candidate_group_id": group_id,
            "applied_rules": {
                "strategy": strategy,
                "auto_cancel_others_on_complete": auto_cancel_others_on_complete,
            },
        },
        "execution_summary": f"已创建 {len(created_ids)} 条候选日程，时间点 {time_point}",
    }


async def auto_schedule_event(
    db: AsyncSession,
    actor_user_id: int,
    text: str,
    title: str,
    now: datetime | None = None,
    event_type: str = "meeting",
) -> dict[str, Any]:
    """默认自动安排：自动找空档、自动避让冲突、直接创建。"""
    if now is None:
        now = datetime.now(CST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=CST)
    else:
        now = now.astimezone(CST)

    duration = parse_duration_minutes(text)
    candidate_semantic = parse_candidate_dates_with_explicit_time(text, now, duration)
    if candidate_semantic.get("success"):
        if _contains_create_all_candidates_intent(text):
            return await execute_candidate_schedule_strategy(
                db,
                actor_user_id=actor_user_id,
                base_event_id=None,
                candidate_dates=candidate_semantic.get("date_candidates") or [],
                time_point=str(candidate_semantic.get("time_point") or ""),
                title=title,
                strategy="create_all_candidates",
                auto_cancel_others_on_complete=_contains_auto_cancel_rule_intent(text),
                event_type=event_type,
                original_text=text,
            )
        await save_candidate_schedule_context(
            db,
            actor_user_id=actor_user_id,
            title=title,
            candidate_dates=candidate_semantic.get("date_candidates") or [],
            time_point=str(candidate_semantic.get("time_point") or ""),
            duration_minutes=duration,
            event_type=event_type,
            original_text=text,
        )
        return {
            "success": True,
            "message": (
                f"已识别为候选日期 + 明确时间："
                f"{'、'.join(candidate_semantic.get('date_candidates') or [])} {candidate_semantic.get('time_point')}。"
                "如需我两天都安排上，请回复「两天都安排上」。"
            ),
            "result": {
                "time_semantic_type": "candidate_dates_with_explicit_time",
                "date_candidates": candidate_semantic.get("date_candidates") or [],
                "time_point": candidate_semantic.get("time_point"),
            },
            "execution_summary": "已识别候选日期时间语义，等待是否批量创建候选日程",
        }

    semantic = parse_time_semantics(text, now)
    range_start = semantic.get("range_start") or now
    range_end = semantic.get("range_end") or (now + timedelta(days=10))
    range_start = ensure_aware_datetime(range_start, CST)
    range_end = ensure_aware_datetime(range_end, CST)
    urgency_level = str(semantic.get("urgency_level") or "normal")
    semantic_label = str(semantic.get("semantic_label") or "")
    target_date = range_start.date().isoformat() if isinstance(range_start, datetime) else ""
    logger.info(
        "auto_schedule_event semantic text=%r cst_today=%s target_date=%s range_start=%s range_end=%s label=%s",
        text,
        now.date().isoformat(),
        target_date,
        range_start.isoformat(),
        range_end.isoformat(),
        semantic_label,
    )
    explicit = parse_explicit_schedule_slot(text, now, duration)

    final_start: datetime | None = None
    final_end: datetime | None = None
    was_adjusted = False
    adjustment_reason = ""
    attempted_range = f"{range_start.strftime('%m月%d日')} - {range_end.strftime('%m月%d日')}"
    if urgency_level == "high" and not explicit.get("success"):
        range_end = min(range_end, range_start + timedelta(days=5))

    if explicit.get("success"):
        preferred_start: datetime = explicit["start"]
        preferred_end: datetime = explicit["end"]
        day_start = preferred_start.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        day_busy = await get_busy_slots(db, actor_user_id, day_start, day_end)
        if not has_slot_conflict(day_busy, preferred_start, preferred_end):
            final_start, final_end = preferred_start, preferred_end
        else:
            was_adjusted = True
            adjustment_reason = "原优先时段存在冲突，已自动调整到最近可用时间"
            nearby_end = day_end + timedelta(days=3)
            nearby_busy = await get_busy_slots(db, actor_user_id, day_start, nearby_end)
            nearby_slots = find_free_slots(nearby_busy, day_start, nearby_end, duration, max_results=1)
            if nearby_slots:
                final_start, final_end = nearby_slots[0]
            else:
                # 明确时间冲突且附近无空档，回到范围搜索
                range_start, range_end = day_start, nearby_end

    if final_start is None or final_end is None:
        if range_start < now:
            range_start = now
        busy = await get_busy_slots(db, actor_user_id, range_start, range_end)
        slots = find_free_slots(busy, range_start, range_end, duration, max_results=1)
        if not slots:
            # 对“今天/明天/后天/下周X”等单日语义，先尝试在该目标日期内回落创建，避免静默跳到其他日期。
            single_day_semantics = {"today", "tomorrow", "day_after_tomorrow", "today_morning", "today_afternoon", "today_evening", "tomorrow_morning", "tomorrow_afternoon", "tomorrow_evening"}
            is_next_weekday_day = semantic_label.startswith("next_weekday_")
            if (semantic_label in single_day_semantics or is_next_weekday_day or range_start.date() == range_end.date()):
                fallback_busy = await get_busy_slots(db, actor_user_id, range_start, range_end + timedelta(days=1))
                fallback_slot = _fallback_single_day_slot(
                    fallback_busy,
                    range_start,
                    duration,
                    preferred_slots=semantic.get("preferred_slots") if isinstance(semantic, dict) else None,
                )
                if fallback_slot is not None:
                    final_start, final_end = fallback_slot
                    was_adjusted = True
                    adjustment_reason = "目标日期工作时段无空档，已在目标日期内回落可用时间"
                    logger.info(
                        "auto_schedule_event single-day fallback text=%r target_date=%s fallback_start=%s fallback_end=%s",
                        text,
                        range_start.date().isoformat(),
                        final_start.isoformat(),
                        final_end.isoformat(),
                    )
            if final_start is not None and final_end is not None:
                slots = [(final_start, final_end)]
            else:
                extended_end = range_end + timedelta(days=7)
                extended_busy = await get_busy_slots(db, actor_user_id, range_start, extended_end)
                extended_slots = find_free_slots(extended_busy, range_start, extended_end, duration, max_results=1)
                if not extended_slots:
                    return {
                        "success": False,
                        "message": f"当前无法为「{title}」安排日程：我已尝试在 {attempted_range} 及顺延 7 天范围内查找 {duration} 分钟空档，但没有可用时段。",
                        "execution_summary": f"自动安排失败：{attempted_range} 无可用空档",
                    }
                slots = extended_slots
                was_adjusted = True
                if not adjustment_reason:
                    adjustment_reason = "原范围无空档，已自动顺延搜索范围"
        final_start, final_end = slots[0]

    body = CalendarEventCreate(
        title=title,
        description=None,
        start_time=final_start,
        end_time=final_end,
        type=event_type,
    )
    event = await create_event(db, body, owner_user_id=actor_user_id)
    logger.info(
        "auto_schedule_event finalized text=%r final_start=%s final_end=%s was_adjusted=%s",
        text,
        final_start.isoformat(),
        final_end.isoformat(),
        was_adjusted,
    )
    base_msg = f"已为您安排日程：{format_slot(final_start, final_end)}，主题为「{title}」。"
    if was_adjusted:
        base_msg = f"{base_msg} 由于原优先时段存在冲突或范围不足，我已自动调整到最近可用时间。"

    return {
        "success": True,
        "message": base_msg,
        "result": {
            "event_id": event.id,
            "title": event.title,
            "final_start": final_start.isoformat(),
            "final_end": final_end.isoformat(),
            "was_adjusted": was_adjusted,
            "adjustment_reason": adjustment_reason or None,
            "semantic_label": semantic_label,
            "urgency_level": urgency_level,
        },
        "execution_summary": f"已自动安排日程：{format_slot(final_start, final_end)}",
    }


# ── Pending Action 管理 ──

async def create_pending_schedule(
    db: AsyncSession,
    actor_user_id: int,
    title: str,
    description: str | None,
    suggested_start: datetime,
    suggested_end: datetime,
    alternative_slots: list[dict[str, str]] | None = None,
    source_channel: str = "web",
    event_type: str = "event",
    original_text: str | None = None,
) -> PendingAiAction:
    """Create a pending schedule suggestion for user confirmation."""
    old = (
        await db.execute(
            select(PendingAiAction).where(
                PendingAiAction.actor_user_id == actor_user_id,
                PendingAiAction.action_type == "schedule_suggestion",
                PendingAiAction.status == "pending",
            )
        )
    ).scalars().all()
    for o in old:
        o.status = "cancelled"
    await db.flush()

    payload = {
        "title": title,
        "description": description,
        "suggested_start_time": suggested_start.isoformat(),
        "suggested_end_time": suggested_end.isoformat(),
        "alternative_slots": alternative_slots or [],
        "source_channel": source_channel,
        "event_type": event_type,
        "original_text": original_text or "",
    }

    row = PendingAiAction(
        actor_user_id=actor_user_id,
        resource_type="calendar_event",
        resource_id=0,
        action_type="schedule_suggestion",
        target_user_id=None,
        payload_json=payload,
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    logger.info("schedule: pending suggestion created id=%s actor=%s title=%s", row.id, actor_user_id, title)
    return row


async def _expire_stale_pending(db: AsyncSession, actor_user_id: int) -> int:
    """Mark overdue pending schedule_suggestions as expired. Returns count updated."""
    now = datetime.now(timezone.utc)
    stale = (
        await db.execute(
            select(PendingAiAction).where(
                PendingAiAction.actor_user_id == actor_user_id,
                PendingAiAction.action_type == "schedule_suggestion",
                PendingAiAction.status == "pending",
                PendingAiAction.expires_at <= now,
            )
        )
    ).scalars().all()
    for s in stale:
        s.status = "expired"
    if stale:
        await db.flush()
        logger.info("schedule: marked %d expired pending(s) for actor=%s", len(stale), actor_user_id)
    return len(stale)


async def get_latest_pending_schedule(db: AsyncSession, actor_user_id: int) -> PendingAiAction | None:
    await _expire_stale_pending(db, actor_user_id)
    row = (
        await db.execute(
            select(PendingAiAction).where(
                PendingAiAction.actor_user_id == actor_user_id,
                PendingAiAction.action_type == "schedule_suggestion",
                PendingAiAction.status == "pending",
                PendingAiAction.expires_at > datetime.now(timezone.utc),
            ).order_by(PendingAiAction.id.desc()).limit(1)
        )
    ).scalar_one_or_none()
    return row


async def confirm_pending_schedule(db: AsyncSession, actor_user_id: int) -> dict[str, Any]:
    """Confirm the latest pending schedule suggestion and create the calendar event."""
    from app.services.audit_log_service import write_audit_log

    pending = await get_latest_pending_schedule(db, actor_user_id)
    if not pending:
        return {"success": False, "message": "没有待确认的日程安排建议，或建议已过期。需要我重新帮你找时间吗？"}

    payload = pending.payload_json or {}
    title = payload.get("title", "未命名日程")
    description = payload.get("description")
    start_str = payload.get("suggested_start_time")
    end_str = payload.get("suggested_end_time")
    event_type = payload.get("event_type", "event")

    if not start_str or not end_str:
        return {"success": False, "message": "建议数据不完整，请重新安排"}

    start_time = datetime.fromisoformat(start_str)
    end_time = datetime.fromisoformat(end_str)

    body = CalendarEventCreate(
        title=title,
        description=description,
        start_time=start_time,
        end_time=end_time,
        type=event_type,
    )
    event = await create_event(db, body, owner_user_id=actor_user_id)

    pending.status = "confirmed"
    pending.confirmed_at = datetime.now(timezone.utc)
    pending.resource_id = event.id
    await db.flush()

    await write_audit_log(
        db,
        action="ai_schedule_suggestion_confirmed",
        actor_user_id=actor_user_id,
        target_type="calendar_event",
        target_id=str(event.id),
        detail=f"confirmed schedule: {title}",
    )
    await write_audit_log(
        db,
        action="ai_schedule_event_created",
        actor_user_id=actor_user_id,
        target_type="calendar_event",
        target_id=str(event.id),
        detail=f"created event: {title} at {start_str}",
    )

    logger.info("schedule: suggestion confirmed id=%s event_id=%s actor=%s", pending.id, event.id, actor_user_id)

    return {
        "success": True,
        "message": f"已为你安排「{title}」在 {format_slot(start_time, end_time)}。你可以在日历中查看。",
        "result": {"event_id": event.id},
        "execution_summary": f"已创建日程「{title}」",
    }


async def cancel_pending_schedule(db: AsyncSession, actor_user_id: int) -> dict[str, Any]:
    from app.services.audit_log_service import write_audit_log

    pending = await get_latest_pending_schedule(db, actor_user_id)
    if not pending:
        return {"success": True, "message": "没有待确认的日程安排建议。"}

    pending.status = "cancelled"
    await db.flush()

    await write_audit_log(
        db,
        action="ai_schedule_suggestion_cancelled",
        actor_user_id=actor_user_id,
        target_type="pending_ai_action",
        target_id=str(pending.id),
        detail="cancelled schedule suggestion",
    )
    logger.info("schedule: suggestion cancelled id=%s actor=%s", pending.id, actor_user_id)
    return {"success": True, "message": "好的，已取消本次日程安排。需要我重新帮你找时间吗？"}


async def suggest_schedule(
    db: AsyncSession,
    actor_user_id: int,
    text: str,
    title: str,
    now: datetime | None = None,
    source_channel: str = "web",
    event_type: str = "meeting",
) -> dict[str, Any]:
    """建议模式：仅在用户明确要求推荐多个时间时使用。"""
    from app.services.audit_log_service import write_audit_log

    if now is None:
        now = datetime.now(CST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=CST)

    duration = parse_duration_minutes(text)
    if not _contains_recommend_intent(text):
        return await auto_schedule_event(
            db,
            actor_user_id=actor_user_id,
            text=text,
            title=title,
            now=now,
            event_type=event_type,
        )
    range_start, range_end = parse_date_range(text, now)

    # 模式 A：用户明确给出时间表达，优先尝试直接创建
    explicit = parse_explicit_schedule_slot(text, now, duration)
    if explicit.get("success") and not _contains_recommend_intent(text):
        explicit_start: datetime = explicit["start"]
        explicit_end: datetime = explicit["end"]
        day_start = explicit_start.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        day_busy = await get_busy_slots(db, actor_user_id, day_start, day_end)
        if not has_slot_conflict(day_busy, explicit_start, explicit_end):
            body = CalendarEventCreate(
                title=title,
                description=None,
                start_time=explicit_start,
                end_time=explicit_end,
                type=event_type,
            )
            event = await create_event(db, body, owner_user_id=actor_user_id)
            return {
                "success": True,
                "message": f"已为您创建日程：{format_slot(explicit_start, explicit_end)}，主题为「{title}」。",
                "result": {
                    "event_id": event.id,
                    "title": event.title,
                    "start_time": explicit_start.isoformat(),
                    "end_time": explicit_end.isoformat(),
                },
                "execution_summary": f"已直接创建日程：{format_slot(explicit_start, explicit_end)}",
            }
        # 明确时间但冲突：自动转建议模式
        range_start = day_start
        range_end = day_end + timedelta(days=3)

    # Ensure range_start is not in the past
    if range_start < now:
        range_start = now

    busy = await get_busy_slots(db, actor_user_id, range_start, range_end)
    slots = find_free_slots(busy, range_start, range_end, duration)

    if not slots:
        logger.info("schedule: no free slot found for user=%s range=%s-%s", actor_user_id, range_start, range_end)
        extended_end = range_end + timedelta(days=7)
        extended_busy = await get_busy_slots(db, actor_user_id, range_start, extended_end)
        extended_slots = find_free_slots(extended_busy, range_start, extended_end, duration)
        if extended_slots:
            msg = build_suggestion_message(extended_slots, title, duration)
            msg = f"你指定的时间范围内已排满，我帮你往后延了一些看看：\n\n{msg}"
        else:
            msg = f"抱歉，近两周内没有找到合适的 {duration} 分钟空档来安排「{title}」。建议你手动查看日历，看看是否有可调整的日程。"
            return {"success": True, "message": msg, "slots": []}
        slots = extended_slots

    alt = [
        {"start": s.isoformat(), "end": e.isoformat(), "label": format_slot(s, e)}
        for s, e in slots[1:]
    ]

    pending = await create_pending_schedule(
        db,
        actor_user_id=actor_user_id,
        title=title,
        description=None,
        suggested_start=slots[0][0],
        suggested_end=slots[0][1],
        alternative_slots=alt,
        source_channel=source_channel,
        event_type=event_type,
        original_text=text,
    )

    await write_audit_log(
        db,
        action="ai_schedule_suggestion_created",
        actor_user_id=actor_user_id,
        target_type="pending_ai_action",
        target_id=str(pending.id),
        detail=f"schedule suggestion for: {title}",
    )

    msg = build_suggestion_message(slots, title, duration)
    if explicit.get("success"):
        msg = f"您指定的时间存在冲突，已为您推荐可用备选时段：\n\n{msg}"
    return {
        "success": True,
        "message": msg,
        "pending_action_id": pending.id,
        "slots": [{"start": s.isoformat(), "end": e.isoformat(), "label": format_slot(s, e)} for s, e in slots],
        "execution_summary": f"已为「{title}」生成候选时间建议：{format_slot(slots[0][0], slots[0][1])}",
    }
