"""
飞书私聊离线补偿服务：按详细版规范提供 list_sync_targets、get_or_create_sync_state、
fetch_feishu_private_history、normalize_history_message、should_skip_history_message、
persist_history_message_event、process_pending_history_message、update_sync_watermark，
run_feishu_history_sync_once、replay_pending_feishu_messages。
仅私聊、文本、已绑定身份；不处理群聊/图片/文件/卡片。
AI 未就绪时消息保持 pending，由 replay_pending_feishu_messages 在 AI ready 后补执行。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx
from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    FeishuIdentityPool,
    FeishuMessageEvent,
    FeishuSyncState,
    SystemLog,
)
from app.db.desktop_mode import is_desktop_sqlite_backend
from app.services.feishu_bot import list_chat_messages, get_message
from app.services.feishu_webhook import _process_one_feishu_message_core
from app.services.audit_log_service import write_audit_log

logger = logging.getLogger(__name__)
MODULE = "feishu.sync"
CHANNEL_TYPE = "feishu_private"
HISTORY_SYNC_WINDOW_SECONDS = 24 * 3600
MAX_HISTORY_MESSAGES_PER_CHAT = 200
PAGE_SIZE = 50
EVENT_TYPE_HISTORY_SYNC = "history.message.sync"
SOURCE_HISTORY_SYNC = "history_sync"
REPLAY_BATCH_SIZE = 50
MAX_REPLAY_RETRIES = 10
REPLAY_RETRY_BASE_SECONDS = 30

# process_status enums for offline compensation (DB-observable)
STATUS_HISTORY_PENDING = "history_pending"
STATUS_SKIPPED_DUPLICATE = "skipped_duplicate"
STATUS_SKIPPED_UNBOUND = "skipped_unbound"
STATUS_SKIPPED_NON_TEXT = "skipped_non_text"
STATUS_SKIPPED_EMPTY = "skipped_empty"
STATUS_OFFLINE_PENDING = "offline_pending"
STATUS_REPLAY_SUCCESS = "replay_success"
STATUS_REPLAY_FAILED = "replay_failed"


def _mask_open_id(open_id: str | None, visible: int = 4) -> str:
    if not open_id or len(open_id) <= visible * 2:
        return "***"
    return f"{open_id[:visible]}***{open_id[-visible:]}"


def _mask_union_id(union_id: str | None, visible: int = 4) -> str:
    if not union_id or len(union_id) <= visible * 2:
        return "***"
    return f"{union_id[:visible]}***{union_id[-visible:]}"


def _mask_chat_id(chat_id: str | None, visible: int = 6) -> str:
    if not chat_id or len(chat_id) <= visible * 2:
        return "***"
    return f"{chat_id[:visible]}***{chat_id[-visible:]}"


async def _log_sync(db: AsyncSession, level: str, message: str) -> None:
    db.add(SystemLog(level=level, module=MODULE, message=message[:2000]))
    await db.flush()


def _is_ai_not_ready_error(e: Exception) -> bool:
    """是否为 AI 未就绪类错误（连接/超时/503/loading），应保持 pending 稍后重放。"""
    msg = (getattr(e, "message", "") or str(e)).lower()
    if isinstance(e, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout)):
        return True
    if "connection refused" in msg or "connection reset" in msg or "timeout" in msg or "timed out" in msg:
        return True
    if "not ready" in msg or "loading" in msg or "unavailable" in msg:
        return True
    if getattr(e, "response", None) is not None:
        try:
            if getattr(e.response, "status_code", None) == 503:
                return True
        except Exception:
            pass
    return False


# ---------------------------------------------------------------------------
# 1. list_sync_targets(db)
# ---------------------------------------------------------------------------
async def list_sync_targets(db: AsyncSession) -> list[FeishuIdentityPool]:
    """
    查找所有应参与补偿的对象：
    - 已绑定用户（bind_status = 'bound'）
    - 对应 identity 非 ignored
    - channel_type = feishu_private（私聊，通过 chat_id 存在推断）
    - is_enabled 在 sync_state 层控制，此处只查 identity
    """
    rows = (
        await db.execute(
            select(FeishuIdentityPool).where(
                FeishuIdentityPool.chat_id.isnot(None),
                FeishuIdentityPool.chat_id != "",
            )
        )
    ).scalars().all()
    # 允许未绑定 chat_id 参与同步：用于落库 skipped_unbound 与推进水位，避免离线消息无痕丢失
    return [r for r in rows if r.chat_id and (r.bind_status or "") != "ignored"]


# ---------------------------------------------------------------------------
# 2. get_or_create_sync_state(db, identity)
# ---------------------------------------------------------------------------
async def get_or_create_sync_state(
    db: AsyncSession,
    identity: FeishuIdentityPool,
) -> FeishuSyncState:
    """为每个已绑定飞书身份获取或创建 feishu_sync_state。"""
    row = (
        await db.execute(
            select(FeishuSyncState).where(
                FeishuSyncState.chat_id == identity.chat_id,
                FeishuSyncState.channel_type == CHANNEL_TYPE,
            ).limit(1)
        )
    ).scalar_one_or_none()
    if row:
        if row.is_enabled and (row.identity_pool_id is None or row.union_id != identity.union_id):
            row.identity_pool_id = identity.id
            row.union_id = identity.union_id
            row.tenant_key = identity.tenant_key
            row.open_id = identity.open_id
            row.bound_user_id = identity.bound_user_id
            await db.flush()
        return row
    row = FeishuSyncState(
        bound_user_id=identity.bound_user_id,
        identity_pool_id=identity.id,
        tenant_key=identity.tenant_key,
        open_id=identity.open_id,
        union_id=identity.union_id,
        chat_id=identity.chat_id,
        channel_type=CHANNEL_TYPE,
        is_enabled=True,
    )
    db.add(row)
    await db.flush()
    return row


# ---------------------------------------------------------------------------
# 3. fetch_feishu_private_history(...)
# ---------------------------------------------------------------------------
async def fetch_feishu_private_history(
    db: AsyncSession,
    *,
    tenant_key: str | None,
    chat_id: str,
    start_time: int | None,
    end_time: int | None,
    page_token: str | None = None,
    page_size: int = PAGE_SIZE,
    max_items: int = MAX_HISTORY_MESSAGES_PER_CHAT,
) -> tuple[list[dict[str, Any]], str | None]:
    """
    只拉私聊会话历史；按 create_time 升序返回（由调用方排序）。
    返回 (items, next_page_token)，items 不超过 max_items。
    """
    all_items: list[dict[str, Any]] = []
    next_token: str | None = page_token
    while len(all_items) < max_items:
        resp = await list_chat_messages(
            db,
            chat_id=chat_id,
            tenant_key=tenant_key,
            start_time=start_time,
            end_time=end_time,
            page_token=next_token,
            page_size=min(page_size, max_items - len(all_items)),
        )
        if not resp.get("ok"):
            raise RuntimeError(resp.get("error", "list_chat_messages failed"))
        items = resp.get("items") or []
        all_items.extend(items)
        if not resp.get("has_more") or not resp.get("page_token"):
            return all_items, None
        next_token = resp.get("page_token")
        if len(all_items) >= max_items:
            return all_items, next_token
    return all_items, next_token


# ---------------------------------------------------------------------------
# 4. normalize_history_message(item)
# ---------------------------------------------------------------------------
def normalize_history_message(item: dict[str, Any]) -> dict[str, Any]:
    """把飞书历史消息整理成统一内部结构。"""
    message_id = item.get("message_id")
    chat_id = item.get("chat_id")
    create_time_ms = item.get("create_time")
    create_time: datetime | None = None
    # 飞书接口常返回字符串毫秒时间戳；也可能是秒级时间戳（历史兼容）
    if isinstance(create_time_ms, str):
        s = create_time_ms.strip()
        if s.isdigit():
            try:
                create_time_ms = int(s)
            except Exception:
                create_time_ms = None
    if isinstance(create_time_ms, (int, float)):
        ts = float(create_time_ms)
        # heuristic: >= 10^12 认为是毫秒，否则认为是秒
        if ts >= 1_000_000_000_000:
            ts = ts / 1000.0
        create_time = datetime.fromtimestamp(ts, tz=timezone.utc)
    sender = item.get("sender") or {}
    sender_id = sender.get("sender_id") if isinstance(sender, dict) else {}
    if not isinstance(sender_id, dict):
        sender_id = {}
    open_id = sender_id.get("open_id")
    union_id = sender_id.get("union_id")
    sender_type = sender.get("sender_type") if isinstance(sender, dict) else None
    msg_type = item.get("msg_type") or item.get("message_type")
    content = item.get("content")
    content_text = _extract_text_from_content(content)
    return {
        "message_id": message_id,
        "chat_id": chat_id,
        "open_id": open_id,
        "union_id": union_id,
        "sender_type": sender_type,
        "message_type": msg_type,
        "content_text": content_text,
        "create_time": create_time,
        "raw_payload": item,
    }


def _extract_text_from_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        try:
            obj = json.loads(content)
            return str((obj or {}).get("text") or "").strip()
        except (json.JSONDecodeError, TypeError):
            return ""
    if isinstance(content, dict):
        return str(content.get("text") or "").strip()
    return ""


# ---------------------------------------------------------------------------
# 5. should_skip_history_message(...)
# ---------------------------------------------------------------------------
async def should_skip_history_message(
    db: AsyncSession,
    normalized: dict[str, Any],
    *,
    bound_user_id: int,
    identity: FeishuIdentityPool,
) -> tuple[bool, str]:
    """
    判断是否跳过。返回 (skip, reason)。
    跳过：缺少 message_id、已存在本地 message_id、身份 ignored。
    其它“非文本/机器人消息/空消息”等在落库后用 process_status 标记为 skipped_*，避免离线消息无痕丢失。
    """
    message_id = normalized.get("message_id")
    if not message_id:
        return True, "missing message_id"
    if identity.bind_status == "ignored":
        return True, "identity ignored"
    existing = (
        await db.execute(
            select(FeishuMessageEvent).where(FeishuMessageEvent.message_id == message_id).limit(1)
        )
    ).scalar_one_or_none()
    if existing:
        # 不覆盖已成功处理的记录；仅用于让“重复拉取”在 DB 层可见（skipped_duplicate）
        if existing.process_status not in (STATUS_REPLAY_SUCCESS, "success"):
            existing.process_status = STATUS_SKIPPED_DUPLICATE
            existing.updated_at = datetime.now(timezone.utc)
            await db.flush()
        return True, "duplicate message_id"
    return False, ""


# ---------------------------------------------------------------------------
# 6. persist_history_message_event(...)
# ---------------------------------------------------------------------------
async def persist_history_message_event(
    db: AsyncSession,
    normalized: dict[str, Any],
    *,
    chat_id: str,
    open_id: str | None,
    tenant_key: str | None,
) -> FeishuMessageEvent:
    """把补偿消息先落入本地消息事件表，状态为 pending。"""
    message_id = normalized.get("message_id")
    event_id_synthetic = f"history_sync:{message_id}"
    record = FeishuMessageEvent(
        event_id=event_id_synthetic,
        message_id=message_id,
        chat_id=chat_id,
        open_id=open_id or normalized.get("open_id"),
        event_type=EVENT_TYPE_HISTORY_SYNC,
        message_type="text",
        raw_payload=normalized.get("raw_payload"),
        process_status=STATUS_HISTORY_PENDING,
        retry_count=0,
        next_retry_at=None,
        source=SOURCE_HISTORY_SYNC,
    )
    db.add(record)
    try:
        await db.flush()
        return record
    except IntegrityError:
        await db.rollback()
        existing = (
            await db.execute(
                select(FeishuMessageEvent).where(FeishuMessageEvent.message_id == message_id).limit(1)
            )
        ).scalar_one_or_none()
        if existing:
            raise ValueError(f"duplicate message_id={message_id}") from None
        raise


# ---------------------------------------------------------------------------
# 7. process_pending_history_message(...)
# ---------------------------------------------------------------------------
async def process_pending_history_message(
    db: AsyncSession,
    event_record: FeishuMessageEvent,
    *,
    bound_user_id: int,
    open_id: str,
    chat_id: str,
    tenant_key: str | None,
    text: str,
    message_id: str,
) -> None:
    """
    复用 AI 处理主流程：定位绑定用户、找到/创建飞书私聊同步会话、
    写入 user message、调 AI、写入 assistant message、发回飞书、更新 process_status=success。
    """
    if event_record.process_status not in (STATUS_HISTORY_PENDING, STATUS_OFFLINE_PENDING):
        return
    event_record.process_status = "processing"
    await db.flush()
    await _process_one_feishu_message_core(
        db,
        open_id=open_id,
        chat_id=chat_id,
        tenant_key=tenant_key,
        text=text,
        message_id=message_id,
        bound_user_id=bound_user_id,
        event_record=event_record,
        conversation_type="p2p",
        final_process_status=STATUS_REPLAY_SUCCESS,
    )


# ---------------------------------------------------------------------------
# 8. update_sync_watermark(...)
# ---------------------------------------------------------------------------
async def update_sync_watermark(
    db: AsyncSession,
    sync_state: FeishuSyncState,
    *,
    last_processed_message_id: str | None = None,
    last_processed_message_time: datetime | None = None,
    last_synced_message_id: str | None = None,
    last_synced_message_time: datetime | None = None,
    last_sync_error: str | None = None,
) -> None:
    """处理完成后推进水位；失败时更新 last_sync_error。"""
    now = datetime.now(timezone.utc)
    if last_processed_message_id is not None:
        sync_state.last_processed_message_id = last_processed_message_id
    if last_processed_message_time is not None:
        sync_state.last_processed_message_time = last_processed_message_time
    if last_synced_message_id is not None:
        sync_state.last_synced_message_id = last_synced_message_id
    if last_synced_message_time is not None:
        sync_state.last_synced_message_time = last_synced_message_time
    sync_state.last_sync_finished_at = now
    if last_sync_error is not None:
        sync_state.last_sync_error = last_sync_error[:500]
    else:
        sync_state.last_sync_error = None
    await db.flush()


def _next_retry_at_for(retry_count: int) -> datetime:
    # 简单指数退避：30s, 60s, 120s... 上限 30min
    delay = min(REPLAY_RETRY_BASE_SECONDS * (2 ** max(0, retry_count - 1)), 1800)
    return datetime.now(timezone.utc) + timedelta(seconds=delay)


# ---------------------------------------------------------------------------
# run_feishu_history_sync_once(db)
# ---------------------------------------------------------------------------
async def run_feishu_history_sync_once(db: AsyncSession) -> None:
    """
    启动后执行一次：查找补偿目标 -> 对每个目标拉历史、过滤、落库 pending、处理、更新水位。
    单个目标失败不阻断其他目标；全局异常记录日志。
    """
    if is_desktop_sqlite_backend():
        return
    try:
        await _run_feishu_history_sync_once_impl(db)
    except Exception as e:
        await _log_sync(db, "ERROR", f"feishu history sync failed: {e!s}")
        logger.exception("feishu history sync failed: %s", e)
        raise


async def _run_feishu_history_sync_once_impl(db: AsyncSession) -> None:
    if is_desktop_sqlite_backend():
        return
    await _log_sync(db, "INFO", "feishu history sync started")
    logger.info("feishu history sync started")
    await write_audit_log(
        db,
        action="feishu_history_sync_started",
        target_type="system",
        target_id="scan",
        detail="feishu history sync scan started",
        metadata_json={},
    )
    targets = await list_sync_targets(db)
    total_fetched = 0
    total_deduped = 0
    total_skipped_other = 0
    total_replay_queued = 0
    total_skipped_unbound = 0
    for identity in targets:
        if not identity.chat_id:
            await _log_sync(db, "WARNING", f"skip identity id={identity.id} missing chat_id")
            continue
        try:
            sync_state = await get_or_create_sync_state(db, identity)
            if not sync_state.is_enabled:
                await _log_sync(db, "INFO", f"sync disabled for bound_user_id={identity.bound_user_id} chat_id={_mask_chat_id(identity.chat_id)}")
                continue
            now = datetime.now(timezone.utc)
            sync_state.last_sync_started_at = now
            sync_state.last_sync_error = None
            await db.flush()
            await _log_sync(
                db,
                "INFO",
                f"syncing history for bound_user_id={identity.bound_user_id} chat_id={_mask_chat_id(identity.chat_id)}",
            )
            await write_audit_log(
                db,
                action="feishu_history_sync_started",
                actor_user_id=identity.bound_user_id,
                target_type="feishu_sync_state",
                target_id=str(sync_state.id),
                detail=f"syncing history for chat_id={_mask_chat_id(identity.chat_id)}",
                metadata_json={"bound_user_id": identity.bound_user_id, "chat_id": identity.chat_id},
            )
            start_time: int | None = None
            if sync_state.last_processed_message_time:
                start_time = int(sync_state.last_processed_message_time.timestamp())
            else:
                start_time = int((now - timedelta(seconds=HISTORY_SYNC_WINDOW_SECONDS)).timestamp())
            end_time = int(now.timestamp())
            await _log_sync(db, "INFO", f"feishu history sync range start_time={start_time} end_time={end_time} chat_id={_mask_chat_id(identity.chat_id)}")
            logger.info("feishu history sync range start_time=%s end_time=%s chat_id=%s", start_time, end_time, _mask_chat_id(identity.chat_id))
            try:
                items, _ = await fetch_feishu_private_history(
                    db,
                    tenant_key=identity.tenant_key,
                    chat_id=identity.chat_id,
                    start_time=start_time,
                    end_time=end_time,
                    max_items=MAX_HISTORY_MESSAGES_PER_CHAT,
                )
            except Exception as e:
                err = str(e)
                await update_sync_watermark(db, sync_state, last_sync_error=err)
                await _log_sync(db, "ERROR", f"history sync failed for bound_user_id={identity.bound_user_id} reason={err}")
                await write_audit_log(
                    db,
                    action="feishu_history_sync_failed",
                    actor_user_id=identity.bound_user_id,
                    target_type="feishu_sync_state",
                    target_id=str(sync_state.id),
                    detail=f"fetch history failed: {err}",
                    metadata_json={"bound_user_id": identity.bound_user_id, "error": err},
                )
                continue
            total_fetched += len(items)
            await _log_sync(db, "INFO", f"feishu history sync fetched {len(items)} messages")
            logger.info("feishu history sync fetched %s messages", len(items))
            await write_audit_log(
                db,
                action="feishu_history_message_fetched",
                actor_user_id=identity.bound_user_id,
                target_type="feishu_sync_state",
                target_id=str(sync_state.id),
                detail=f"fetched {len(items)} historical messages",
                metadata_json={"bound_user_id": identity.bound_user_id, "count": len(items)},
            )
            def _sort_key(raw_item: dict[str, Any]) -> float:
                t = raw_item.get("create_time")
                if t is None:
                    return 0.0
                return float(t) if isinstance(t, (int, float)) else 0.0
            sorted_items = sorted(items, key=_sort_key)
            last_processed_id: str | None = sync_state.last_processed_message_id
            last_processed_time: datetime | None = sync_state.last_processed_message_time
            deduped_this_chat = 0
            skipped_other_this_chat = 0
            for item in sorted_items:
                normalized = normalize_history_message(item)
                # 水位推进：无论后续是否跳过/入队/成功，只要能解析到 create_time，就推进 last_processed_*
                create_time = normalized.get("create_time")
                if isinstance(create_time, datetime):
                    if last_processed_time is None or create_time > last_processed_time:
                        last_processed_time = create_time
                        last_processed_id = normalized.get("message_id") or last_processed_id
                else:
                    # 无法解析 create_time 时，至少推进 message_id，避免水位长期为 NULL
                    if normalized.get("message_id"):
                        last_processed_id = normalized.get("message_id") or last_processed_id

                skip, reason = await should_skip_history_message(db, normalized, bound_user_id=identity.bound_user_id, identity=identity)
                if skip:
                    if "duplicate" in reason:
                        deduped_this_chat += 1
                        total_deduped += 1
                        await _log_sync(db, "INFO", f"skipped duplicate history message_id={normalized.get('message_id')}")
                        await write_audit_log(
                            db,
                            action="feishu_offline_message_skipped_duplicate",
                            actor_user_id=identity.bound_user_id,
                            target_type="feishu_message_event",
                            target_id=str(normalized.get("message_id") or ""),
                            detail=f"skipped duplicate message_id={normalized.get('message_id')}",
                            metadata_json={"chat_id": identity.chat_id, "message_id": normalized.get("message_id"), "bound_user_id": identity.bound_user_id},
                        )
                    else:
                        skipped_other_this_chat += 1
                        total_skipped_other += 1
                        await _log_sync(db, "INFO", f"skipped non-text / bot / group message message_id={normalized.get('message_id')} reason={reason}")
                    continue
                message_id = normalized.get("message_id")
                content_text = normalized.get("content_text") or ""
                sender_type = normalized.get("sender_type")
                msg_type = (normalized.get("message_type") or "").lower()
                # 先确保落库一条 history_pending，再根据类型标记 skipped_non_text
                if sender_type != "user" or (msg_type and msg_type != "text"):
                    skipped_other_this_chat += 1
                    total_skipped_other += 1
                    try:
                        event_record = await persist_history_message_event(
                            db,
                            normalized,
                            chat_id=identity.chat_id,
                            open_id=identity.open_id,
                            tenant_key=identity.tenant_key,
                        )
                        event_record.process_status = STATUS_SKIPPED_NON_TEXT
                        event_record.updated_at = datetime.now(timezone.utc)
                        await db.flush()
                    except Exception:
                        pass
                    await _log_sync(db, "INFO", f"skipped non-text / bot message_id={message_id} sender_type={sender_type} msg_type={msg_type}")
                    continue
                if not content_text.strip():
                    resp = await get_message(db, message_id=message_id, tenant_key=identity.tenant_key)
                    if resp.get("ok"):
                        data = resp.get("data") or {}
                        content_text = _extract_text_from_content(data.get("content"))
                if not content_text.strip():
                    # 仍落库一条 history_pending -> skipped_empty（保证 DB 可追踪）
                    skipped_other_this_chat += 1
                    total_skipped_other += 1
                    try:
                        event_record = await persist_history_message_event(
                            db,
                            normalized,
                            chat_id=identity.chat_id,
                            open_id=identity.open_id,
                            tenant_key=identity.tenant_key,
                        )
                        event_record.process_status = STATUS_SKIPPED_EMPTY
                        await db.flush()
                    except Exception:
                        pass
                    await _log_sync(db, "INFO", f"skipped empty message_id={message_id}")
                    continue

                # 历史消息落库为 history_pending（无论后续是否可执行）
                try:
                    event_record = await persist_history_message_event(
                        db,
                        normalized,
                        chat_id=identity.chat_id,
                        open_id=identity.open_id,
                        tenant_key=identity.tenant_key,
                    )
                except ValueError as e:
                    await _log_sync(db, "INFO", f"skipped duplicate message_id={message_id} (race)")
                    continue

                # 未绑定：不进入主流程，落库 skipped_unbound
                if not identity.bound_user_id:
                    total_skipped_unbound += 1
                    event_record.process_status = STATUS_SKIPPED_UNBOUND
                    event_record.updated_at = datetime.now(timezone.utc)
                    await db.flush()
                    await _log_sync(db, "INFO", f"skipped unbound message_id={message_id} chat_id={_mask_chat_id(identity.chat_id)}")
                    await write_audit_log(
                        db,
                        action="feishu_offline_message_skipped_unbound",
                        actor_user_id=None,
                        target_type="feishu_message_event",
                        target_id=str(event_record.id),
                        detail=f"skipped unbound offline message message_id={message_id}",
                        metadata_json={"chat_id": identity.chat_id, "message_id": message_id, "open_id": event_record.open_id},
                    )
                    continue

                try:
                    await process_pending_history_message(
                        db,
                        event_record,
                        bound_user_id=identity.bound_user_id,
                        open_id=identity.open_id or normalized.get("open_id") or "",
                        chat_id=identity.chat_id,
                        tenant_key=identity.tenant_key,
                        text=content_text,
                        message_id=message_id,
                    )
                    # process_pending_history_message 内部会把最终状态写成 replay_success
                    await _log_sync(db, "INFO", f"offline message replay success message_id={message_id}")
                    await write_audit_log(
                        db,
                        action="feishu_offline_message_replayed",
                        actor_user_id=identity.bound_user_id,
                        target_type="feishu_message_event",
                        target_id=str(event_record.id),
                        detail=f"offline message replayed success message_id={message_id}",
                        metadata_json={"chat_id": identity.chat_id, "message_id": message_id, "bound_user_id": identity.bound_user_id},
                    )
                    await write_audit_log(
                        db,
                        action="feishu_history_message_synced",
                        actor_user_id=identity.bound_user_id,
                        target_type="feishu_sync_state",
                        target_id=str(sync_state.id),
                        detail=f"synced historical message message_id={message_id}",
                        metadata_json={"bound_user_id": identity.bound_user_id, "message_id": message_id},
                    )
                except Exception as e:
                    if _is_ai_not_ready_error(e):
                        total_replay_queued += 1
                        event_record.process_status = STATUS_OFFLINE_PENDING
                        event_record.retry_count = (event_record.retry_count or 0) + 1
                        event_record.error_message = str(e)[:500]
                        event_record.next_retry_at = _next_retry_at_for(int(event_record.retry_count or 1))
                        await db.flush()
                        await _log_sync(db, "INFO", f"offline message queued (AI not ready) message_id={message_id} retry_count={event_record.retry_count}")
                        logger.info("offline message queued message_id=%s retry_count=%s", message_id, event_record.retry_count)
                        await write_audit_log(
                            db,
                            action="feishu_offline_message_queued",
                            actor_user_id=identity.bound_user_id,
                            target_type="feishu_message_event",
                            target_id=str(event_record.id),
                            detail=f"queued offline message (ai not ready) message_id={message_id}",
                            metadata_json={"chat_id": identity.chat_id, "message_id": message_id, "bound_user_id": identity.bound_user_id, "next_retry_at": event_record.next_retry_at.isoformat() if event_record.next_retry_at else None},
                        )
                    else:
                        event_record.process_status = STATUS_REPLAY_FAILED
                        event_record.error_message = str(e)[:1000]
                        await db.flush()
                        await _log_sync(db, "ERROR", f"offline message replay failed message_id={message_id}: {e!s}")
                        logger.error("offline message replay failed message_id=%s: %s", message_id, e)
                        await update_sync_watermark(db, sync_state, last_sync_error=str(e)[:500])
                        await write_audit_log(
                            db,
                            action="feishu_offline_message_replay_failed",
                            actor_user_id=identity.bound_user_id,
                            target_type="feishu_message_event",
                            target_id=str(event_record.id),
                            detail=f"offline message replay failed message_id={message_id}: {e!s}",
                            metadata_json={"bound_user_id": identity.bound_user_id, "chat_id": identity.chat_id, "message_id": message_id, "error": str(e)},
                        )
            # 同步结束推进 watermarks：last_processed_* 与 last_synced_* 对齐到本轮最后水位
            await update_sync_watermark(
                db,
                sync_state,
                last_processed_message_id=last_processed_id or sync_state.last_processed_message_id,
                last_processed_message_time=last_processed_time or sync_state.last_processed_message_time,
                last_synced_message_id=last_processed_id or sync_state.last_synced_message_id,
                last_synced_message_time=last_processed_time or sync_state.last_synced_message_time,
            )
            await _log_sync(db, "INFO", f"updated watermark for chat_id={_mask_chat_id(identity.chat_id)}")
        except Exception as e:
            await _log_sync(db, "ERROR", f"feishu history sync failed for bound_user_id={identity.bound_user_id}: {e!s}")
            logger.exception("feishu history sync failed for bound_user_id=%s: %s", identity.bound_user_id, e)
            await write_audit_log(
                db,
                action="feishu_history_sync_failed",
                actor_user_id=identity.bound_user_id,
                target_type="feishu_identity_pool",
                target_id=str(identity.id),
                detail=f"sync one chat failed: {e!s}",
                metadata_json={"bound_user_id": identity.bound_user_id, "chat_id": identity.chat_id, "error": str(e)},
            )
    await _log_sync(
        db,
        "INFO",
        f"feishu history sync summary: fetched={total_fetched} deduped={total_deduped} skipped_other={total_skipped_other} replay_queued={total_replay_queued} skipped_unbound={total_skipped_unbound}",
    )
    logger.info(
        "feishu history sync summary: fetched=%s deduped=%s skipped_other=%s replay_queued=%s skipped_unbound=%s",
        total_fetched, total_deduped, total_skipped_other, total_replay_queued, total_skipped_unbound,
    )
    await _log_sync(db, "INFO", "feishu history sync finished")
    logger.info("feishu history sync finished")
    await write_audit_log(
        db,
        action="feishu_history_sync_finished",
        target_type="system",
        target_id="scan",
        detail="feishu history sync finished",
        metadata_json={
            "fetched": total_fetched,
            "deduped": total_deduped,
            "skipped_other": total_skipped_other,
            "replay_queued": total_replay_queued,
            "skipped_unbound": total_skipped_unbound,
        },
    )


# ---------------------------------------------------------------------------
# replay_pending_feishu_messages(db)
# ---------------------------------------------------------------------------
async def replay_pending_feishu_messages(db: AsyncSession) -> int:
    """
    AI 就绪后重放未处理的离线消息（source=history_sync 且 process_status=pending）。
    返回本轮重放处理的数量（成功或最终失败，不含仍 pending 的）。
    """
    if is_desktop_sqlite_backend():
        return 0
    from sqlalchemy import and_
    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(FeishuMessageEvent)
            .where(
                and_(
                    FeishuMessageEvent.source == SOURCE_HISTORY_SYNC,
                    FeishuMessageEvent.process_status == STATUS_OFFLINE_PENDING,
                    FeishuMessageEvent.retry_count < MAX_REPLAY_RETRIES,
                    or_(FeishuMessageEvent.next_retry_at.is_(None), FeishuMessageEvent.next_retry_at <= now),
                )
            )
            .order_by(FeishuMessageEvent.id)
            .limit(REPLAY_BATCH_SIZE)
        )
    ).scalars().all()
    if not rows:
        return 0
    await _log_sync(db, "INFO", f"feishu history sync replay started for {len(rows)} pending messages")
    logger.info("feishu history sync replay started for %s pending messages", len(rows))
    replayed = 0
    for event_record in rows:
        message_id = event_record.message_id
        chat_id = event_record.chat_id
        open_id = event_record.open_id
        if not chat_id:
            await _log_sync(db, "WARNING", f"replay skip message_id={message_id} missing chat_id")
            continue
        identity_row = (
            await db.execute(
                select(FeishuIdentityPool).where(
                    FeishuIdentityPool.chat_id == chat_id,
                    FeishuIdentityPool.bind_status == "bound",
                    FeishuIdentityPool.bound_user_id.isnot(None),
                ).limit(1)
            )
        ).scalar_one_or_none()
        if not identity_row or not identity_row.bound_user_id:
            await _log_sync(db, "WARNING", f"replay skip message_id={message_id} no bound identity for chat_id")
            continue
        raw = event_record.raw_payload or {}
        content_text = _extract_text_from_content(raw.get("content")) if isinstance(raw, dict) else ""
        if not content_text.strip() and message_id:
            resp = await get_message(db, message_id=message_id, tenant_key=identity_row.tenant_key)
            if resp.get("ok"):
                data = resp.get("data") or {}
                content_text = _extract_text_from_content(data.get("content"))
        if not content_text.strip():
            await _log_sync(db, "WARNING", f"replay skip message_id={message_id} empty text")
            continue
        try:
            await process_pending_history_message(
                db,
                event_record,
                bound_user_id=identity_row.bound_user_id,
                open_id=open_id or identity_row.open_id or "",
                chat_id=chat_id,
                tenant_key=identity_row.tenant_key,
                text=content_text,
                message_id=message_id or "",
            )
            replayed += 1
            await _log_sync(db, "INFO", f"offline message replay success message_id={message_id}")
            logger.info("offline message replay success message_id=%s", message_id)
            await write_audit_log(
                db,
                action="feishu_offline_message_replayed",
                actor_user_id=identity_row.bound_user_id,
                target_type="feishu_message_event",
                target_id=str(event_record.id),
                detail=f"offline message replayed success message_id={message_id}",
                metadata_json={"chat_id": chat_id, "message_id": message_id, "bound_user_id": identity_row.bound_user_id},
            )
        except Exception as e:
            if _is_ai_not_ready_error(e):
                event_record.process_status = STATUS_OFFLINE_PENDING
                event_record.retry_count = (event_record.retry_count or 0) + 1
                event_record.error_message = str(e)[:500]
                event_record.next_retry_at = _next_retry_at_for(int(event_record.retry_count or 1))
                await db.flush()
                await _log_sync(db, "INFO", f"offline message queued again (AI not ready) message_id={message_id}")
                logger.info("offline message queued again message_id=%s", message_id)
                await write_audit_log(
                    db,
                    action="feishu_offline_message_queued",
                    actor_user_id=identity_row.bound_user_id,
                    target_type="feishu_message_event",
                    target_id=str(event_record.id),
                    detail=f"queued offline message again (ai not ready) message_id={message_id}",
                    metadata_json={"chat_id": chat_id, "message_id": message_id, "bound_user_id": identity_row.bound_user_id, "next_retry_at": event_record.next_retry_at.isoformat() if event_record.next_retry_at else None},
                )
            else:
                event_record.process_status = STATUS_REPLAY_FAILED
                event_record.error_message = str(e)[:1000]
                await db.flush()
                replayed += 1
                await _log_sync(db, "ERROR", f"offline message replay failed message_id={message_id}: {e!s}")
                logger.error("offline message replay failed message_id=%s: %s", message_id, e)
                await write_audit_log(
                    db,
                    action="feishu_offline_message_replay_failed",
                    actor_user_id=identity_row.bound_user_id,
                    target_type="feishu_message_event",
                    target_id=str(event_record.id),
                    detail=f"offline message replay failed message_id={message_id}: {e!s}",
                    metadata_json={"chat_id": chat_id, "message_id": message_id, "bound_user_id": identity_row.bound_user_id, "error": str(e)},
                )
    await _log_sync(db, "INFO", f"feishu history sync replayed {replayed} messages")
    logger.info("feishu history sync replayed %s messages", replayed)
    return replayed
