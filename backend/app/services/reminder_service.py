"""
提醒任务：创建、列表、取消、更新；定时触发。
channel=local 时仅本地记账；feishu_private 为服务端部署保留（桌面 SQLite 会将旧数据降级为 local）。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.url import get_database_url, is_sqlite_url, normalize_database_url
from app.models import CalendarEvent, ReminderLog, ReminderTask
from app.services.feishu_bot import send_text_message
from app.services.feishu_identity_service import list_bound_identities_for_user
from app.services.time_semantic_service import resolve_reminder_oneshot_trigger_datetime

logger = logging.getLogger(__name__)
CST = ZoneInfo("Asia/Shanghai")


def _try_parse_day_after_afternoon_clock(title: str, now_utc: datetime) -> datetime | None:
    """解析「后天下午N点…」（含中文「三点」）；与 time_semantic 内「后天中午」互补，避免改 time_semantic_service。"""
    t = (title or "").strip()
    if "后天" not in t or "下午" not in t:
        return None
    m = re.search(r"下午\s*(三|四|五|六|七|八|九|十|两|二|一|[0-2]?\d)\s*(?:点|點)", t)
    if not m:
        return None
    g = m.group(1)
    cn12 = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    if g.isdigit():
        clock12 = int(g)
    else:
        clock12 = cn12.get(g)
        if clock12 is None:
            return None
    if not (1 <= clock12 <= 12):
        return None
    hour24 = 12 if clock12 == 12 else clock12 + 12
    now_cst = now_utc.astimezone(CST) if now_utc.tzinfo else now_utc.replace(tzinfo=timezone.utc).astimezone(CST)
    day_start = now_cst.replace(hour=0, minute=0, second=0, microsecond=0)
    day_after = day_start + timedelta(days=2)
    return day_after.replace(hour=min(hour24, 23), minute=0, second=0, microsecond=0)


def _title_for_reminder_time_parse(
    title: str,
    *,
    reminder_type: str,
    trigger_at: str | None,
) -> str:
    """
    单次提醒且未传 trigger_at 时，time_semantic 需「明天上午/明天下午/明天N点」等锚点；
    用户常说「明天提醒我…」——在不改 time_semantic_service 的前提下补全为「明天上午提醒…」。
    """
    if reminder_type != "one_time" or (trigger_at or "").strip():
        return title
    t0 = (title or "").strip()
    if t0.startswith("明天提醒") and "明天上午" not in t0 and "明天下午" not in t0 and not re.search(
        r"明天\s*\d{1,2}\s*(?:点|點)", t0
    ):
        return "明天上午" + t0[len("明天") :]
    return title


def parse_iso_datetime(s: str | None) -> datetime | None:
    if not s or not isinstance(s, str) or not s.strip():
        return None
    s = s.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _weekday_iso(monday_is_zero: int) -> int:
    return monday_is_zero + 1


def first_recurring_next(
    now_utc: datetime,
    rule: dict[str, Any],
    end_at_utc: datetime | None,
) -> datetime | None:
    trigger_time = str(rule.get("trigger_time") or "09:00")
    parts = trigger_time.split(":")
    h = int(parts[0])
    mi = int(parts[1]) if len(parts) > 1 else 0
    by_weekdays = rule.get("by_weekdays")
    if by_weekdays is not None and not isinstance(by_weekdays, list):
        by_weekdays = None
    now_local = now_utc.astimezone(CST)
    cur = now_local.replace(hour=h, minute=mi, second=0, microsecond=0)
    if cur <= now_local:
        cur = cur + timedelta(days=1)
    for _ in range(370):
        na = cur.astimezone(timezone.utc)
        if end_at_utc and na > end_at_utc:
            return None
        iso_d = _weekday_iso(cur.weekday())
        if not by_weekdays or iso_d in by_weekdays:
            return na
        cur = cur + timedelta(days=1)
    return None


def next_recurring_after_fire(
    fire_utc: datetime,
    rule: dict[str, Any],
    end_at_utc: datetime | None,
) -> datetime | None:
    trigger_time = str(rule.get("trigger_time") or "09:00")
    parts = trigger_time.split(":")
    h = int(parts[0])
    mi = int(parts[1]) if len(parts) > 1 else 0
    by_weekdays = rule.get("by_weekdays")
    if by_weekdays is not None and not isinstance(by_weekdays, list):
        by_weekdays = None
    base_local = fire_utc.astimezone(CST)
    cur = (base_local + timedelta(days=1)).replace(hour=h, minute=mi, second=0, microsecond=0)
    for _ in range(370):
        na = cur.astimezone(timezone.utc)
        if end_at_utc and na > end_at_utc:
            return None
        iso_d = _weekday_iso(cur.weekday())
        if not by_weekdays or iso_d in by_weekdays:
            return na
        cur = cur + timedelta(days=1)
    return None


async def get_calendar_event_for_owner(
    db: AsyncSession,
    event_id: int,
    owner_user_id: int,
) -> CalendarEvent | None:
    ev = await db.get(CalendarEvent, event_id)
    if ev is None or ev.owner_user_id != owner_user_id:
        return None
    return ev


async def resolve_feishu_for_user(db: AsyncSession, user_id: int) -> tuple[str | None, str | None]:
    rows = await list_bound_identities_for_user(db, user_id)
    for r in rows:
        if r.open_id:
            return r.open_id.strip(), (r.tenant_key or None)
    return None, None


async def build_reminder_feishu_text(db: AsyncSession, task: ReminderTask) -> str:
    lines = [f"【Fly Arrangement 提醒】{task.title}"]
    if task.content:
        lines.append(task.content)
    if task.related_event_id:
        ev = await db.get(CalendarEvent, task.related_event_id)
        if ev:
            st = ev.start_time.astimezone(CST).strftime("%Y-%m-%d %H:%M") if ev.start_time else ""
            et = ev.end_time.astimezone(CST).strftime("%Y-%m-%d %H:%M") if ev.end_time else ""
            lines.append(f"关联日程：{ev.title}（{st} ~ {et}）")
    return "\n".join(lines)


def reminder_task_to_dict(t: ReminderTask) -> dict[str, Any]:
    return {
        "id": t.id,
        "owner_user_id": t.owner_user_id,
        "channel": t.channel,
        "title": t.title,
        "content": t.content,
        "related_event_id": t.related_event_id,
        "related_project_id": t.related_project_id,
        "related_customer_id": t.related_customer_id,
        "reminder_type": t.reminder_type,
        "schedule_rule": t.schedule_rule_json,
        "next_trigger_at": t.next_trigger_at.isoformat() if t.next_trigger_at else None,
        "last_trigger_at": t.last_trigger_at.isoformat() if t.last_trigger_at else None,
        "end_at": t.end_at.isoformat() if t.end_at else None,
        "is_enabled": t.is_enabled,
        "status": t.status,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


async def create_reminder_task_service(
    db: AsyncSession,
    *,
    operator_user_id: int | None,
    title: str,
    content: str | None,
    channel: str,
    reminder_type: str,
    schedule_rule: dict[str, Any] | None = None,
    related_event_id: int | None = None,
    related_project_id: int | None = None,
    related_customer_id: int | None = None,
    end_at: str | None = None,
    trigger_at: str | None = None,
    operator_source: str | None = None,
) -> dict[str, Any]:
    if operator_user_id is None:
        return {"success": False, "error": "需要登录用户身份才能创建提醒", "execution_summary": "缺少用户身份"}

    title = (title or "").strip() or "提醒"
    content = (content or "").strip() or None
    channel = (channel or "feishu_private").strip()
    reminder_type = (reminder_type or "one_time").strip()
    rule = dict(schedule_rule or {})

    # 桌面 Web / Electron：写入本地 reminder_tasks，不要求飞书身份；触发时无推送仅记日志（见 _fire_one_reminder）
    is_desktop_web = (operator_source or "").strip() == "web"
    open_id: str | None
    tenant_key: str | None
    effective_channel: str

    if is_desktop_web:
        effective_channel = "local"
        open_id = None
        tenant_key = None
    else:
        if channel != "feishu_private":
            return {
                "success": False,
                "error": "当前仅支持 channel=feishu_private；桌面端请通过网页聊天创建（将自动存为本地提醒）。",
                "execution_summary": "渠道不支持",
            }
        effective_channel = "feishu_private"
        open_id, tenant_key = await resolve_feishu_for_user(db, operator_user_id)
        if not open_id:
            return {
                "success": False,
                "error": "未绑定飞书身份，无法在飞书私聊发送提醒。请先在「设置 → 飞书身份」完成绑定。",
                "execution_summary": "未绑定飞书，无法创建飞书提醒",
            }

    end_at_dt = parse_iso_datetime(end_at) if end_at else None
    now = datetime.now(timezone.utc)
    next_trigger: datetime | None = None

    if reminder_type == "one_time":
        ta_raw = trigger_at if trigger_at is not None else rule.get("trigger_at")
        ta_for_parse = str(ta_raw).strip() if ta_raw is not None and str(ta_raw).strip() else None
        title_for_parse = _title_for_reminder_time_parse(title, reminder_type=reminder_type, trigger_at=ta_for_parse)
        resolved = resolve_reminder_oneshot_trigger_datetime(
            trigger_at=ta_for_parse,
            title=title_for_parse,
            content=content,
            now_utc=now,
        )
        if not resolved.get("ok") and reminder_type == "one_time":
            fb = _try_parse_day_after_afternoon_clock(title_for_parse, now)
            if fb is not None:
                resolved = {"ok": True, "trigger_cst": fb, "source": "reminder_service_day_after_pm"}
        if not resolved.get("ok"):
            err = str(resolved.get("error") or "无法解析触发时间")
            return {"success": False, "error": err, "execution_summary": err}

        trigger_cst = resolved["trigger_cst"]
        if trigger_cst.tzinfo is None:
            trigger_cst = trigger_cst.replace(tzinfo=CST)
        next_trigger = trigger_cst.astimezone(timezone.utc)

        min_lead = max(30, int(getattr(settings, "REMINDER_MIN_LEAD_SECONDS", 60)))
        grace = timedelta(minutes=5)
        adjustment_note: str | None = None
        floor = now + timedelta(seconds=min_lead)

        # 兜底校正：只要模型解析结果落在“可执行时间窗口”之前，则顺延到最近可执行时间，
        # 并在 execution_summary 中说明（避免因一次失败导致重复创建）。
        if next_trigger < floor:
            prev = next_trigger
            next_trigger = floor
            if prev < now - grace:
                adjustment_note = "解析到的触发时间已过期，已自动顺延至最近可执行时间。"
            else:
                adjustment_note = "由于原始触发时间过近，已自动顺延至最近可执行时间。"

        rule = dict(rule)
        rule["trigger_at"] = next_trigger.isoformat()
        if adjustment_note:
            rule["_trigger_adjustment_note"] = adjustment_note

    elif reminder_type == "recurring":
        if end_at_dt is None and related_event_id:
            ev = await get_calendar_event_for_owner(db, related_event_id, operator_user_id)
            if ev:
                end_at_dt = ev.end_time
        if end_at_dt is None:
            until_s = rule.get("until")
            end_at_dt = parse_iso_datetime(str(until_s)) if until_s else None
        if end_at_dt and end_at_dt <= now:
            return {"success": False, "error": "截止时间必须在未来", "execution_summary": "截止时间无效"}
        freq = rule.get("freq") or "daily"
        if freq != "daily":
            return {"success": False, "error": "目前仅支持 freq=daily", "execution_summary": "频率不支持"}
        next_trigger = first_recurring_next(now, rule, end_at_dt)
        if not next_trigger:
            return {"success": False, "error": "无法计算下次触发时间（可能已超过截止时间）", "execution_summary": "排程失败"}

    elif reminder_type == "relative_to_event":
        eid = related_event_id or rule.get("related_event_id")
        if not eid:
            return {"success": False, "error": "相对事件提醒必须提供 related_event_id", "execution_summary": "缺少关联日程"}
        ev = await get_calendar_event_for_owner(db, int(eid), operator_user_id)
        if not ev:
            return {"success": False, "error": "关联日程不存在或无权访问", "execution_summary": "日程无效"}
        offset = rule.get("offset_minutes")
        if offset is None:
            return {
                "success": False,
                "error": "schedule_rule 需包含 offset_minutes（相对锚点的分钟偏移，负数为提前）",
                "execution_summary": "缺少偏移",
            }
        try:
            offset_m = int(offset)
        except (TypeError, ValueError):
            return {"success": False, "error": "offset_minutes 必须为整数", "execution_summary": "偏移无效"}
        anchor = str(rule.get("anchor") or "start")
        base = ev.start_time if anchor == "start" else ev.end_time
        next_trigger = base + timedelta(minutes=offset_m)
        if next_trigger.tzinfo is None:
            next_trigger = next_trigger.replace(tzinfo=timezone.utc)
        else:
            next_trigger = next_trigger.astimezone(timezone.utc)
        if next_trigger <= now:
            return {"success": False, "error": "相对事件计算出的触发时间已过", "execution_summary": "触发时间已过期"}
        if related_event_id is None:
            related_event_id = int(eid)
    else:
        return {"success": False, "error": f"未知 reminder_type: {reminder_type}", "execution_summary": "类型不支持"}

    task = ReminderTask(
        owner_user_id=operator_user_id,
        channel=effective_channel,
        feishu_open_id=open_id,
        tenant_key=tenant_key,
        title=title,
        content=content,
        related_event_id=related_event_id,
        related_project_id=related_project_id,
        related_customer_id=related_customer_id,
        reminder_type=reminder_type,
        schedule_rule_json=rule,
        next_trigger_at=next_trigger,
        last_trigger_at=None,
        end_at=end_at_dt,
        is_enabled=True,
        status="active",
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    data = reminder_task_to_dict(task)
    data["reminder_task_id"] = task.id
    adj = None
    if reminder_type == "one_time" and isinstance(task.schedule_rule_json, dict):
        adj = task.schedule_rule_json.get("_trigger_adjustment_note")
    if is_desktop_web:
        summary = f"已创建本地提醒计划「{title}」（id={task.id}，触发时间已写入；桌面端暂无系统级推送，可在提醒列表中查看）"
    else:
        summary = f"已创建飞书提醒计划「{title}」（id={task.id}）"
    if adj:
        summary += f" {adj}"
    return {
        "success": True,
        "result": data,
        "execution_summary": summary,
    }


async def list_reminder_tasks_service(
    db: AsyncSession,
    *,
    operator_user_id: int | None,
    status_filter: str | None = None,
) -> dict[str, Any]:
    if operator_user_id is None:
        return {"success": False, "error": "需要用户身份", "execution_summary": "缺少用户身份", "result": []}
    stmt = select(ReminderTask).where(ReminderTask.owner_user_id == operator_user_id).order_by(ReminderTask.id.desc())
    if status_filter:
        stmt = stmt.where(ReminderTask.status == status_filter)
    r = await db.execute(stmt)
    rows = list(r.scalars().all())
    return {
        "success": True,
        "result": [reminder_task_to_dict(t) for t in rows],
        "execution_summary": f"共 {len(rows)} 条提醒计划",
    }


async def cancel_reminder_task_service(
    db: AsyncSession,
    *,
    operator_user_id: int | None,
    task_id: int,
) -> dict[str, Any]:
    if operator_user_id is None:
        return {"success": False, "error": "需要用户身份", "execution_summary": "缺少用户身份"}
    t = await db.get(ReminderTask, task_id)
    if t is None or t.owner_user_id != operator_user_id:
        return {"success": False, "error": "提醒不存在或无权操作", "execution_summary": "未找到提醒"}
    t.status = "cancelled"
    t.is_enabled = False
    t.next_trigger_at = None
    t.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return {
        "success": True,
        "result": {"reminder_task_id": t.id, "status": t.status},
        "execution_summary": f"已取消提醒 id={t.id}",
    }


async def update_reminder_task_service(
    db: AsyncSession,
    *,
    operator_user_id: int | None,
    task_id: int,
    title: str | None = None,
    content: str | None = None,
    end_at: str | None = None,
    is_enabled: bool | None = None,
    schedule_rule: dict[str, Any] | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    if operator_user_id is None:
        return {"success": False, "error": "需要用户身份", "execution_summary": "缺少用户身份"}
    t = await db.get(ReminderTask, task_id)
    if t is None or t.owner_user_id != operator_user_id:
        return {"success": False, "error": "提醒不存在或无权操作", "execution_summary": "未找到提醒"}
    if t.status in ("cancelled", "completed"):
        return {"success": False, "error": "已结束或已取消的提醒不可修改", "execution_summary": "状态不允许修改"}

    now = datetime.now(timezone.utc)
    if title is not None:
        t.title = (title or "").strip() or t.title
    if content is not None:
        t.content = (content or "").strip() or None
    if end_at is not None:
        t.end_at = parse_iso_datetime(end_at)
    if is_enabled is not None:
        t.is_enabled = bool(is_enabled)
        if not t.is_enabled:
            t.status = "paused"
        elif t.status == "paused":
            t.status = "active"
    if schedule_rule is not None:
        merged = dict(t.schedule_rule_json or {})
        merged.update(schedule_rule)
        t.schedule_rule_json = merged

    if status is not None and status in ("active", "paused"):
        t.status = status
        if status == "paused":
            t.is_enabled = False
        else:
            t.is_enabled = True

    recompute_next = False
    if t.reminder_type == "recurring":
        if end_at is not None or schedule_rule is not None:
            recompute_next = True
        if is_enabled is True and t.is_enabled:
            recompute_next = True
        if status == "active":
            recompute_next = True
    if recompute_next and t.status == "active" and t.is_enabled:
        rule = dict(t.schedule_rule_json or {})
        t.next_trigger_at = first_recurring_next(now, rule, t.end_at)

    t.updated_at = now
    await db.flush()
    await db.refresh(t)
    return {
        "success": True,
        "result": reminder_task_to_dict(t),
        "execution_summary": f"已更新提醒 id={t.id}",
    }


def _complete_task_after_trigger(task: ReminderTask, now: datetime) -> None:
    """单次/周期：在已成功触发（飞书发出或本地记账）后更新任务状态与下次触发。"""
    if task.reminder_type == "one_time" or task.reminder_type == "relative_to_event":
        task.status = "completed"
        task.next_trigger_at = None
    elif task.reminder_type == "recurring":
        r = dict(task.schedule_rule_json or {})
        nxt = next_recurring_after_fire(now, r, task.end_at)
        if nxt is None:
            task.status = "completed"
            task.next_trigger_at = None
        else:
            task.next_trigger_at = nxt
    else:
        task.status = "completed"
        task.next_trigger_at = None
    task.updated_at = now


async def _fire_one_reminder(db: AsyncSession, task: ReminderTask, now: datetime) -> int:
    """SQLite 桌面模式：将仍标记为 feishu_private 的旧任务按本地渠道记账，避免反复打飞书 API。"""
    try:
        if is_sqlite_url(normalize_database_url(get_database_url())) and task.channel == "feishu_private":
            task.channel = "local"
            await db.flush()
    except Exception:
        pass

    if task.channel == "local":
        db.add(
            ReminderLog(
                reminder_task_id=task.id,
                triggered_at=now,
                status="sent",
                error_message=None,
                feishu_message_id=None,
            )
        )
        task.last_trigger_at = now
        rule = dict(task.schedule_rule_json or {})
        rule.pop("_send_failures", None)
        task.schedule_rule_json = rule
        _complete_task_after_trigger(task, now)
        await db.flush()
        return 1

    if task.channel != "feishu_private" or not task.feishu_open_id:
        log = ReminderLog(
            reminder_task_id=task.id,
            triggered_at=now,
            status="failed",
            error_message="渠道不支持或未配置飞书 open_id",
        )
        db.add(log)
        task.status = "failed"
        task.next_trigger_at = None
        task.updated_at = now
        await db.flush()
        return 1

    text = await build_reminder_feishu_text(db, task)
    out = await send_text_message(
        db,
        receive_id=task.feishu_open_id,
        receive_id_type="open_id",
        text=text,
        tenant_key=task.tenant_key,
    )
    ok = bool(out.get("ok"))
    msg_id = (out.get("message_id") or "") if isinstance(out.get("message_id"), str) else None

    if not ok:
        rule = dict(task.schedule_rule_json or {})
        fails = int(rule.get("_send_failures") or 0) + 1
        rule["_send_failures"] = fails
        task.schedule_rule_json = rule
        db.add(
            ReminderLog(
                reminder_task_id=task.id,
                triggered_at=now,
                status="failed",
                error_message=str(out.get("error") or "send failed")[:2000],
            )
        )
        if fails >= 3:
            task.status = "failed"
            task.next_trigger_at = None
        else:
            task.next_trigger_at = now + timedelta(minutes=15)
        task.updated_at = now
        await db.flush()
        logger.warning("reminder send failed task_id=%s fails=%s", task.id, fails)
        return 1

    db.add(
        ReminderLog(
            reminder_task_id=task.id,
            triggered_at=now,
            status="sent",
            feishu_message_id=msg_id,
        )
    )
    task.last_trigger_at = now
    rule = dict(task.schedule_rule_json or {})
    rule.pop("_send_failures", None)
    task.schedule_rule_json = rule

    _complete_task_after_trigger(task, now)

    await db.flush()
    return 1


async def process_due_reminders(db: AsyncSession) -> int:
    """处理已到期的提醒；返回处理条数。"""
    now = datetime.now(timezone.utc)
    stmt = (
        select(ReminderTask)
        .where(
            ReminderTask.status == "active",
            ReminderTask.is_enabled.is_(True),
            ReminderTask.next_trigger_at.isnot(None),
            ReminderTask.next_trigger_at <= now,
        )
        .order_by(ReminderTask.next_trigger_at)
        .limit(40)
    )
    r = await db.execute(stmt)
    tasks = list(r.scalars().all())
    total = 0
    for task in tasks:
        total += await _fire_one_reminder(db, task, now)
    return total
