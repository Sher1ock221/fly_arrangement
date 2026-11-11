"""
飞书相关 HTTP 路由：仅非桌面 SQLite（服务端）部署时由 main 注册；桌面单机不加载本模块。
"""
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, BackgroundTasks
from fastapi.responses import HTMLResponse
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.models import FeishuMessageEvent, FeishuToken, SystemLog
from app.schemas.feishu import FeishuConfigRead, FeishuConfigTestResult, FeishuConfigUpdate
from app.services.feishu_webhook import process_feishu_event_async, process_feishu_event_in_background
from app.services.system_config_service import (
    build_feishu_urls,
    get_feishu_config,
    is_non_public_base_url,
    normalize_public_api_base_url,
    save_feishu_config,
)

router = APIRouter(prefix="/ai", tags=["ai-feishu"])


def _analyze_public_base_url(url: str | None) -> tuple[bool, list[str]]:
    warnings: list[str] = []
    normalized = normalize_public_api_base_url(url)
    if not normalized:
        return False, warnings
    if not (normalized.startswith("http://") or normalized.startswith("https://")):
        warnings.append("PUBLIC_API_BASE_URL 不是合法的 http/https 地址")
        return False, warnings
    if is_non_public_base_url(normalized):
        warnings.append("PUBLIC_API_BASE_URL 指向 localhost/内网地址，飞书公网回调可能不可用")
    try:
        parsed = urlparse(normalized)
        if not parsed.hostname:
            warnings.append("PUBLIC_API_BASE_URL 缺少有效主机名")
            return False, warnings
    except Exception:
        return False, warnings
    return True, warnings


