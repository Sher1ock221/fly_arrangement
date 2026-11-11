"""
飞书机器人：获取 tenant_access_token，发送富文本/卡片回执。
AI 修改数据后通过此模块向用户发送通知卡片。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FeishuToken, SystemLog
from app.services.system_config_service import get_feishu_config

FEISHU_API = "https://open.feishu.cn/open-apis"
TOKEN_REFRESH_BUFFER_SECONDS = 300
TOKEN_TYPE_PREFIX = "fst_"
TOKEN_CACHE_KEY_MAX_LEN = 64


def _token_cache_key(app_id: str, tenant_key: str | None) -> str:
    """生成带 tenant_key 的 token 缓存 key，保证多租户不共用 token。"""
    raw = f"{app_id}:{tenant_key or 'default'}"
    if len(TOKEN_TYPE_PREFIX + raw) <= TOKEN_CACHE_KEY_MAX_LEN:
        return (TOKEN_TYPE_PREFIX + raw)[:TOKEN_CACHE_KEY_MAX_LEN]
    h = hashlib.sha256(raw.encode()).hexdigest()[: TOKEN_CACHE_KEY_MAX_LEN - len(TOKEN_TYPE_PREFIX)]
    return TOKEN_TYPE_PREFIX + h


def _is_simulation_receive_id(receive_id: str | None) -> bool:
    """
    判定是否为系统内部模拟会话 ID，非飞书真实 receive_id。
    命中则不应调用飞书开放平台发送接口。
    """
    if not receive_id or not isinstance(receive_id, str):
        return False
    r = receive_id.strip()
    return (
        r.startswith("chat_sim_")
        or r.startswith("sim_")
        or r.startswith("mock_")
    )


async def _log_system(
    db: AsyncSession,
    *,
    level: str,
    module: str,
    message: str,
    stack_trace: str | None = None,
) -> None:
    db.add(SystemLog(level=level, module=module, message=message[:2000], stack_trace=stack_trace))
    await db.flush()


async def get_tenant_access_token(
    db: AsyncSession,
    *,
    tenant_key: str | None = None,
) -> str | None:
    """使用 DB 缓存获取 tenant_access_token，过期前提前刷新。缓存 key 含 app_id+tenant_key，避免多租户共用 token。"""
    cfg = await get_feishu_config(db)
    app_id = str(cfg.get("app_id") or "")
    app_secret = str(cfg.get("app_secret") or "")
    if not app_id or not app_secret:
        await _log_system(
            db,
            level="ERROR",
            module="feishu.token",
            message="missing FEISHU_APP_ID or FEISHU_APP_SECRET",
        )
        return None
    cache_key = _token_cache_key(app_id, tenant_key)
    await _log_system(
        db,
        level="INFO",
        module="feishu.token",
        message=f"token lookup app_id={app_id} tenant_key={tenant_key or 'default'} cache_key={cache_key}",
    )
    now = datetime.now(timezone.utc)
    cached = (
        await db.execute(
            select(FeishuToken).where(FeishuToken.token_type == cache_key).limit(1)
        )
    ).scalar_one_or_none()
    if cached and cached.expire_at > now + timedelta(seconds=TOKEN_REFRESH_BUFFER_SECONDS):
        remain = int((cached.expire_at - now).total_seconds())
        await _log_system(
            db,
            level="INFO",
            module="feishu.token",
            message=f"token reused remain_seconds={remain} cache_key={cache_key}",
        )
        return cached.access_token
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{FEISHU_API}/auth/v3/tenant_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
            )
            r.raise_for_status()
            data = r.json()
            if data.get("code") != 0:
                await _log_system(
                    db,
                    level="ERROR",
                    module="feishu.token",
                    message=f"fetch token failed code={data.get('code')} msg={data.get('msg')}",
                )
                return None
            token = data.get("tenant_access_token")
            expire = now + timedelta(seconds=int(data.get("expire", 7200)))
            if token:
                if cached:
                    cached.access_token = token
                    cached.expire_at = expire
                    cached.updated_at = now
                else:
                    db.add(
                        FeishuToken(
                            token_type=cache_key,
                            access_token=token,
                            expire_at=expire,
                        )
                    )
                await db.flush()
                await _log_system(
                    db,
                    level="INFO",
                    module="feishu.token",
                    message=f"token refreshed expire_at={expire.isoformat()} cache_key={cache_key}",
                )
                return token
            return None
    except Exception as e:
        await _log_system(
            db,
            level="ERROR",
            module="feishu.token",
            message=f"token request exception: {e!s}",
        )
        return None


async def _send_feishu_message(
    db: AsyncSession,
    *,
    receive_id: str,
    receive_id_type: str,
    msg_type: str,
    content: dict[str, Any],
    event_id: str | None = None,
    open_id: str | None = None,
    chat_id: str | None = None,
    tenant_key: str | None = None,
) -> dict[str, Any]:
    if _is_simulation_receive_id(receive_id):
        await _log_system(
            db,
            level="INFO",
            module="feishu.bot",
            message=(
                f"skip real feishu send for simulated conversation "
                f"receive_id={receive_id} receive_id_type={receive_id_type} "
                f"event_id={event_id or ''} open_id={open_id or ''} chat_id={chat_id or ''}"
            ),
        )
        return {"ok": True, "skipped": True, "reason": "simulation"}

    cfg = await get_feishu_config(db)
    app_id = str((cfg or {}).get("app_id") or "")
    effective_tenant_key = (tenant_key if (tenant_key is not None and str(tenant_key).strip()) else None)
    if effective_tenant_key is None:
        await _log_system(
            db,
            level="WARNING",
            module="feishu.bot",
            message="tenant_key not provided for send_message, using fallback (default cache key)",
        )
    await _log_system(
        db,
        level="INFO",
        module="feishu.bot",
        message=(
            f"send_message called tenant_key={effective_tenant_key or ''} app_id={app_id} "
            f"receive_id={receive_id} receive_id_type={receive_id_type}"
        ),
    )
    token = await get_tenant_access_token(db, tenant_key=effective_tenant_key)
    if not token:
        return {"ok": False, "error": "missing tenant_access_token"}
    tenant_key_for_log = effective_tenant_key or ""
    await _log_system(
        db,
        level="INFO",
        module="feishu.bot",
        message=(
            f"feishu send debug app_id={app_id} tenant_key={tenant_key_for_log} token_present={bool(token)} "
            f"receive_id={receive_id} receive_id_type={receive_id_type} chat_id={chat_id or ''} "
            f"open_id={open_id or ''} event_id={event_id or ''} message_type={msg_type} simulation=False"
        ),
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{FEISHU_API}/im/v1/messages",
                params={"receive_id_type": receive_id_type},
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"receive_id": receive_id, "msg_type": msg_type, "content": json.dumps(content, ensure_ascii=False)},
            )
        data = r.json() if r.content else {}
        ok = r.status_code == 200 and (data or {}).get("code") == 0
        if ok:
            await _log_system(
                db,
                level="INFO",
                module="feishu.bot",
                message=f"send message ok type={msg_type} receive_id_type={receive_id_type}",
            )
            return {"ok": True, "data": data, "message_id": (data.get("data") or {}).get("message_id")}
        await _log_system(
            db,
            level="ERROR",
            module="feishu.bot",
            message=(
                f"send message failed status={r.status_code} code={data.get('code')} msg={data.get('msg')} "
                f"app_id={app_id} tenant_key={tenant_key_for_log} receive_id={receive_id} receive_id_type={receive_id_type} "
                f"chat_id={chat_id or ''} open_id={open_id or ''} event_id={event_id or ''} message_type={msg_type} body={data!r}"
            ),
        )
        return {"ok": False, "error": str(data), "status_code": r.status_code}
    except Exception as e:
        await _log_system(
            db,
            level="ERROR",
            module="feishu.bot",
            message=(
                f"send message exception status=exception app_id={app_id} tenant_key={tenant_key_for_log} "
                f"receive_id={receive_id} receive_id_type={receive_id_type} chat_id={chat_id or ''} "
                f"open_id={open_id or ''} event_id={event_id or ''} message_type={msg_type}: {e!s}"
            ),
        )
        return {"ok": False, "error": str(e)}


async def send_text_message(
    db: AsyncSession,
    *,
    receive_id: str,
    text: str,
    receive_id_type: str = "chat_id",
    event_id: str | None = None,
    open_id: str | None = None,
    chat_id: str | None = None,
    tenant_key: str | None = None,
) -> dict[str, Any]:
    return await _send_feishu_message(
        db,
        receive_id=receive_id,
        receive_id_type=receive_id_type,
        msg_type="text",
        content={"text": text},
        event_id=event_id,
        open_id=open_id,
        chat_id=chat_id,
        tenant_key=tenant_key,
    )


async def send_card_message(
    db: AsyncSession,
    *,
    receive_id: str,
    card: dict[str, Any],
    receive_id_type: str = "chat_id",
    event_id: str | None = None,
    open_id: str | None = None,
    chat_id: str | None = None,
    tenant_key: str | None = None,
) -> dict[str, Any]:
    return await _send_feishu_message(
        db,
        receive_id=receive_id,
        receive_id_type=receive_id_type,
        msg_type="interactive",
        content=card,
        event_id=event_id,
        open_id=open_id,
        chat_id=chat_id,
        tenant_key=tenant_key,
    )


async def send_error_message(
    db: AsyncSession,
    *,
    receive_id: str,
    receive_id_type: str = "chat_id",
    text: str = "本次处理失败，请稍后重试",
    event_id: str | None = None,
    open_id: str | None = None,
    chat_id: str | None = None,
    tenant_key: str | None = None,
) -> dict[str, Any]:
    return await send_text_message(
        db,
        receive_id=receive_id,
        receive_id_type=receive_id_type,
        text=text,
        event_id=event_id,
        open_id=open_id,
        chat_id=chat_id,
        tenant_key=tenant_key,
    )


async def reply_message(
    db: AsyncSession,
    *,
    receive_id: str,
    receive_id_type: str = "chat_id",
    text: str | None = None,
    card: dict[str, Any] | None = None,
    event_id: str | None = None,
    open_id: str | None = None,
    chat_id: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": True}
    if text:
        out = await send_text_message(
            db,
            receive_id=receive_id,
            receive_id_type=receive_id_type,
            text=text,
            event_id=event_id,
            open_id=open_id,
            chat_id=chat_id,
        )
        if not out.get("ok"):
            return out
    if card:
        out = await send_card_message(
            db,
            receive_id=receive_id,
            receive_id_type=receive_id_type,
            card=card,
            event_id=event_id,
            open_id=open_id,
            chat_id=chat_id,
        )
    return out


async def list_chat_messages(
    db: AsyncSession,
    *,
    chat_id: str,
    tenant_key: str | None = None,
    start_time: int | None = None,
    end_time: int | None = None,
    page_token: str | None = None,
    page_size: int = 50,
) -> dict[str, Any]:
    """
    拉取指定会话（私聊/群聊）的历史消息列表。
    GET /open-apis/im/v1/messages?container_id_type=chat&container_id=chat_id&...
    用于离线补偿：只拉私聊时由调用方保证 chat_id 为 p2p 会话。
    """
    token = await get_tenant_access_token(db, tenant_key=tenant_key)
    if not token:
        return {"ok": False, "error": "missing tenant_access_token"}
    params: dict[str, Any] = {
        "container_id_type": "chat",
        "container_id": chat_id,
        "page_size": min(max(page_size, 1), 50),
    }
    if start_time is not None:
        params["start_time"] = str(start_time)
    if end_time is not None:
        params["end_time"] = str(end_time)
    if page_token:
        params["page_token"] = page_token
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                f"{FEISHU_API}/im/v1/messages",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
        data = r.json() if r.content else {}
        if r.status_code != 200 or data.get("code") != 0:
            return {"ok": False, "error": data.get("msg", r.text), "code": data.get("code")}
        d = data.get("data") or {}
        items = d.get("items") or []
        return {
            "ok": True,
            "items": items,
            "has_more": bool(d.get("has_more")),
            "page_token": d.get("page_token"),
        }
    except Exception as e:
        await _log_system(
            db,
            level="ERROR",
            module="feishu.bot",
            message=f"list_chat_messages exception chat_id={chat_id!r}: {e!s}",
        )
        return {"ok": False, "error": str(e)}


async def get_message(
    db: AsyncSession,
    *,
    message_id: str,
    tenant_key: str | None = None,
) -> dict[str, Any]:
    """获取单条消息详情（含 body 正文），用于历史消息列表中无 body 时补拉。"""
    token = await get_tenant_access_token(db, tenant_key=tenant_key)
    if not token:
        return {"ok": False, "error": "missing tenant_access_token"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{FEISHU_API}/im/v1/messages/{message_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
        data = r.json() if r.content else {}
        if r.status_code != 200 or data.get("code") != 0:
            return {"ok": False, "error": data.get("msg", r.text), "code": data.get("code")}
        return {"ok": True, "data": data.get("data") or {}}
    except Exception as e:
        await _log_system(
            db,
            level="ERROR",
            module="feishu.bot",
            message=f"get_message exception message_id={message_id!r}: {e!s}",
        )
        return {"ok": False, "error": str(e)}


# 项目字段展示用中文名
PROJECT_FIELD_LABELS: dict[str, str] = {
    "name": "项目名称",
    "deadline": "截止日期",
    "goal": "项目目标",
    "owner": "负责人",
    "requirements": "项目内需",
    "customer_name": "客户名称",
    "update_date": "更新日期",
}


def _format_field_value(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, str) and len(value) > 80:
        return value[:77] + "..."
    return str(value)


def _build_receipt_card(
    summary: str,
    execution_results: list[dict[str, Any]],
    assistant_text: str = "",
    public_api_base_url: str | None = None,
    operator_external_id: str | None = None,
) -> dict[str, Any]:
    """
    构建飞书交互卡片 JSON：
    - 项目总结（list_all_projects）：报表型卡片「📊 项目运行月度/周度报告」+ note 数据来源与截止时间。
    - 新建项目：标题「🆕 新项目已创建」，列出所有初始字段。
    - 修改项目：标题「✏️ 项目属性已变更」，旧值 -> 新值 对比。
    - 其他：通用「AI 已执行修改」+ 执行摘要。
    - 若涉及项目且可撤销，底部增加「撤销」按钮。
    """
    elements: list[dict[str, Any]] = []
    project_id_for_undo: int | None = None
    base_url = (public_api_base_url or "").rstrip("/")

    # 优先识别：项目总结（list_all_projects 成功）→ 报表型卡片
    summary_result = next(
        (r for r in execution_results if r.get("success") and r.get("tool_name") == "list_all_projects"),
        None,
    )
    if summary_result and (assistant_text or "").strip():
        # 报表标题 + note 数据来源与截止时间 + 总结正文
        data_cutoff = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        note_content = f"数据来源：list_all_projects | 截止时间：{data_cutoff}"
        elements.append({
            "tag": "note",
            "elements": [
                {"tag": "plain_text", "content": note_content},
            ],
        })
        elements.append({"tag": "hr"})
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": (assistant_text or "").strip()}})
        return {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": "📊 项目运行月度/周度报告", "emoji": True}},
            "elements": elements,
        }

    # 识别：智能排程建议（suggest_schedule 成功）→ 日程建议卡片
    schedule_result = next(
        (r for r in execution_results if r.get("success") and r.get("tool_name") in ("auto_schedule_event", "suggest_schedule", "confirm_or_cancel_schedule")),
        None,
    )
    if schedule_result:
        if assistant_text and assistant_text.strip():
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": assistant_text}})
        elif schedule_result.get("message"):
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": schedule_result["message"]}})
        slots = schedule_result.get("slots")
        if isinstance(slots, list) and slots:
            elements.append({"tag": "hr"})
            for i, s in enumerate(slots[:3], 1):
                if not isinstance(s, dict):
                    continue
                label = s.get("label") or ""
                if label:
                    elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"{i}. {label}"}})
        tool_name = schedule_result.get("tool_name", "")
        if tool_name == "auto_schedule_event":
            card_title = "✅ 日程已自动安排"
            result_obj = schedule_result.get("result") if isinstance(schedule_result.get("result"), dict) else {}
            if result_obj and result_obj.get("was_adjusted"):
                elements.append({"tag": "note", "elements": [{"tag": "plain_text", "content": "已自动避让冲突并完成安排"}]})
        elif tool_name == "suggest_schedule":
            card_title = "📅 日程安排建议"
        elif schedule_result.get("event_id"):
            card_title = "✅ 日程已创建"
        else:
            card_title = "📅 日程安排"
        return {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": card_title, "emoji": True}},
            "elements": elements,
        }

    # 优先识别：新建项目（create_project / upsert_project）
    create_result = next(
        (r for r in execution_results if r.get("success") and r.get("tool_name") in ("create_project", "upsert_project")),
        None,
    )
    if create_result and isinstance(create_result.get("result"), dict):
        result = create_result["result"]
        project_id_for_undo = result.get("id") if isinstance(result.get("id"), int) else None
        if assistant_text and assistant_text.strip():
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": assistant_text}})
        elements.append({"tag": "hr"})
        for key, label in PROJECT_FIELD_LABELS.items():
            if key not in result:
                continue
            val = _format_field_value(result.get(key))
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"**{label}**：{val}"}})
        card_title = "🆕 新项目已创建"
    else:
        # 识别：修改项目（update_project / update_project_fields）
        update_result = next(
            (
                r
                for r in execution_results
                if r.get("success") and r.get("tool_name") in ("update_project", "update_project_fields")
            ),
            None,
        )
        if update_result and isinstance(update_result.get("result"), dict):
            result = update_result["result"]
            old_value = update_result.get("old_value") if isinstance(update_result.get("old_value"), dict) else {}
            project_id_for_undo = result.get("id") if isinstance(result.get("id"), int) else None
            if assistant_text and assistant_text.strip():
                elements.append({"tag": "div", "text": {"tag": "lark_md", "content": assistant_text}})
            elements.append({"tag": "hr"})
            # 仅展示有变更的字段：旧值 -> 新值
            has_any_change = False
            for key, label in PROJECT_FIELD_LABELS.items():
                if key not in result:
                    continue
                new_val = result.get(key)
                old_val = old_value.get(key)
                if old_val == new_val:
                    continue
                has_any_change = True
                old_str = _format_field_value(old_val)
                new_str = _format_field_value(new_val)
                elements.append({
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": f"**{label}**：{old_str} → {new_str}"},
                })
            if not has_any_change:
                elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"**执行摘要**：{summary}"}})
            card_title = "✏️ 项目属性已变更"
        else:
            # 通用卡片
            if assistant_text and assistant_text.strip():
                elements.append({"tag": "div", "text": {"tag": "lark_md", "content": assistant_text}})
            elements.append({"tag": "hr"})
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"**执行摘要**：{summary}"}})
            for i, er in enumerate(execution_results, 1):
                name = er.get("tool_name", "?")
                success = er.get("success", False)
                status = "✅ 成功" if success else "❌ 失败"
                detail = er.get("result") if success else er.get("error", "")
                if isinstance(detail, dict):
                    detail = json.dumps(detail, ensure_ascii=False)[:200]
                elif isinstance(detail, list):
                    detail = f"共 {len(detail)} 条"
                elements.append({
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": f"{i}. **{name}**：{status}\n{str(detail)[:150]}"},
                })
            card_title = "AI 已执行修改"

    # 底部「撤销」按钮：仅当存在可撤销的项目时展示
    if project_id_for_undo and base_url:
        undo_url = f"{base_url}/api/v1/ai/feishu-undo?project_id={project_id_for_undo}"
        if operator_external_id:
            undo_url += f"&open_id={operator_external_id}"
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "撤销", "emoji": True},
                    "type": "default",
                    "url": undo_url,
                },
            ],
        })

    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": card_title, "emoji": True}},
        "elements": elements,
    }


async def send_receipt_card(
    db: AsyncSession,
    receive_id: str,
    receive_id_type: str = "chat_id",
    *,
    execution_results: list[dict[str, Any]] | None = None,
    assistant_text: str = "",
    operator_external_id: str | None = None,
    event_id: str | None = None,
    open_id: str | None = None,
    chat_id: str | None = None,
    tenant_key: str | None = None,
) -> bool:
    """
    发送 AI 执行结果回执卡片到指定会话。
    receive_id: 群聊 chat_id 或用户 open_id
    receive_id_type: "chat_id" | "open_id"
    execution_results: execute_tool_calls 的返回值列表
    assistant_text: 助手回复的文本（可选）
    """
    execution_results = execution_results or []
    success_count = sum(1 for r in execution_results if r.get("success"))
    summary = f"共 {len(execution_results)} 项操作，{success_count} 项成功。"
    cfg = await get_feishu_config(db)
    card = _build_receipt_card(
        summary,
        execution_results,
        assistant_text,
        public_api_base_url=str(cfg.get("public_api_base_url") or ""),
        operator_external_id=operator_external_id,
    )
    result = await send_card_message(
        db,
        receive_id=receive_id,
        receive_id_type=receive_id_type,
        card=card,
        event_id=event_id,
        open_id=open_id,
        chat_id=chat_id,
        tenant_key=tenant_key,
    )
    return bool(result.get("ok"))
