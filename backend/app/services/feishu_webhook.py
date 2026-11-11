"""
飞书 webhook 处理主流程（同步执行，预留异步入口）。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
import traceback
from datetime import datetime, timezone
from typing import Any

from fastapi import Request
from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatRecord, Conversation, FeishuConversation, FeishuMessageEvent, FeishuUser, SystemLog, User
from app.services.ai_engine import chat_and_execute_tools, generate_conversation_title
from app.services.feishu_bot import send_error_message, send_receipt_card, send_text_message
from app.services.system_config_service import get_feishu_config
from app.services.feishu_identity_service import upsert_feishu_identity, resolve_bound_user_for_feishu_message
from app.services.audit_log_service import write_audit_log
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)
MAX_FEISHU_RETRY = 1
SUPPORTED_MESSAGE_TYPE = "text"


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def is_whitelist_enabled(cfg: dict[str, Any]) -> bool:
    return _as_bool(cfg.get("enable_whitelist"), False)


def _whitelist_open_ids(cfg: dict[str, Any]) -> set[str]:
    raw = str(cfg.get("whitelist_open_ids") or "")
    return {x.strip() for x in raw.split(",") if x.strip()}


def is_user_allowed(open_id: str | None, cfg: dict[str, Any]) -> bool:
    if not is_whitelist_enabled(cfg):
        return True
    if not open_id:
        return False
    return open_id in _whitelist_open_ids(cfg)


async def _log(
    db: AsyncSession,
    *,
    level: str,
    module: str,
    message: str,
    stack_trace: str | None = None,
) -> None:
    db.add(
        SystemLog(
            level=level,
            module=module,
            message=message[:2000],
            stack_trace=(stack_trace or "")[:8000] if stack_trace else None,
        )
    )
    await db.flush()


async def _get_user_display_prefix(db: AsyncSession, user_id: int | None) -> str:
    """根据系统用户 ID 取 display_name，用于飞书回复前缀；无则返回空字符串。"""
    if user_id is None:
        return ""
    try:
        user = await db.get(User, user_id)
        if user and getattr(user, "display_name", None):
            return (user.display_name or "").strip()
    except Exception:
        pass
    return ""


def _extract_text_from_message_content(content_str: str) -> str:
    try:
        payload = json.loads(content_str or "{}")
        return str(payload.get("text") or "").strip()
    except (json.JSONDecodeError, TypeError):
        return ""


def _normalize_header(headers: dict[str, str], key: str) -> str:
    return headers.get(key) or headers.get(key.lower()) or headers.get(key.upper()) or ""


def _mask_token(value: str | None, visible: int = 3) -> str:
    """脱敏显示 token：保留前 visible 位和后 visible 位，中间用 ***。不泄露完整 secret。"""
    if value is None:
        return "<none>"
    s = str(value)
    if not s:
        return "<empty>"
    if len(s) <= visible * 2:
        return "***"
    return f"{s[:visible]}***{s[-visible]}"


def _is_feishu_like_request(body: dict[str, Any]) -> bool:
    """
    仅当以下字段全部缺失时，才判定为“非飞书请求”：
    token, verification_token, type, challenge, header.event_id, event, schema。
    任一存在即视为飞书请求，避免误伤 url_verification / event_callback。
    """
    token = body.get("token")
    if token is not None and str(token).strip():
        return True
    verification_token = body.get("verification_token")
    if verification_token is not None and str(verification_token).strip():
        return True
    req_type = body.get("type")
    if req_type is not None and str(req_type).strip():
        return True
    if body.get("challenge") is not None:
        return True
    header = body.get("header") or {}
    event_id = header.get("event_id") or body.get("event_id")
    if event_id is not None and str(event_id).strip():
        return True
    if "event" in body and isinstance(body.get("event"), dict):
        return True
    schema = body.get("schema")
    if schema is not None and str(schema).strip():
        return True
    return False


def _verify_signature(
    raw_body: bytes,
    headers: dict[str, str],
    body: dict[str, Any],
    cfg: dict[str, Any],
) -> tuple[bool, str, str | None]:
    """
    校验飞书 webhook 签名/Token。
    返回 (ok, error_reason, debug_line)。
    - verification token 校验仅在 body 中存在 token 或 verification_token 时执行；
    - schema 2.0 且带 event/event_id、且无 token 的请求视为有效飞书事件，不报 mismatch，直接通过。
    """
    enable_signature_check = _as_bool(cfg.get("signature_check"), True)
    if not enable_signature_check:
        return True, "", None

    # 飞书请求体可能为 token 或 verification_token，统一取并 strip
    incoming_raw = body.get("token") or body.get("verification_token")
    incoming_token = (str(incoming_raw or "")).strip()
    expected_raw = cfg.get("verification_token")
    expected_token = (str(expected_raw or "")).strip()

    token_source = cfg.get("_verification_token_source") or "unknown"
    req_type = body.get("type") or ""
    header = body.get("header") or {}
    event_id = header.get("event_id") or body.get("event_id") or ""

    # schema 2.0 事件且无 token：飞书新版本事件体不带 token/verification_token，视为有效，不执行 token 比较
    schema_val = body.get("schema")
    is_schema2 = schema_val == "2.0" or (isinstance(schema_val, str) and schema_val.strip() == "2.0")
    has_event = "event" in body and isinstance(body.get("event"), dict)
    has_event_id = bool((header.get("event_id") or body.get("event_id") or "").strip())
    if is_schema2 and (has_event or has_event_id) and not incoming_token:
        schema2_line = (
            f"feishu webhook schema2 event without token accepted: event_id={event_id!r} schema=2.0"
        )
        return True, "", schema2_line

    app_id_raw = (cfg.get("app_id") or "")[:8] if cfg.get("app_id") else ""
    app_id_masked = f"{app_id_raw[:3]}***{app_id_raw[-3:]}" if len(app_id_raw) >= 6 else "***"

    debug_line = (
        f"feishu webhook token debug: "
        f"incoming={_mask_token(incoming_token)}(len={len(incoming_token)}) "
        f"expected={_mask_token(expected_token)}(len={len(expected_token)}) "
        f"source={token_source} stripped=true "
        f"type={req_type!r} event_id={event_id!r} app_id={app_id_masked}"
    )

    # 仅当 body 中明确存在 token 或 verification_token 时才执行 token 比较；两边都有值且 strip 后仍不相等才报 mismatch
    if expected_token and incoming_token:
        if incoming_token != expected_token:
            reason = (
                f"verification token mismatch; "
                f"token_source={token_source}; "
                f"incoming={_mask_token(incoming_token)}(len={len(incoming_token)}); "
                f"expected={_mask_token(expected_token)}(len={len(expected_token)}); "
                f"stripped=true; type={req_type!r} event_id={event_id!r}"
            )
            return False, reason, debug_line
    elif expected_token and not incoming_token:
        # body 中无 token 但配置了 expected：非 schema 2.0 时仍要求有签名头，否则拒绝
        if not _normalize_header(headers, "x-lark-signature"):
            return False, "missing verification token and signature header", debug_line

    signature = _normalize_header(headers, "x-lark-signature")
    timestamp = _normalize_header(headers, "x-lark-request-timestamp")
    nonce = _normalize_header(headers, "x-lark-request-nonce")
    if not signature:
        return True, "", None

    app_secret = str(cfg.get("app_secret") or "").strip()
    if not app_secret:
        return False, "signature enabled but FEISHU_APP_SECRET missing", None

    body_text = raw_body.decode("utf-8", errors="ignore")
    # 兼容不同签名格式：hex / base64 以及常见拼接方式
    candidates: set[str] = set()
    digest_hex = hmac.new(
        app_secret.encode("utf-8"),
        f"{timestamp}{nonce}{body_text}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    candidates.add(digest_hex)
    digest_b64 = base64.b64encode(
        hmac.new(
            app_secret.encode("utf-8"),
            f"{timestamp}{nonce}{body_text}".encode("utf-8"),
            hashlib.sha256,
        ).digest()
    ).decode("utf-8")
    candidates.add(digest_b64)
    custom_bot_sig = base64.b64encode(
        hmac.new(
            f"{timestamp}\n{app_secret}".encode("utf-8"),
            b"",
            hashlib.sha256,
        ).digest()
    ).decode("utf-8")
    candidates.add(custom_bot_sig)
    if signature in candidates:
        return True, "", None
    return False, "signature mismatch", None


def _is_group_at_message(event: dict[str, Any], text: str, cfg: dict[str, Any]) -> bool:
    bot_name = str(cfg.get("bot_name") or "")
    msg = event.get("message") or {}
    mentions = msg.get("mentions") or []
    if mentions:
        return True
    if "<at " in text:
        return True
    if bot_name and bot_name in text:
        return True
    return False


async def _upsert_feishu_user(db: AsyncSession, event: dict[str, Any]) -> FeishuUser | None:
    sender = event.get("sender") or {}
    sender_id = sender.get("sender_id") or {}
    open_id = sender_id.get("open_id") or sender.get("open_id")
    user_id = sender_id.get("user_id") or sender.get("user_id")
    union_id = sender_id.get("union_id") or sender.get("union_id")
    tenant_key = sender.get("tenant_key")
    if not open_id:
        return None

    row = (
        await db.execute(
            select(FeishuUser).where(
                or_(
                    FeishuUser.open_id == open_id,
                    FeishuUser.user_id == user_id if user_id else False,
                    FeishuUser.union_id == union_id if union_id else False,
                )
            ).limit(1)
        )
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if row is None:
        row = FeishuUser(
            open_id=open_id,
            user_id=user_id,
            union_id=union_id,
            tenant_key=tenant_key,
            name=(sender.get("sender_name") or sender.get("name")),
            avatar_url=sender.get("avatar_url"),
            last_seen_at=now,
            is_active=True,
        )
        db.add(row)
    else:
        row.user_id = user_id or row.user_id
        row.union_id = union_id or row.union_id
        row.tenant_key = tenant_key or row.tenant_key
        row.name = sender.get("sender_name") or sender.get("name") or row.name
        row.avatar_url = sender.get("avatar_url") or row.avatar_url
        row.is_active = True
        row.last_seen_at = now
        row.updated_at = now
    await db.flush()
    return row


async def _process_one_feishu_message_core(
    db: AsyncSession,
    *,
    open_id: str,
    chat_id: str,
    tenant_key: str | None,
    text: str,
    message_id: str | None,
    bound_user_id: int,
    event_record: FeishuMessageEvent,
    conversation_type: str = "p2p",
    final_process_status: str = "success",
) -> int | None:
    """
    单条飞书消息的通用处理：会话获取/创建、上下文构建、AI 调用、回发飞书、写入 ChatRecord、更新 event_record。
    供 webhook 实时处理与 history_sync 离线补偿共用。返回 source_conversation_id，供调用方写 return_details。
    """
    feishu_conv = await _get_or_create_feishu_conversation(
        db,
        open_id=open_id,
        chat_id=chat_id,
        conversation_type=conversation_type,
        owner_user_id=bound_user_id,
    )
    if conversation_type == "p2p" and feishu_conv.source_conversation_id:
        logger.info(
            "feishu.sync: matched bound user and synced to web conversation conv_id=%s owner_user_id=%s open_id=%s",
            feishu_conv.source_conversation_id,
            bound_user_id,
            (open_id[:6] + "***") if open_id and len(open_id) > 6 else (open_id or ""),
        )
    messages = await _build_conversation_messages(
        db,
        source_conversation_id=feishu_conv.source_conversation_id,
        user_text=text,
    )
    feishu_source = "feishu_private" if conversation_type == "p2p" else "feishu_group"
    out = await chat_and_execute_tools(
        db,
        messages,
        operator_source=feishu_source,
        operator_external_id=open_id,
        operator_user_id=bound_user_id,
    )
    execution_results = out.get("execution_results") or []
    assistant_message = out.get("message") or {}
    assistant_text = ""
    if isinstance(assistant_message, dict):
        assistant_text = (assistant_message.get("content") or "").strip()
    if not assistant_text:
        assistant_text = "已根据您的指令处理。"
    card_ok = await send_receipt_card(
        db,
        receive_id=chat_id,
        receive_id_type="chat_id",
        execution_results=execution_results,
        assistant_text=assistant_text,
        operator_external_id=open_id,
        event_id=None,
        open_id=open_id,
        chat_id=chat_id,
        tenant_key=tenant_key,
    )
    response_message_id = None
    if not card_ok:
        text_result = await send_text_message(
            db,
            receive_id=chat_id,
            receive_id_type="chat_id",
            text=assistant_text,
            event_id=None,
            open_id=open_id,
            chat_id=chat_id,
            tenant_key=tenant_key,
        )
        response_message_id = text_result.get("message_id") if isinstance(text_result, dict) else None
    chat_rec = ChatRecord(
        user_message=text,
        ai_response=assistant_text,
        tool_calls={"execution_results": execution_results},
        channel="feishu",
        external_user_id=open_id,
        external_chat_id=chat_id,
        source_conversation_id=feishu_conv.source_conversation_id,
        external_message_id=response_message_id,
        incoming_message_id=message_id,
    )
    try:
        db.add(chat_rec)
        await db.flush()
    except IntegrityError:
        db.expunge(chat_rec)
        logger.debug(
            "feishu chat record already exists for incoming_message_id=%s, skip duplicate write",
            message_id,
        )
    feishu_conv.last_message_id = message_id
    feishu_conv.updated_at = datetime.now(timezone.utc)
    if feishu_conv.source_conversation_id:
        source_conv = await db.get(Conversation, feishu_conv.source_conversation_id)
        if source_conv:
            source_conv.updated_at = datetime.now(timezone.utc)
            if conversation_type == "p2p":
                await _log(
                    db,
                    level="INFO",
                    module="feishu.auth",
                    message=f"synced feishu message into web conversation conv_id={feishu_conv.source_conversation_id} bound_user_id={bound_user_id}",
                )
                logger.info(
                    "feishu.sync: appended feishu user message and assistant reply to synced conversation conv_id=%s",
                    feishu_conv.source_conversation_id,
                )
                await write_audit_log(
                    db,
                    action="feishu_private_message_synced",
                    actor_user_id=bound_user_id,
                    target_type="conversation",
                    target_id=str(feishu_conv.source_conversation_id),
                    detail="feishu private message and reply synced to web conversation",
                    metadata_json={"conversation_id": feishu_conv.source_conversation_id},
                )
            if source_conv.title in ("飞书私聊会话", "飞书群聊会话", "新对话"):
                title = await generate_conversation_title(db, messages[-4:])
                source_conv.title = title[:256]
                feishu_conv.title = source_conv.title
    await db.flush()
    event_record.response_message_id = response_message_id
    event_record.process_status = final_process_status
    event_record.error_message = None
    await db.flush()
    return feishu_conv.source_conversation_id


async def _get_or_create_feishu_conversation(
    db: AsyncSession,
    *,
    open_id: str,
    chat_id: str | None,
    conversation_type: str,
    owner_user_id: int | None = None,
) -> FeishuConversation:
    stmt = select(FeishuConversation).where(
        FeishuConversation.feishu_open_id == open_id,
        FeishuConversation.conversation_type == conversation_type,
    )
    if conversation_type == "group_at":
        stmt = stmt.where(FeishuConversation.feishu_chat_id == chat_id)
    row = (await db.execute(stmt.limit(1))).scalar_one_or_none()
    if row:
        # 兼容旧数据：历史上可能存在 source_conversation_id 为空的映射记录，
        # 会导致 chat_records.source_conversation_id 为空、对话归属链路断裂。
        if row.source_conversation_id is None:
            conv_title = "飞书私聊会话" if conversation_type == "p2p" else "飞书群聊会话"
            conv_source = "feishu_private" if conversation_type == "p2p" else "feishu_group"
            effective_owner: int | None = owner_user_id if conversation_type == "p2p" else None
            source = Conversation(
                title=conv_title[:256],
                owner_user_id=effective_owner,
                source=conv_source,
            )
            db.add(source)
            await db.flush()
            row.source_conversation_id = source.id
            row.updated_at = datetime.now(timezone.utc)
            await db.flush()
        if conversation_type == "p2p" and row.source_conversation_id and owner_user_id:
            await _log(
                db,
                level="INFO",
                module="feishu.auth",
                message=f"reused feishu_private conversation for bound_user_id={owner_user_id} conv_id={row.source_conversation_id}",
            )
        return row

    conv_title = "飞书私聊会话" if conversation_type == "p2p" else "飞书群聊会话"
    conv_source = "feishu_private" if conversation_type == "p2p" else "feishu_group"
    effective_owner: int | None = owner_user_id if conversation_type == "p2p" else None
    source = Conversation(
        title=conv_title[:256],
        owner_user_id=effective_owner,
        source=conv_source,
    )
    db.add(source)
    await db.flush()
    row = FeishuConversation(
        feishu_open_id=open_id,
        feishu_chat_id=chat_id,
        conversation_type=conversation_type,
        source_conversation_id=source.id,
        title=conv_title,
        is_active=True,
    )
    db.add(row)
    await db.flush()
    if conversation_type == "p2p" and effective_owner:
        await _log(
            db,
            level="INFO",
            module="feishu.auth",
            message=f"created feishu_private conversation for bound_user_id={effective_owner} conv_id={source.id}",
        )
        await write_audit_log(
            db,
            action="feishu_private_conversation_created",
            actor_user_id=effective_owner,
            target_type="conversation",
            target_id=str(source.id),
            detail="created feishu private sync conversation",
            metadata_json={"conversation_id": source.id},
        )
        logger.info(
            "feishu.sync: created feishu private conversation conv_id=%s owner_user_id=%s",
            source.id,
            effective_owner,
        )
    return row


async def _build_conversation_messages(
    db: AsyncSession,
    *,
    source_conversation_id: int | None,
    user_text: str,
) -> list[dict[str, str]]:
    if not source_conversation_id:
        return [{"role": "user", "content": user_text}]
    rows = list(
        (
            await db.execute(
                select(ChatRecord)
                .where(ChatRecord.source_conversation_id == source_conversation_id)
                .order_by(ChatRecord.timestamp.desc(), ChatRecord.id.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    rows.reverse()
    messages: list[dict[str, str]] = []
    for r in rows:
        if r.user_message:
            messages.append({"role": "user", "content": r.user_message})
        if r.ai_response:
            messages.append({"role": "assistant", "content": r.ai_response})
    messages.append({"role": "user", "content": user_text})
    return messages


async def _get_or_create_event_record(
    db: AsyncSession,
    *,
    body: dict[str, Any],
    event: dict[str, Any],
) -> tuple[FeishuMessageEvent, bool]:
    header = body.get("header") or {}
    event_id = header.get("event_id") or body.get("event_id")
    msg = event.get("message") or {}
    message_id = msg.get("message_id")
    existing = None
    if event_id:
        existing = (
            await db.execute(
                select(FeishuMessageEvent).where(FeishuMessageEvent.event_id == event_id).limit(1)
            )
        ).scalar_one_or_none()
    if existing is None and message_id:
        existing = (
            await db.execute(
                select(FeishuMessageEvent).where(FeishuMessageEvent.message_id == message_id).limit(1)
            )
        ).scalar_one_or_none()

    if existing:
        if existing.process_status in ("success", "replay_success", "processing", "ignored", "pending", "offline_pending", "history_pending"):
            return existing, True
        if existing.retry_count >= MAX_FEISHU_RETRY:
            return existing, True
        existing.process_status = "processing"
        existing.retry_count = int(existing.retry_count or 0) + 1
        existing.updated_at = datetime.now(timezone.utc)
        existing.error_message = None
        await db.flush()
        return existing, False

    record = FeishuMessageEvent(
        event_id=event_id,
        message_id=message_id,
        chat_id=msg.get("chat_id"),
        open_id=((event.get("sender") or {}).get("sender_id") or {}).get("open_id"),
        event_type=str((header.get("event_type") or body.get("type") or "unknown")),
        message_type=msg.get("message_type"),
        raw_payload=body,
        process_status="processing",
        retry_count=0,
    )
    db.add(record)
    try:
        await db.flush()
        return record, False
    except IntegrityError:
        await db.rollback()
        result = await db.execute(
            select(FeishuMessageEvent).where(FeishuMessageEvent.event_id == event_id).limit(1)
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            return existing, True
        result = await db.execute(
            select(FeishuMessageEvent).where(FeishuMessageEvent.message_id == message_id).limit(1)
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            return existing, True
        raise


async def process_feishu_event_sync(
    db: AsyncSession,
    request: Request,
    body: dict[str, Any],
    raw_body: bytes,
    *,
    skip_signature_check: bool = False,
    return_details: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()
    event_id: str | None = None
    message_id: str | None = None
    open_id: str | None = None
    chat_id: str | None = None
    final_status = "received"

    # 第 1 条：入口日志，任何请求都会先打，避免静默 return
    has_token = body.get("token") is not None and bool(str(body.get("token") or "").strip())
    has_verification_token = body.get("verification_token") is not None and bool(
        str(body.get("verification_token") or "").strip()
    )
    entry_type = body.get("type")
    entry_type_str = repr(entry_type) if entry_type is not None else "absent"
    challenge_present = "challenge" in body
    entry_event_id = (body.get("header") or {}).get("event_id") or body.get("event_id")
    entry_event_id_str = repr(entry_event_id) if entry_event_id is not None else "absent"
    entry_schema = body.get("schema")
    entry_schema_str = repr(entry_schema) if entry_schema is not None else "absent"
    has_event = "event" in body and isinstance(body.get("event"), dict)
    raw_len = len(raw_body) if raw_body else 0
    await _log(
        db,
        level="INFO",
        module="feishu.webhook",
        message=(
            f"feishu webhook entry: has_token={has_token} has_verification_token={has_verification_token} "
            f"type={entry_type_str} challenge={'present' if challenge_present else 'absent'} "
            f"event_id={entry_event_id_str} schema={entry_schema_str} has_event={has_event} raw_len={raw_len}"
        ),
    )

    # 非飞书请求：仅当 token/verification_token/type/challenge/header.event_id/event/schema 全部缺失时才判定
    if not _is_feishu_like_request(body):
        safe_token = _mask_token(body.get("token") or body.get("verification_token"))
        safe_type = body.get("type") or ""
        safe_header = body.get("header") or {}
        safe_event_id = safe_header.get("event_id") or body.get("event_id") or ""
        await _log(
            db,
            level="INFO",
            module="feishu.webhook",
            message=(
                f"feishu webhook ignored non-feishu request: "
                f"token={safe_token} type={safe_type!r} event_id={safe_event_id!r} reason=no_feishu_fields"
            ),
        )
        raise HTTPException(status_code=400, detail="not a feishu event request")

    # challenge 请求：优先识别，避免被误判
    if "challenge" in body:
        await _log(
            db,
            level="INFO",
            module="feishu.webhook",
            message=f"feishu webhook challenge: type={body.get('type')!r} challenge=present",
        )
        return {"challenge": body["challenge"]}

    cfg = await get_feishu_config(db)
    # 受控调试日志：仅打印与排查相关的字段，不输出完整 secret
    safe_type = body.get("type") or ""
    safe_challenge = "present" if "challenge" in body else "absent"
    safe_token_masked = _mask_token(body.get("token") or body.get("verification_token"))
    safe_header = body.get("header") or {}
    safe_event_id = safe_header.get("event_id") or body.get("event_id") or ""
    await _log(
        db,
        level="INFO",
        module="feishu.webhook",
        message=(
            f"feishu webhook request: type={safe_type!r} challenge={safe_challenge} "
            f"token_masked={safe_token_masked} event_id={safe_event_id!r}"
        ),
    )
    ok, reason, debug_line = _verify_signature(raw_body, dict(request.headers), body, cfg)
    if debug_line:
        await _log(db, level="INFO", module="feishu.webhook", message=debug_line)
    if not ok and not skip_signature_check:
        # incoming 为空时的 token mismatch 记为 WARNING，避免干扰真实排障；仅当两边都有值且 strip 后仍不一致时记 ERROR
        is_empty_incoming_mismatch = (
            "verification token mismatch" in reason and "incoming=<empty>(len=0)" in reason
        )
        log_level = "WARNING" if is_empty_incoming_mismatch else "ERROR"
        await _log(db, level=log_level, module="feishu.webhook", message=f"signature check failed: {reason}")
        return {"code": 403, "msg": "invalid signature"}

    event = body.get("event") or {}
    event_type = (body.get("header") or {}).get("event_type") or body.get("type")
    event_id = (body.get("header") or {}).get("event_id") or body.get("event_id")
    if event_type and "message" not in str(event_type):
        if return_details:
            return {
                "success": True,
                "process_status": "ignored",
                "ai_reply": "",
                "execution_results": [],
                "conversation_id": None,
                "feishu_event_record_id": None,
                "error": "non-message event ignored",
            }
        return {"ok": True}
    if not isinstance(event, dict) or not event:
        return {"ok": True}

    event_record, duplicated = await _get_or_create_event_record(db, body=body, event=event)
    if duplicated:
        dup_event_id = (body.get("header") or {}).get("event_id") or body.get("event_id") or "n/a"
        await _log(
            db,
            level="INFO",
            module="feishu.webhook",
            message=f"duplicate feishu event skipped event_id={dup_event_id}",
        )
        if return_details:
            return {
                "success": True,
                "process_status": event_record.process_status,
                "ai_reply": "",
                "execution_results": [],
                "conversation_id": None,
                "feishu_event_record_id": event_record.id,
                "error": "duplicated event",
            }
        return {"ok": True, "duplicated": True}

    msg = event.get("message") or {}
    sender = event.get("sender") or {}
    sender_id = sender.get("sender_id") or {}
    sender_type = sender.get("sender_type")
    chat_id = msg.get("chat_id")
    chat_type = msg.get("chat_type") or "group"
    open_id = sender_id.get("open_id")
    message_id = msg.get("message_id")
    message_type = msg.get("message_type")
    event_tenant_key = sender.get("tenant_key") or (body.get("header") or {}).get("tenant_key") or None
    if event_tenant_key is not None:
        await _log(
            db,
            level="INFO",
            module="feishu.webhook",
            message=f"event tenant_key extracted tenant_key={event_tenant_key}",
        )
    # 飞书身份采集（待绑定池）：不阻塞主流程，采集失败仅打日志
    try:
        if open_id or (sender_id.get("union_id") if isinstance(sender.get("sender_id"), dict) else None):
            identity = await upsert_feishu_identity(
                db,
                tenant_key=event_tenant_key,
                open_id=open_id,
                union_id=sender_id.get("union_id") if isinstance(sender_id, dict) else None,
                feishu_user_id=sender_id.get("user_id") if isinstance(sender_id, dict) else None,
                chat_id=chat_id,
                message_id=message_id,
                event_id=event_id,
                sender_name=sender.get("sender_name") or sender.get("name"),
                raw_payload=body,
            )
            if identity:
                await write_audit_log(
                    db,
                    action="feishu_identity_captured",
                    target_type="feishu_identity",
                    target_id=str(identity.id),
                    detail=f"tenant_key={event_tenant_key or ''} open_id={open_id or ''} union_id={sender_id.get('union_id') if isinstance(sender_id, dict) else ''}",
                    metadata_json={"identity_pool_id": identity.id, "bind_status": identity.bind_status},
                )
                logger.info(
                    "feishu.identity: captured tenant_key=%s open_id=%s union_id=%s bind_status=%s identity_pool_id=%s",
                    event_tenant_key or "",
                    open_id or "",
                    (sender_id.get("union_id") if isinstance(sender_id, dict) else "") or "",
                    identity.bind_status,
                    identity.id,
                )
        else:
            logger.warning(
                "feishu.identity: skip capture, missing open_id and union_id event_id=%s",
                event_id or "",
            )
    except Exception as e:
        logger.warning(
            "feishu.identity: capture failed (non-blocking) event_id=%s reason=%s",
            event_id or "",
            str(e),
        )
    text = _extract_text_from_message_content(msg.get("content", "{}"))
    ai_started: float | None = None
    ai_duration_ms: int | None = None
    tool_count = 0

    try:
        if sender_type == "app":
            event_record.process_status = "ignored"
            final_status = "ignored"
            await db.flush()
            if return_details:
                return {
                    "success": True,
                    "process_status": "ignored",
                    "ai_reply": "",
                    "execution_results": [],
                    "conversation_id": None,
                    "feishu_event_record_id": event_record.id,
                    "error": "sender_type=app",
                }
            return {"ok": True}

        if message_type != SUPPORTED_MESSAGE_TYPE:
            if chat_id:
                await _log(
                    db,
                    level="INFO",
                    module="feishu.webhook",
                    message=(
                        f"about to send feishu message tenant_key={event_tenant_key or ''} "
                        f"app_id={(cfg or {}).get('app_id') or ''} chat_id={chat_id} open_id={open_id or ''} event_id={event_id or ''}"
                    ),
                )
                await send_text_message(
                    db,
                    receive_id=chat_id,
                    receive_id_type="chat_id",
                    text="当前仅支持文本消息，请发送文本内容。",
                    event_id=event_id,
                    open_id=open_id,
                    chat_id=chat_id,
                    tenant_key=event_tenant_key,
                )
            event_record.process_status = "ignored"
            final_status = "ignored"
            await db.flush()
            if return_details:
                return {
                    "success": True,
                    "process_status": "ignored",
                    "ai_reply": "",
                    "execution_results": [],
                    "conversation_id": None,
                    "feishu_event_record_id": event_record.id,
                    "error": "unsupported message type",
                }
            return {"ok": True}

        if chat_type != "p2p" and not _is_group_at_message(event, text, cfg):
            event_record.process_status = "ignored"
            final_status = "ignored"
            await db.flush()
            if return_details:
                return {
                    "success": True,
                    "process_status": "ignored",
                    "ai_reply": "",
                    "execution_results": [],
                    "conversation_id": None,
                    "feishu_event_record_id": event_record.id,
                    "error": "group message without @bot",
                }
            return {"ok": True}

        if not is_user_allowed(open_id, cfg):
            event_record.process_status = "ignored"
            event_record.error_message = "not in whitelist"
            final_status = "ignored"
            await db.flush()
            if chat_id:
                await _log(
                    db,
                    level="INFO",
                    module="feishu.webhook",
                    message=(
                        f"about to send feishu message tenant_key={event_tenant_key or ''} "
                        f"app_id={(cfg or {}).get('app_id') or ''} chat_id={chat_id} open_id={open_id or ''} event_id={event_id or ''}"
                    ),
                )
                await send_text_message(
                    db,
                    receive_id=chat_id,
                    receive_id_type="chat_id",
                    text="当前账号暂未开通使用权限，请联系管理员。",
                    event_id=event_id,
                    open_id=open_id,
                    chat_id=chat_id,
                    tenant_key=event_tenant_key,
                )
            await _log(
                db,
                level="INFO",
                module="feishu.webhook",
                message=f"whitelist blocked open_id={open_id} chat_id={chat_id} message_id={message_id}",
            )
            if return_details:
                return {
                    "success": True,
                    "process_status": "ignored",
                    "ai_reply": "",
                    "execution_results": [],
                    "conversation_id": None,
                    "feishu_event_record_id": event_record.id,
                    "error": "not in whitelist",
                }
            return {"ok": True}

        if not open_id or not chat_id or not text:
            event_record.process_status = "failed"
            event_record.error_message = "missing open_id/chat_id/text"
            final_status = "failed"
            await db.flush()
            await _log(
                db,
                level="ERROR",
                module="feishu.webhook",
                message=f"missing required data open_id={open_id} chat_id={chat_id} message_id={message_id}",
            )
            if return_details:
                return {
                    "success": False,
                    "process_status": "failed",
                    "ai_reply": "",
                    "execution_results": [],
                    "conversation_id": None,
                    "feishu_event_record_id": event_record.id,
                    "error": "missing open_id/chat_id/text",
                }
            return {"ok": True}

        feishu_user = await _upsert_feishu_user(db, event)
        if not feishu_user:
            event_record.process_status = "failed"
            event_record.error_message = "cannot resolve feishu user"
            final_status = "failed"
            await db.flush()
            if return_details:
                return {
                    "success": False,
                    "process_status": "failed",
                    "ai_reply": "",
                    "execution_results": [],
                    "conversation_id": None,
                    "feishu_event_record_id": event_record.id,
                    "error": "cannot resolve feishu user",
                }
            return {"ok": True}

        # 飞书消息归属：仅已绑定用户进入业务主流程（不依赖 Web 登录态，仅查 feishu_identity_pool）
        # 私聊(p2p)：bound_user_id 作为会话 owner，消息同步到该用户 Web 会话；群聊(group_at)：会话不归属个人。
        union_id = sender_id.get("union_id") if isinstance(sender_id, dict) else None
        identity, bound_user_id = await resolve_bound_user_for_feishu_message(
            db,
            open_id=open_id,
            union_id=union_id,
            tenant_key=event_tenant_key,
        )
        if identity is not None and identity.bind_status == "ignored":
            if chat_type == "group":
                await _log(db, level="INFO", module="feishu.auth", message="group actor ignored, skipped")
            await send_text_message(
                db,
                receive_id=chat_id,
                receive_id_type="chat_id",
                text="该账号未启用飞书绑定，请联系管理员。",
                event_id=event_id,
                open_id=open_id,
                chat_id=chat_id,
                tenant_key=event_tenant_key,
            )
            event_record.process_status = "ignored"
            final_status = "ignored"
            await db.flush()
            if return_details:
                return {
                    "success": False,
                    "process_status": "ignored",
                    "ai_reply": "",
                    "execution_results": [],
                    "conversation_id": None,
                    "feishu_event_record_id": event_record.id,
                    "error": "feishu identity ignored",
                }
            return {"ok": True}
        if bound_user_id is None:
            if chat_type == "group":
                await _log(db, level="INFO", module="feishu.auth", message="group actor not bound, skipped")
            await write_audit_log(
                db,
                action="feishu_identity_unbound_message",
                target_type="feishu_identity",
                target_id=str(identity.id) if identity else None,
                detail="飞书消息发送者未绑定系统用户",
                metadata_json={"open_id": open_id, "tenant_key": event_tenant_key, "union_id": union_id},
            )
            await send_text_message(
                db,
                receive_id=chat_id,
                receive_id_type="chat_id",
                text="你的飞书账号尚未绑定系统账号，请联系管理员在后台完成绑定后再使用。",
                event_id=event_id,
                open_id=open_id,
                chat_id=chat_id,
                tenant_key=event_tenant_key,
            )
            event_record.process_status = "ignored"
            final_status = "ignored"
            await db.flush()
            if return_details:
                return {
                    "success": False,
                    "process_status": "ignored",
                    "ai_reply": "",
                    "execution_results": [],
                    "conversation_id": None,
                    "feishu_event_record_id": event_record.id,
                    "error": "feishu identity unbound",
                }
            return {"ok": True}
        await write_audit_log(
            db,
            action="feishu_identity_matched_user",
            actor_user_id=bound_user_id,
            target_type="feishu_identity",
            target_id=str(identity.id) if identity else "",
            detail=f"飞书消息归属到用户 id={bound_user_id}",
            metadata_json={"bound_user_id": bound_user_id, "open_id": open_id, "tenant_key": event_tenant_key},
        )
        logger.info(
            "feishu.identity: matched bound user open_id=%s bound_user_id=%s",
            open_id or "",
            bound_user_id,
        )
        await _log(
            db,
            level="INFO",
            module="feishu.auth",
            message=f"matched bound user from feishu identity without web session bound_user_id={bound_user_id} open_id={open_id or ''} chat_type={chat_type}",
        )
        if chat_type == "p2p":
            await _log(
                db,
                level="INFO",
                module="feishu.auth",
                message=f"processing feishu private message for bound_user_id={bound_user_id} (no web login required)",
            )
        else:
            await _log(
                db,
                level="INFO",
                module="feishu.auth",
                message=f"resolved group actor bound_user_id={bound_user_id}",
            )
            await _log(
                db,
                level="INFO",
                module="feishu.auth",
                message=f"processing group mention message for bound_user_id={bound_user_id}",
            )

        conv_type = "p2p" if chat_type == "p2p" else "group_at"
        source_conv_id = await _process_one_feishu_message_core(
            db,
            open_id=open_id,
            chat_id=chat_id,
            tenant_key=event_tenant_key,
            text=text,
            message_id=message_id,
            bound_user_id=bound_user_id,
            event_record=event_record,
            conversation_type=conv_type,
        )
        final_status = "success"
        if return_details:
            return {
                "success": True,
                "process_status": "success",
                "ai_reply": "",  # already sent in core
                "execution_results": [],
                "conversation_id": source_conv_id,
                "feishu_event_record_id": event_record.id,
            }
        return {"ok": True}
    except Exception as e:
        event_record.process_status = "failed"
        final_status = "failed"
        event_record.error_message = str(e)[:1000]
        event_record.updated_at = datetime.now(timezone.utc)
        await db.flush()
        if chat_id:
            await _log(
                db,
                level="INFO",
                module="feishu.webhook",
                message=(
                    f"about to send feishu message tenant_key={event_tenant_key or ''} "
                    f"app_id={(cfg or {}).get('app_id') or ''} chat_id={chat_id} open_id={open_id or ''} event_id={event_id or ''}"
                ),
            )
            await send_error_message(
                db,
                receive_id=chat_id,
                receive_id_type="chat_id",
                text="本次处理失败，请稍后重试",
                event_id=event_id,
                open_id=open_id,
                chat_id=chat_id,
                tenant_key=event_tenant_key,
            )
        await _log(
            db,
            level="ERROR",
            module="feishu.webhook",
            message=f"process failed open_id={open_id} chat_id={chat_id} message_id={message_id}: {e!s}",
            stack_trace="".join(traceback.format_exception(type(e), e, e.__traceback__)),
        )
        if return_details:
            return {
                "success": False,
                "process_status": "failed",
                "ai_reply": "",
                "execution_results": [],
                "conversation_id": None,
                "feishu_event_record_id": event_record.id if event_record else None,
                "error": str(e),
            }
        return {"ok": True}
    finally:
        total_duration_ms = int((time.perf_counter() - started) * 1000)
        try:
            event_record.duration_ms = total_duration_ms
            event_record.updated_at = datetime.now(timezone.utc)
            await db.flush()
        except Exception:
            pass
        await _log(
            db,
            level="INFO",
            module="feishu.webhook",
            message=(
                f"event_id={event_id} message_id={message_id} open_id={open_id} chat_id={chat_id} "
                f"process_status={final_status} total_duration_ms={total_duration_ms} "
                f"ai_duration_ms={ai_duration_ms if ai_duration_ms is not None else -1} tool_count={tool_count}"
            ),
        )


def _request_like(headers: dict[str, str]) -> Any:
    """构造仅含 headers 的 request-like 对象，供后台任务签名校验使用。"""
    class _Req:
        pass

    req = _Req()
    req.headers = headers or {}
    return req


async def process_feishu_event_in_background(
    body: dict[str, Any],
    raw_body: bytes,
    headers: dict[str, str],
) -> None:
    """
    后台任务入口：自建 DB session，不复用请求作用域的 session。
    用于 webhook 快速返回 200 后异步执行 AI 与飞书回执。
    """
    async with AsyncSessionLocal() as db:
        try:
            req = _request_like(headers)
            await process_feishu_event_async(db, req, body, raw_body)
            await db.commit()
        except Exception:
            await db.rollback()
            raise


async def process_feishu_event_async(
    db: AsyncSession,
    request: Request,
    body: dict[str, Any],
    raw_body: bytes,
    *,
    skip_signature_check: bool = False,
    return_details: bool = False,
) -> dict[str, Any]:
    """
    异步入口预留：当前仍复用同步处理。
    后续接入 Celery/RQ 时可在此处投递任务。
    """
    return await process_feishu_event_sync(
        db,
        request,
        body,
        raw_body,
        skip_signature_check=skip_signature_check,
        return_details=return_details,
    )