@router.post("/feishu-webhook")
async def feishu_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    飞书事件 Webhook：收到用户消息后快速返回 200，后台异步执行 AI 与飞书回执。
    飞书配置：事件订阅请求 URL 指向本接口；需配置 FEISHU_APP_ID / FEISHU_APP_SECRET。
    """
    raw_body = await request.body()
    try:
        body = json.loads(raw_body.decode("utf-8"))
    except Exception:
        body = {}
    if isinstance(body, dict) and "challenge" in body:
        return await process_feishu_event_async(db, request, body, raw_body)
    headers = dict(request.headers)
    background_tasks.add_task(process_feishu_event_in_background, body, raw_body, headers)
    return {"ok": True}


@router.get("/feishu-status")
async def feishu_status(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """飞书接入只读状态：配置状态、token、事件统计、最近错误。"""
    try:
        cfg = await get_feishu_config(db)
        now = datetime.now(timezone.utc)
        day_ago = now - timedelta(hours=24)

        token = (
            await db.execute(
                select(FeishuToken).where(FeishuToken.token_type == "tenant_access_token").limit(1)
            )
        ).scalar_one_or_none()
        token_expire_at = token.expire_at if token else None
        token_exists = token is not None
        token_expired = bool(token_expire_at and token_expire_at <= now)
        token_remain_seconds = int((token_expire_at - now).total_seconds()) if token_expire_at else None

        total_events = int((await db.execute(select(func.count(FeishuMessageEvent.id)))).scalar_one() or 0)
        success_count = int(
            (
                await db.execute(
                    select(func.count(FeishuMessageEvent.id)).where(FeishuMessageEvent.process_status == "success")
                )
            ).scalar_one()
            or 0
        )
        failed_count = int(
            (
                await db.execute(
                    select(func.count(FeishuMessageEvent.id)).where(FeishuMessageEvent.process_status == "failed")
                )
            ).scalar_one()
            or 0
        )
        ignored_count = int(
            (
                await db.execute(
                    select(func.count(FeishuMessageEvent.id)).where(FeishuMessageEvent.process_status == "ignored")
                )
            ).scalar_one()
            or 0
        )
        processing_count = int(
            (
                await db.execute(
                    select(func.count(FeishuMessageEvent.id)).where(FeishuMessageEvent.process_status == "processing")
                )
            ).scalar_one()
            or 0
        )
        last_24h_events = int(
            (
                await db.execute(
                    select(func.count(FeishuMessageEvent.id)).where(FeishuMessageEvent.created_at >= day_ago)
                )
            ).scalar_one()
            or 0
        )
        last_24h_failed = int(
            (
                await db.execute(
                    select(func.count(FeishuMessageEvent.id)).where(
                        FeishuMessageEvent.created_at >= day_ago,
                        FeishuMessageEvent.process_status == "failed",
                    )
                )
            ).scalar_one()
            or 0
        )
        failed_items = list(
            (
                await db.execute(
                    select(FeishuMessageEvent)
                    .where(FeishuMessageEvent.process_status == "failed")
                    .order_by(desc(FeishuMessageEvent.created_at), desc(FeishuMessageEvent.id))
                    .limit(10)
                )
            )
            .scalars()
            .all()
        )
        recent_errors = list(
            (
                await db.execute(
                    select(SystemLog)
                    .where(SystemLog.level == "ERROR", SystemLog.module.ilike("feishu.%"))
                    .order_by(desc(SystemLog.timestamp), desc(SystemLog.id))
                    .limit(10)
                )
            )
            .scalars()
            .all()
        )
        missing_items: list[str] = []
        if not cfg.get("app_id_configured"):
            missing_items.append("app_id")
        if not cfg.get("app_secret_configured"):
            missing_items.append("app_secret")
        if not cfg.get("verification_token_configured"):
            missing_items.append("verification_token")
        if not cfg.get("public_api_base_url_configured"):
            missing_items.append("public_api_base_url")
        diagnostics_warnings: list[str] = []
        _, base_url_warnings = _analyze_public_base_url(cfg.get("public_api_base_url"))
        diagnostics_warnings.extend(base_url_warnings)
        if bool(cfg.get("signature_check")) and not cfg.get("verification_token_configured"):
            diagnostics_warnings.append("已开启签名校验，但缺少 Verification Token")
        if bool(cfg.get("enable_whitelist")) and int(cfg.get("whitelist_count") or 0) == 0:
            diagnostics_warnings.append("已开启白名单，但 whitelist_open_ids 为空")
        is_ready_for_webhook = (
            cfg.get("app_id_configured")
            and cfg.get("app_secret_configured")
            and cfg.get("verification_token_configured")
            and cfg.get("public_api_base_url_configured")
        )
        is_ready_for_card_undo = bool(cfg.get("public_api_base_url_configured"))

        return {
            "ok": True,
            "config_source": cfg.get("config_source", "env"),
            "basic_config": {
                "app_id_configured": bool(cfg.get("app_id_configured")),
                "app_secret_configured": bool(cfg.get("app_secret_configured")),
                "verification_token_configured": bool(cfg.get("verification_token_configured")),
                "encrypt_key_configured": bool(cfg.get("encrypt_key_configured")),
                "signature_check_enabled": bool(cfg.get("signature_check")),
                "whitelist_enabled": bool(cfg.get("enable_whitelist")),
                "public_api_base_url": cfg.get("public_api_base_url"),
                "webhook_path": "/api/v1/ai/feishu-webhook",
                "undo_path": "/api/v1/ai/feishu-undo",
            },
            "capabilities": {
                "challenge_supported": True,
                "signature_check_enabled": bool(cfg.get("signature_check")),
                "group_at_supported": True,
                "p2p_supported": True,
                "undo_supported": True,
                "async_mode": False,
            },
            "token_status": {
                "exists": token_exists,
                "expire_at": token_expire_at.isoformat() if token_expire_at else None,
                "is_expired": token_expired,
                "remain_seconds": token_remain_seconds,
            },
            "event_stats": {
                "total": total_events,
                "success": success_count,
                "failed": failed_count,
                "ignored": ignored_count,
                "processing": processing_count,
                "last_24h_total": last_24h_events,
                "last_24h_failed": last_24h_failed,
            },
            "failed_events": [
                {
                    "id": e.id,
                    "event_id": e.event_id,
                    "message_id": e.message_id,
                    "chat_id": e.chat_id,
                    "open_id": e.open_id,
                    "error_message": e.error_message,
                    "retry_count": e.retry_count,
                    "duration_ms": e.duration_ms,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in failed_items
            ],
            "recent_webhook_errors": [
                {
                    "id": x.id,
                    "timestamp": x.timestamp.isoformat() if x.timestamp else None,
                    "module": x.module,
                    "message": x.message,
                }
                for x in recent_errors
            ],
            "diagnostics": {
                "is_ready_for_webhook": bool(is_ready_for_webhook),
                "is_ready_for_card_undo": bool(is_ready_for_card_undo),
                "missing_items": missing_items,
                "warnings": diagnostics_warnings,
            },
        }
    except Exception as e:
        env_missing_items = []
        if not settings.FEISHU_APP_ID:
            env_missing_items.append("app_id")
        if not settings.FEISHU_APP_SECRET:
            env_missing_items.append("app_secret")
        if not settings.FEISHU_VERIFICATION_TOKEN:
            env_missing_items.append("verification_token")
        if not settings.PUBLIC_API_BASE_URL:
            env_missing_items.append("public_api_base_url")
        return {
            "ok": False,
            "error": f"failed to collect status: {e!s}",
            "config_source": "env",
            "basic_config": {
                "app_id_configured": bool(settings.FEISHU_APP_ID),
                "app_secret_configured": bool(settings.FEISHU_APP_SECRET),
                "verification_token_configured": bool(settings.FEISHU_VERIFICATION_TOKEN),
                "encrypt_key_configured": bool(settings.FEISHU_ENCRYPT_KEY),
                "signature_check_enabled": settings.FEISHU_ENABLE_SIGNATURE_CHECK,
                "whitelist_enabled": settings.FEISHU_ENABLE_WHITELIST,
                "public_api_base_url": settings.PUBLIC_API_BASE_URL,
                "webhook_path": "/api/v1/ai/feishu-webhook",
                "undo_path": "/api/v1/ai/feishu-undo",
            },
            "capabilities": {
                "challenge_supported": True,
                "signature_check_enabled": settings.FEISHU_ENABLE_SIGNATURE_CHECK,
                "group_at_supported": True,
                "p2p_supported": True,
                "undo_supported": True,
                "async_mode": False,
            },
            "token_status": {"exists": False, "expire_at": None, "is_expired": None, "remain_seconds": None},
            "event_stats": {
                "total": 0,
                "success": 0,
                "failed": 0,
                "ignored": 0,
                "processing": 0,
                "last_24h_total": 0,
                "last_24h_failed": 0,
            },
            "failed_events": [],
            "recent_webhook_errors": [],
            "diagnostics": {
                "is_ready_for_webhook": False,
                "is_ready_for_card_undo": bool(settings.PUBLIC_API_BASE_URL),
                "missing_items": env_missing_items,
                "warnings": [],
            },
        }


@router.get("/feishu-recent-events")
async def feishu_recent_events(
    limit: int = Query(20, ge=1, le=200),
    process_status: str | None = Query(None),
    failed_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(FeishuMessageEvent)
    if failed_only:
        stmt = stmt.where(FeishuMessageEvent.process_status == "failed")
    elif process_status:
        stmt = stmt.where(FeishuMessageEvent.process_status == process_status)
    rows = list((await db.execute(stmt.order_by(desc(FeishuMessageEvent.created_at), desc(FeishuMessageEvent.id)).limit(limit))).scalars().all())
    return {
        "ok": True,
        "items": [
            {
                "id": e.id,
                "event_id": e.event_id,
                "message_id": e.message_id,
                "chat_id": e.chat_id,
                "open_id": e.open_id,
                "event_type": e.event_type,
                "message_type": e.message_type,
                "process_status": e.process_status,
                "error_message": e.error_message,
                "retry_count": e.retry_count,
                "duration_ms": e.duration_ms,
                "raw_payload": e.raw_payload,
                "response_message_id": e.response_message_id,
                "possible_config_issue": bool(
                    (e.error_message or "").lower().find("missing") >= 0
                    or (e.error_message or "").lower().find("token") >= 0
                    or (e.error_message or "").lower().find("signature") >= 0
                    or (e.error_message or "").lower().find("app_id") >= 0
                    or (e.error_message or "").lower().find("app_secret") >= 0
                ),
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in rows
        ],
    }


@router.get("/feishu-recent-errors")
async def feishu_recent_errors(
    limit: int = Query(20, ge=1, le=200),
    module_prefix: str = Query("feishu."),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows = list(
        (
            await db.execute(
                select(SystemLog)
                .where(SystemLog.level == "ERROR", SystemLog.module.ilike(f"{module_prefix}%"))
                .order_by(desc(SystemLog.timestamp), desc(SystemLog.id))
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return {
        "ok": True,
        "items": [
            {
                "id": x.id,
                "timestamp": x.timestamp.isoformat() if x.timestamp else None,
                "module": x.module,
                "message": x.message,
            }
            for x in rows
        ],
    }


@router.get("/feishu-config", response_model=FeishuConfigRead)
async def feishu_config(db: AsyncSession = Depends(get_db)) -> FeishuConfigRead:
    cfg = await get_feishu_config(db)
    return FeishuConfigRead(
        app_id=cfg.get("app_id"),
        app_secret_masked=cfg.get("app_secret_masked"),
        app_secret_configured=bool(cfg.get("app_secret_configured")),
        verification_token_masked=cfg.get("verification_token_masked"),
        verification_token_configured=bool(cfg.get("verification_token_configured")),
        encrypt_key_masked=cfg.get("encrypt_key_masked"),
        encrypt_key_configured=bool(cfg.get("encrypt_key_configured")),
        signature_check=bool(cfg.get("signature_check", True)),
        enable_signature_check=bool(cfg.get("signature_check", True)),
        enable_whitelist=bool(cfg.get("enable_whitelist", False)),
        whitelist_open_ids=str(cfg.get("whitelist_open_ids") or ""),
        bot_name=str(cfg.get("bot_name") or ""),
        public_api_base_url=cfg.get("public_api_base_url"),
        public_api_base_url_configured=bool(cfg.get("public_api_base_url_configured")),
        source_summary=str(cfg.get("source_summary") or "env"),
        webhook_url=cfg.get("webhook_url"),
        undo_url=cfg.get("undo_url"),
        app_id_configured=bool(cfg.get("app_id_configured")),
        whitelist_count=int(cfg.get("whitelist_count") or 0),
        config_source=str(cfg.get("config_source") or "env"),
    )


@router.put("/feishu-config", response_model=FeishuConfigRead)
@router.post("/feishu-config", response_model=FeishuConfigRead)
async def save_feishu_config_api(
    body: FeishuConfigUpdate,
    db: AsyncSession = Depends(get_db),
) -> FeishuConfigRead:
    cfg = await save_feishu_config(db, body.model_dump())
    return FeishuConfigRead(
        app_id=cfg.get("app_id"),
        app_secret_masked=cfg.get("app_secret_masked"),
        app_secret_configured=bool(cfg.get("app_secret_configured")),
        verification_token_masked=cfg.get("verification_token_masked"),
        verification_token_configured=bool(cfg.get("verification_token_configured")),
        encrypt_key_masked=cfg.get("encrypt_key_masked"),
        encrypt_key_configured=bool(cfg.get("encrypt_key_configured")),
        signature_check=bool(cfg.get("signature_check", True)),
        enable_signature_check=bool(cfg.get("signature_check", True)),
        enable_whitelist=bool(cfg.get("enable_whitelist", False)),
        whitelist_open_ids=str(cfg.get("whitelist_open_ids") or ""),
        bot_name=str(cfg.get("bot_name") or ""),
        public_api_base_url=cfg.get("public_api_base_url"),
        public_api_base_url_configured=bool(cfg.get("public_api_base_url_configured")),
        source_summary=str(cfg.get("source_summary") or "env"),
        webhook_url=cfg.get("webhook_url"),
        undo_url=cfg.get("undo_url"),
        app_id_configured=bool(cfg.get("app_id_configured")),
        whitelist_count=int(cfg.get("whitelist_count") or 0),
        config_source=str(cfg.get("config_source") or "env"),
    )


@router.post("/feishu-config/test", response_model=FeishuConfigTestResult)
async def test_feishu_config_api(
    body: FeishuConfigUpdate | None = None,
    db: AsyncSession = Depends(get_db),
) -> FeishuConfigTestResult:
    current = await get_feishu_config(db)
    payload = body.model_dump() if body is not None else {}
    app_id = str(payload.get("app_id") or current.get("app_id") or "").strip()
    app_secret = str(payload.get("app_secret") or current.get("app_secret") or "").strip()
    verification_token = str(payload.get("verification_token") or current.get("verification_token") or "").strip()
    public_api_base_url = normalize_public_api_base_url(
        str(payload.get("public_api_base_url") or current.get("public_api_base_url") or "")
    )
    webhook_url, undo_url = build_feishu_urls(public_api_base_url)
    app_id_ok = bool(app_id)
    app_secret_ok = bool(app_secret)
    token_ok = bool(verification_token)
    public_api_base_url_ok, url_warnings = _analyze_public_base_url(public_api_base_url)
    warnings: list[str] = []
    errors: list[str] = []
    warnings.extend(url_warnings)
    if not public_api_base_url:
        errors.append("缺少 PUBLIC_API_BASE_URL")
    if payload.get("enable_whitelist", current.get("enable_whitelist")) and not str(
        payload.get("whitelist_open_ids", current.get("whitelist_open_ids") or "")
    ).strip():
        warnings.append("已开启白名单，但 whitelist_open_ids 为空")
    if not app_id_ok:
        errors.append("缺少 App ID")
    if not app_secret_ok:
        errors.append("缺少 App Secret")
    if not token_ok:
        errors.append("缺少 Verification Token")
    if public_api_base_url and not public_api_base_url_ok:
        errors.append("PUBLIC_API_BASE_URL 非法")
    checks = [
        {"name": "app_id", "ok": app_id_ok, "message": "App ID 已配置" if app_id_ok else "缺少 App ID"},
        {
            "name": "app_secret",
            "ok": app_secret_ok,
            "message": "App Secret 已配置" if app_secret_ok else "缺少 App Secret",
        },
        {
            "name": "verification_token",
            "ok": token_ok,
            "message": "Verification Token 已配置" if token_ok else "缺少 Verification Token",
        },
        {
            "name": "public_api_base_url",
            "ok": public_api_base_url_ok,
            "message": "公网地址已配置" if public_api_base_url_ok else "缺少 PUBLIC_API_BASE_URL",
        },
    ]
    has_minimum_required_config = app_id_ok and app_secret_ok and token_ok and public_api_base_url_ok
    ok = has_minimum_required_config
    message = "配置通过基本校验" if ok else "配置未通过，请补齐必填项"
    return FeishuConfigTestResult(
        ok=ok,
        message=message,
        app_id_ok=app_id_ok,
        app_secret_ok=app_secret_ok,
        token_ok=token_ok,
        public_api_base_url_ok=public_api_base_url_ok,
        normalized_public_api_base_url=public_api_base_url or None,
        has_minimum_required_config=has_minimum_required_config,
        webhook_url=webhook_url,
        undo_url=undo_url,
        warnings=warnings,
        errors=errors,
        checks=checks,
    )


@router.post("/feishu-simulate")
async def feishu_simulate(
    body: dict[str, Any],
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    内部测试接口：模拟飞书消息进入 webhook 处理逻辑（复用同一核心流程）。
    """
    chat_type = str(body.get("chat_type") or "p2p")
    open_id = str(body.get("open_id") or "").strip()
    text = str(body.get("text") or "").strip()
    if not open_id or not text:
        raise HTTPException(status_code=400, detail="open_id 和 text 必填")
    chat_id = str(body.get("chat_id") or (f"chat_sim_{open_id}" if chat_type == "p2p" else "chat_sim_group")).strip()
    is_at_bot = bool(body.get("is_at_bot", chat_type == "p2p"))
    message_id = str(body.get("message_id") or f"sim_msg_{int(datetime.now(timezone.utc).timestamp() * 1000)}")
    event_id = str(body.get("event_id") or f"sim_evt_{int(datetime.now(timezone.utc).timestamp() * 1000)}")

    mentions = [{"key": "@_user_1", "name": "bot"}] if (chat_type != "p2p" and is_at_bot) else []
    simulated_body = {
        "header": {"event_id": event_id, "event_type": "im.message.receive_v1"},
        "event": {
            "sender": {"sender_type": "user", "sender_id": {"open_id": open_id}},
            "message": {
                "message_id": message_id,
                "chat_id": chat_id,
                "chat_type": "p2p" if chat_type == "p2p" else "group",
                "message_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
                "mentions": mentions,
            },
        },
    }
    raw = json.dumps(simulated_body, ensure_ascii=False).encode("utf-8")
    result = await process_feishu_event_async(
        db,
        request,
        simulated_body,
        raw,
        skip_signature_check=True,
        return_details=True,
    )
    return result


@router.get("/feishu-undo", response_class=HTMLResponse)
async def feishu_undo(
    project_id: int = Query(..., description="要撤销的项目 ID"),
    open_id: str | None = Query(None, description="可选：飞书用户 open_id"),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """
    飞书卡片「撤销」按钮打开的链接：执行项目撤销后返回简单 HTML 页面。
    点击卡片上的「撤销」会打开此 URL（GET），执行一次撤销并展示结果。
    """
    from app.api.projects import _undo_project_impl

    try:
        await _undo_project_impl(
            db,
            project_id,
            operator_source="feishu",
            operator_external_id=open_id,
        )
        db.add(
            SystemLog(
                level="INFO",
                module="feishu.undo",
                message=f"undo success project_id={project_id} open_id={open_id or ''}",
            )
        )
        await db.flush()
        return HTMLResponse(
            content="<html><body><p style='font-family:sans-serif;padding:1rem;'>✅ 撤销成功，请关闭此页。</p></body></html>",
            status_code=200,
        )
    except HTTPException as e:
        db.add(
            SystemLog(
                level="ERROR",
                module="feishu.undo",
                message=f"undo failed project_id={project_id} open_id={open_id or ''} detail={e.detail}",
            )
        )
        await db.flush()
        return HTMLResponse(
            content=f"<html><body><p style='font-family:sans-serif;padding:1rem;'>❌ 撤销失败：{e.detail}</p></body></html>",
            status_code=e.status_code,
        )
