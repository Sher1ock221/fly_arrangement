"""
AI 工具调用执行器：TOOL_MAP 分发 + 实体解析优先流程，减少 if/else，统一写 SystemLog。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta, time, timezone
from typing import Any, Callable, Awaitable

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AuditLog,
    Customer,
    CustomerInteraction,
    Project,
    SystemLog,
    ACTION_CREATE,
    ACTION_UPDATE,
    TARGET_TYPE_CUSTOMER,
    TARGET_TYPE_PROJECT,
)
from app.models.collaboration import (
    CustomerCollaborator,
    ProjectCollaborator,
)
from app.models.project_customer import ProjectCustomer
from app.schemas.customer import CustomerCreate, CustomerInDB, CustomerUpdate
from app.schemas.customer_interaction import CustomerInteractionCreate
from app.schemas.project import ProjectCreate, ProjectInDB, ProjectUpdate
from app.services.entity_resolver import resolve_project as resolve_project_impl, resolve_customer as resolve_customer_impl
from app.services.project_tools import update_project_by_id
from app.services.customer_tools import update_customer_by_id
from app.services.calendar_tools import (
    get_calendar_events,
    create_calendar_event,
    update_calendar_event,
    delete_calendar_event,
)

logger = logging.getLogger(__name__)
MAX_TOOL_RETRY = 1

# ---------- 中文字段映射：AI 解析后映射到 update 参数 ----------
CN_FIELD_MAP = {
    "负责人": "owner",
    "截止日期": "deadline",
    "项目目标": "goal",
    "项目内需": "requirements",
    "项目名称": "name",
    "客户名称": "customer_name",
    "客户": "customer_id",
    "公司": "company",
    "职位": "position",
    "业务方向": "business_direction",
    "备注": "notes",
    "如何认识": "acquaintance_source",
    "联系方式": "contact",
    "公司简介": "profile",
    "未来合作方向": "future_direction",
    "认识方式": "origin",
}


def _project_to_log_value(orm: Project) -> dict:
    return ProjectInDB.model_validate(orm).model_dump(mode="json")


def _customer_to_log_value(orm: Customer) -> dict:
    return CustomerInDB.model_validate(orm).model_dump(mode="json")


def _parse_meeting_time(value: Any) -> datetime | None:
    """
    将 meeting_time 转为 timezone-aware datetime。
    支持：None、ISO 字符串、相对时间关键词（昨天、前天、上周、今天、今天下午）。
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).strip()
    now = datetime.now(timezone.utc)
    today = now.date()
    relative_map = {
        "今天": today,
        "昨天": today - timedelta(days=1),
        "前天": today - timedelta(days=2),
        "上周": today - timedelta(days=7),
        "大前天": today - timedelta(days=3),
    }
    if s in relative_map:
        return datetime.combine(relative_map[s], time(12, 0, 0, tzinfo=timezone.utc))
    if s == "今天下午":
        return datetime.combine(today, time(14, 0, 0, tzinfo=timezone.utc))
    if s == "昨天下午":
        d = today - timedelta(days=1)
        return datetime.combine(d, time(14, 0, 0, tzinfo=timezone.utc))
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


async def _get_next_project_no(db: AsyncSession) -> str:
    result = await db.execute(
        select(Project.project_no).where(Project.project_no.isnot(None))
    )
    rows = result.scalars().all()
    max_n = 0
    for row in rows:
        no = row[0] if isinstance(row, (tuple, list)) else getattr(row, "project_no", row)
        if no and isinstance(no, str):
            m = re.match(r"^P(\d+)$", no.strip(), re.IGNORECASE)
            if m:
                max_n = max(max_n, int(m.group(1)))
    return f"P{max_n + 1:03d}"


# ---------- TOOL_MAP 统一入口：resolve / update by id ----------

async def _handle_resolve_project(
    db: AsyncSession,
    args: dict[str, Any],
    *,
    operator_source: str = "ai",
    operator_external_id: str | None = None,
    operator_user_id: int | None = None,
) -> dict[str, Any]:
    query = args.get("query", "") or ""
    result = await resolve_project_impl(db, query, owner_user_id=operator_user_id)
    if result.get("success"):
        result["execution_summary"] = f"已解析到项目 {result.get('project_no', '')} (id={result.get('project_id')})"
    else:
        result["execution_summary"] = result.get("message", "未找到项目")
    return result


async def _handle_resolve_customer(
    db: AsyncSession,
    args: dict[str, Any],
    *,
    operator_source: str = "ai",
    operator_external_id: str | None = None,
    operator_user_id: int | None = None,
) -> dict[str, Any]:
    query = args.get("query", "") or ""
    result = await resolve_customer_impl(db, query, owner_user_id=operator_user_id)
    if result.get("success"):
        result["execution_summary"] = f"已解析到客户 {result.get('name', '')} (id={result.get('customer_id')})"
    else:
        result["execution_summary"] = result.get("message", "未找到客户")
    return result


async def _handle_update_project(
    db: AsyncSession,
    args: dict[str, Any],
    *,
    operator_source: str = "ai",
    operator_external_id: str | None = None,
    operator_user_id: int | None = None,
) -> dict[str, Any]:
    """
    更新项目。支持 customer_ids / customer_names 与 append：
    append=True 表示追加关联客户，False 或未传表示覆盖。
    customer_names 会先逐个 resolve，任一歧义则返回澄清。
    """
    project_id = args.get("project_id")
    if project_id is None:
        return {"success": False, "message": "缺少 project_id", "execution_summary": "缺少 project_id"}
    project_id = int(project_id)
    customer_ids_raw = args.get("customer_ids")
    customer_names_raw = args.get("customer_names")
    append = args.get("append")
    if isinstance(append, str):
        append = append.strip().lower() in ("true", "1", "yes")
    elif append is None:
        append = False
    ids_from_arg: list[int] = []
    if customer_ids_raw is not None:
        if isinstance(customer_ids_raw, (list, tuple)):
            for x in customer_ids_raw:
                try:
                    ids_from_arg.append(int(x))
                except (TypeError, ValueError):
                    pass
        else:
            try:
                ids_from_arg.append(int(customer_ids_raw))
            except (TypeError, ValueError):
                pass
    names_list: list[str] = []
    if customer_names_raw is not None:
        if isinstance(customer_names_raw, (list, tuple)):
            names_list = [str(x).strip() for x in customer_names_raw if x and str(x).strip()]
        elif customer_names_raw:
            names_list = [str(customer_names_raw).strip()]
    resolved_ids: list[int] = []
    for name in names_list:
        resolve_result = await resolve_customer_impl(db, name, owner_user_id=operator_user_id)
        if not resolve_result.get("success"):
            msg = resolve_result.get("message", "未找到客户")
            candidates = resolve_result.get("candidates")
            if candidates:
                return {
                    "success": False,
                    "message": msg,
                    "execution_summary": f"客户「{name}」存在多个匹配，请补充更具体的名称或公司：",
                    "candidates": candidates,
                }
            return {"success": False, "message": msg, "execution_summary": f"未找到唯一匹配的客户「{name}」，请确认名称。"}
        cid = resolve_result.get("customer_id")
        if cid is not None:
            resolved_ids.append(cid)
    merged_customer_ids = list(ids_from_arg)
    for cid in resolved_ids:
        if cid not in merged_customer_ids:
            merged_customer_ids.append(cid)
    mapped_args = {}
    for k, v in args.items():
        if k in ("project_id", "customer_ids", "customer_names", "append"):
            continue
        mapped_args[CN_FIELD_MAP.get(k, k)] = v
    fields = {k: v for k, v in mapped_args.items() if v is not None}
    if merged_customer_ids or customer_ids_raw is not None or names_list:
        fields["customer_ids"] = merged_customer_ids
        fields["append"] = append
    return await update_project_by_id(
        db,
        project_id,
        fields,
        operator_source=operator_source,
        operator_external_id=operator_external_id,
        operator_user_id=operator_user_id,
    )


async def _handle_update_customer(
    db: AsyncSession,
    args: dict[str, Any],
    *,
    operator_source: str = "ai",
    operator_external_id: str | None = None,
    operator_user_id: int | None = None,
) -> dict[str, Any]:
    """
    更新客户。支持 customer_id 或 customer_name（先 resolve 再更新）。
    歧义时返回 candidates，不乱改。
    """
    customer_id_arg = args.get("customer_id")
    customer_name_arg = args.get("customer_name") or args.get("query")
    if customer_id_arg is None and (not customer_name_arg or not str(customer_name_arg).strip()):
        return {"success": False, "message": "缺少 customer_id 或 customer_name", "execution_summary": "请指定要修改的客户（名称或 ID）。"}
    customer_id: int | None = None
    customer_name: str = ""
    if customer_id_arg is not None:
        try:
            cid = int(customer_id_arg)
        except (TypeError, ValueError):
            return {"success": False, "message": "customer_id 格式错误", "execution_summary": "customer_id 必须为数字"}
        orm = await db.get(Customer, cid)
        if orm is None:
            return {"success": False, "message": "客户不存在", "execution_summary": f"未找到 id={cid} 的客户。"}
        if operator_user_id is not None and orm.owner_user_id != operator_user_id:
            return {"success": False, "message": "无权限操作该客户", "execution_summary": "无权限操作该客户或客户不存在。"}
        customer_id = orm.id
        customer_name = (orm.name or "").strip()
    else:
        name_query = str(customer_name_arg).strip()
        resolve_result = await resolve_customer_impl(db, name_query, owner_user_id=operator_user_id)
        if not resolve_result.get("success"):
            msg = resolve_result.get("message", "未找到客户")
            candidates = resolve_result.get("candidates")
            if candidates:
                return {
                    "success": False,
                    "message": msg,
                    "execution_summary": "找到多个可能匹配的客户，请补充更具体的名称或公司：",
                    "candidates": candidates,
                }
            return {"success": False, "message": msg, "execution_summary": "未找到唯一匹配的客户，请确认客户名称。"}
        customer_id = resolve_result.get("customer_id")
        customer_name = resolve_result.get("name", name_query)
        if customer_id is None:
            return {"success": False, "message": "未找到客户", "execution_summary": "未找到唯一匹配的客户。"}
    mapped_args = {}
    for k, v in args.items():
        if k in ("customer_id", "customer_name", "query"):
            continue
        mapped_args[CN_FIELD_MAP.get(k, k)] = v
    fields = {k: v for k, v in mapped_args.items() if v is not None}
    result = await update_customer_by_id(
        db,
        customer_id,
        fields,
        operator_source=operator_source,
        operator_external_id=operator_external_id,
        operator_user_id=operator_user_id,
    )
    if result.get("success") and isinstance(result.get("result"), dict):
        result["result"]["detail_url"] = f"/customers/{customer_id}"
        result["result"]["customer_name"] = customer_name
    return result


async def _handle_create_customer_interaction(
    db: AsyncSession,
    args: dict[str, Any],
    *,
    operator_source: str = "ai",
    operator_external_id: str | None = None,
    operator_user_id: int | None = None,
) -> dict[str, Any]:
    """
    将客户沟通/拜访记录归档到 customer_interactions。
    优先使用 customer_id；若只有 customer_name 则通过 resolve_customer 匹配。
    找不到唯一客户时不写入，返回澄清提示。
    """
    customer_id_arg = args.get("customer_id")
    customer_name_arg = args.get("customer_name")
    if customer_id_arg is None and (not customer_name_arg or not str(customer_name_arg).strip()):
        return {
            "success": False,
            "message": "必须提供 customer_id 或 customer_name",
            "execution_summary": "无法确定客户：请提供客户名称或先说出「列出客户」后提供客户 ID。",
        }
    customer_id: int | None = None
    customer_name: str = ""
    if customer_id_arg is not None:
        try:
            cid = int(customer_id_arg)
        except (TypeError, ValueError):
            return {"success": False, "message": "customer_id 格式错误", "execution_summary": "customer_id 必须为数字"}
        orm = await db.get(Customer, cid)
        if orm is None:
            return {
                "success": False,
                "message": "客户不存在",
                "execution_summary": f"未找到 id={cid} 的客户，请确认客户是否存在或改用客户名称。",
            }
        if operator_user_id is not None and orm.owner_user_id != operator_user_id:
            return {"success": False, "message": "无权限操作该客户", "execution_summary": "无权限为该客户添加沟通记录。"}
        customer_id = orm.id
        customer_name = (orm.name or "").strip()
    else:
        name_query = str(customer_name_arg).strip()
        resolve_result = await resolve_customer_impl(db, name_query, owner_user_id=operator_user_id)
        if not resolve_result.get("success"):
            msg = resolve_result.get("message", "未找到客户")
            candidates = resolve_result.get("candidates")
            if candidates:
                summary = "找到多个可能匹配的客户，请补充更具体的名称或公司："
                return {
                    "success": False,
                    "message": msg,
                    "execution_summary": summary,
                    "candidates": candidates,
                }
            return {
                "success": False,
                "message": msg,
                "execution_summary": "未找到唯一匹配的客户，请确认客户名称或说「列出客户」查看后提供更具体的名称或 ID。",
            }
        customer_id = resolve_result.get("customer_id")
        customer_name = resolve_result.get("name", name_query)
        if customer_id is None:
            return {
                "success": False,
                "message": "未找到客户",
                "execution_summary": "未找到唯一匹配的客户，请确认客户名称。",
            }
    meeting_time = _parse_meeting_time(args.get("meeting_time"))
    talk_summary = args.get("talk_summary")
    if isinstance(talk_summary, str) and not talk_summary.strip():
        talk_summary = None
    cooperation_direction = args.get("cooperation_direction")
    if isinstance(cooperation_direction, str) and not cooperation_direction.strip():
        cooperation_direction = None
    cooperation_intent = args.get("cooperation_intent")
    if isinstance(cooperation_intent, str) and not cooperation_intent.strip():
        cooperation_intent = None
    next_cooperation_plan = args.get("next_cooperation_plan")
    if isinstance(next_cooperation_plan, str) and not next_cooperation_plan.strip():
        next_cooperation_plan = None
    specific_needs = args.get("specific_needs")
    if isinstance(specific_needs, str) and not specific_needs.strip():
        specific_needs = None
    importance = args.get("importance")
    if importance is not None:
        try:
            importance = int(importance)
            if importance < 1 or importance > 5:
                importance = None
        except (TypeError, ValueError):
            importance = None
    source = operator_source if operator_source in ("ai", "feishu", "web") else "ai"
    raw_input = args.get("raw_input")
    if isinstance(raw_input, str) and not raw_input.strip():
        raw_input = None
    try:
        body = CustomerInteractionCreate(
            meeting_time=meeting_time,
            talk_summary=talk_summary,
            cooperation_direction=cooperation_direction,
            cooperation_intent=cooperation_intent,
            next_cooperation_plan=next_cooperation_plan,
            specific_needs=specific_needs,
            importance=importance,
            source=source,
            raw_input=raw_input,
        )
    except Exception as e:
        logger.exception("create_customer_interaction validation failed")
        return {"success": False, "error": str(e), "execution_summary": str(e)}
    orm = CustomerInteraction(
        customer_id=customer_id,
        meeting_time=body.meeting_time,
        talk_summary=body.talk_summary,
        cooperation_direction=body.cooperation_direction,
        cooperation_intent=body.cooperation_intent,
        next_cooperation_plan=body.next_cooperation_plan,
        specific_needs=body.specific_needs,
        importance=body.importance,
        source=body.source,
        raw_input=body.raw_input,
    )
    db.add(orm)
    await db.flush()
    await db.refresh(orm)
    message = "已将本次沟通记录归档到客户【" + customer_name + "】名下，可前往客户详情页查看。"
    detail_url = f"/customers/{customer_id}"
    return {
        "success": True,
        "result": {
            "id": orm.id,
            "customer_id": customer_id,
            "customer_name": customer_name,
            "interaction_id": orm.id,
            "message": message,
            "detail_url": detail_url,
        },
        "message": message,
        "execution_summary": message,
    }


async def _handle_resolve_user(
    db: AsyncSession,
    args: dict[str, Any],
    *,
    operator_source: str = "ai",
    operator_external_id: str | None = None,
    operator_user_id: int | None = None,
) -> dict[str, Any]:
    from app.services.collaboration_service import resolve_user_by_name
    query = args.get("query", "") or ""
    result = await resolve_user_by_name(db, query)
    if result.get("success"):
        result["execution_summary"] = f"已解析到用户 {result.get('display_name', '')} (id={result.get('user_id')})"
    else:
        result["execution_summary"] = result.get("message", "未找到用户")
    return result


async def _handle_manage_collaborator(
    db: AsyncSession,
    args: dict[str, Any],
    *,
    operator_source: str = "ai",
    operator_external_id: str | None = None,
    operator_user_id: int | None = None,
) -> dict[str, Any]:
    from app.services.collaboration_service import (
        add_project_collaborator, remove_project_collaborator, list_project_collaborators,
        add_customer_collaborator, remove_customer_collaborator, list_customer_collaborators,
        add_calendar_event_collaborator, remove_calendar_event_collaborator, list_calendar_event_collaborators,
        get_project_access_role, get_customer_access_role, get_calendar_event_access_role,
    )
    from app.services.audit_log_service import write_audit_log

    action = args.get("action", "")
    rt = args.get("resource_type", "")
    rid = args.get("resource_id")
    target_uid = args.get("target_user_id")

    if not rid:
        return {"success": False, "message": "缺少 resource_id", "execution_summary": "缺少 resource_id"}
    rid = int(rid)

    if not operator_user_id:
        return {"success": False, "message": "无法确定当前操作用户", "execution_summary": "无法确定当前操作用户"}

    role_fn = {"project": get_project_access_role, "customer": get_customer_access_role, "calendar_event": get_calendar_event_access_role}.get(rt)
    if not role_fn:
        return {"success": False, "message": f"不支持的资源类型: {rt}", "execution_summary": f"不支持的资源类型: {rt}"}

    role = await role_fn(db, rid, operator_user_id)
    type_label = {"project": "项目", "customer": "客户", "calendar_event": "日程"}.get(rt, rt)

    if action == "list":
        if role == "none":
            logger.warning("collaborator action denied: user=%s has no access to %s id=%s for list", operator_user_id, rt, rid)
            return {"success": False, "message": f"你无权查看该{type_label}的协作成员", "execution_summary": "无权限"}
        list_fn = {"project": list_project_collaborators, "customer": list_customer_collaborators, "calendar_event": list_calendar_event_collaborators}[rt]
        items = await list_fn(db, rid)
        if not items:
            return {"success": True, "result": [], "execution_summary": f"该{type_label}暂无共享成员"}
        names = [c.get("display_name") or c.get("username") or f"用户{c['user_id']}" for c in items]
        return {"success": True, "result": items, "execution_summary": f"该{type_label}共有 {len(items)} 位协作者：{'、'.join(names)}"}

    if role != "owner":
        logger.warning("collaborator action denied: user=%s role=%s cannot manage collaborators for %s id=%s", operator_user_id, role, rt, rid)
        return {"success": False, "message": f"你是该{type_label}的{'协作者' if role == 'collaborator' else '无关用户'}，不能管理共享成员", "execution_summary": "无权限管理共享成员"}

    if not target_uid:
        return {"success": False, "message": "缺少 target_user_id", "execution_summary": "缺少 target_user_id"}
    target_uid = int(target_uid)

    try:
        if action == "add":
            add_fn = {"project": add_project_collaborator, "customer": add_customer_collaborator, "calendar_event": add_calendar_event_collaborator}[rt]
            row = await add_fn(db, rid, target_uid, operator_user_id)
            await write_audit_log(
                db, action=f"{rt}_add_collaborator", actor_user_id=operator_user_id,
                target_type=rt, target_id=str(rid),
                detail=f"AI added collaborator user_id={target_uid}",
                metadata_json={"collaborator_user_id": target_uid},
            )
            from app.services.collaboration_service import _get_user_brief
            brief = await _get_user_brief(db, target_uid)
            return {"success": True, "execution_summary": f"已将{brief.get('display_name', target_uid)}添加为该{type_label}的协作者"}
        elif action == "remove":
            remove_fn = {"project": remove_project_collaborator, "customer": remove_customer_collaborator, "calendar_event": remove_calendar_event_collaborator}[rt]
            await remove_fn(db, rid, target_uid)
            await write_audit_log(
                db, action=f"{rt}_remove_collaborator", actor_user_id=operator_user_id,
                target_type=rt, target_id=str(rid),
                detail=f"AI removed collaborator user_id={target_uid}",
                metadata_json={"collaborator_user_id": target_uid},
            )
            from app.services.collaboration_service import _get_user_brief
            brief = await _get_user_brief(db, target_uid)
            return {"success": True, "execution_summary": f"已将{brief.get('display_name', target_uid)}从该{type_label}的协作者中移除"}
        else:
            return {"success": False, "message": f"不支持的操作: {action}", "execution_summary": f"不支持的操作: {action}"}
    except Exception as e:
        return {"success": False, "message": str(e), "execution_summary": str(e)}


async def _handle_add_resource_activity(
    db: AsyncSession,
    args: dict[str, Any],
    *,
    operator_source: str = "ai",
    operator_external_id: str | None = None,
    operator_user_id: int | None = None,
) -> dict[str, Any]:
    from app.services.collaboration_service import (
        add_project_activity, add_customer_followup, add_calendar_event_comment,
        require_at_least_collaborator,
    )
    from app.services.audit_log_service import write_audit_log

    rt = args.get("resource_type", "")
    rid = args.get("resource_id")
    content = args.get("content", "")

    if not rid:
        return {"success": False, "message": "缺少 resource_id", "execution_summary": "缺少 resource_id"}
    if not content:
        return {"success": False, "message": "内容不能为空", "execution_summary": "内容不能为空"}
    rid = int(rid)

    if not operator_user_id:
        return {"success": False, "message": "无法确定当前操作用户", "execution_summary": "无法确定当前操作用户"}

    type_label = {"project": "项目", "customer": "客户", "calendar_event": "日程"}.get(rt, rt)

    try:
        role = await require_at_least_collaborator(db, rt, rid, operator_user_id)
    except Exception:
        logger.warning("collaborator action denied: user=%s has no access to %s id=%s for add_resource_activity", operator_user_id, rt, rid)
        return {"success": False, "message": f"你无权访问该{type_label}", "execution_summary": "无权限"}

    try:
        if rt == "project":
            update_type = args.get("update_type", "note") or "note"
            await add_project_activity(db, rid, operator_user_id, content, update_type)
            action_name = "project_add_update"
            type_cn = {"progress": "进度", "note": "备注", "requirement": "需求"}.get(update_type, "更新")
            summary = f"已为该项目添加{type_cn}记录"
        elif rt == "customer":
            await add_customer_followup(db, rid, operator_user_id, content)
            action_name = "customer_add_followup"
            summary = "已为该客户添加跟进记录"
        elif rt == "calendar_event":
            await add_calendar_event_comment(db, rid, operator_user_id, content)
            action_name = "calendar_event_add_comment"
            summary = "已为该日程添加评论"
        else:
            return {"success": False, "message": f"不支持的资源类型: {rt}", "execution_summary": f"不支持的资源类型: {rt}"}

        await write_audit_log(
            db, action=action_name, actor_user_id=operator_user_id,
            target_type=rt, target_id=str(rid), detail=f"AI: {content[:100]}",
        )
        return {"success": True, "execution_summary": summary}
    except Exception as e:
        return {"success": False, "message": str(e), "execution_summary": str(e)}


async def _handle_transfer_owner(
    db: AsyncSession,
    args: dict[str, Any],
    *,
    operator_source: str = "ai",
    operator_external_id: str | None = None,
    operator_user_id: int | None = None,
) -> dict[str, Any]:
    from app.services.collaboration_service import (
        create_pending_transfer, get_project_access_role, get_customer_access_role,
        get_calendar_event_access_role, _get_user_brief,
    )
    from app.services.audit_log_service import write_audit_log

    rt = args.get("resource_type", "")
    rid = args.get("resource_id")
    target_uid = args.get("target_user_id")

    if not rid or not target_uid:
        return {"success": False, "message": "缺少 resource_id 或 target_user_id", "execution_summary": "参数不完整"}
    rid, target_uid = int(rid), int(target_uid)

    if not operator_user_id:
        return {"success": False, "message": "无法确定当前操作用户", "execution_summary": "无法确定当前操作用户"}

    type_label = {"project": "项目", "customer": "客户", "calendar_event": "日程"}.get(rt, rt)
    role_fn = {"project": get_project_access_role, "customer": get_customer_access_role, "calendar_event": get_calendar_event_access_role}.get(rt)
    if not role_fn:
        return {"success": False, "message": f"不支持的资源类型: {rt}", "execution_summary": f"不支持的资源类型: {rt}"}

    role = await role_fn(db, rid, operator_user_id)
    if role != "owner":
        logger.warning("owner transfer denied: user=%s role=%s cannot transfer %s id=%s", operator_user_id, role, rt, rid)
        return {"success": False, "message": f"你不是该{type_label}的负责人，无法转移归属", "execution_summary": "无权限转移"}

    if target_uid == operator_user_id:
        return {"success": False, "message": "不能将负责人转移给自己", "execution_summary": "不能转给自己"}

    from app.models.user import User
    target = await db.get(User, target_uid)
    if not target or not target.is_active:
        return {"success": False, "message": "目标用户不存在或已停用", "execution_summary": "目标用户无效"}

    pending = await create_pending_transfer(db, operator_user_id, rt, rid, target_uid)
    target_brief = await _get_user_brief(db, target_uid)

    await write_audit_log(
        db, action="pending_transfer_action_created", actor_user_id=operator_user_id,
        target_type=rt, target_id=str(rid),
        detail=f"pending transfer to user_id={target_uid}",
        metadata_json={"pending_id": pending.id, "target_user_id": target_uid},
    )

    target_name = target_brief.get("display_name", str(target_uid))
    return {
        "success": True,
        "pending_confirmation": True,
        "execution_summary": f"已创建待确认的{type_label}负责人转移操作。请确认：你确定要把该{type_label}的负责人转移给「{target_name}」吗？转移后，{target_name}将成为新的负责人，你将自动保留为协作者。请回复「确认转移」继续，或回复「取消」终止。",
    }


async def _handle_confirm_or_cancel_transfer(
    db: AsyncSession,
    args: dict[str, Any],
    *,
    operator_source: str = "ai",
    operator_external_id: str | None = None,
    operator_user_id: int | None = None,
) -> dict[str, Any]:
    from app.services.collaboration_service import confirm_pending_transfer, cancel_pending_transfer

    action = args.get("action", "")
    if not operator_user_id:
        return {"success": False, "message": "无法确定当前操作用户", "execution_summary": "无法确定当前操作用户"}

    if action == "confirm":
        result = await confirm_pending_transfer(db, operator_user_id)
    elif action == "cancel":
        result = await cancel_pending_transfer(db, operator_user_id)
    else:
        return {"success": False, "message": f"不支持的操作: {action}", "execution_summary": f"不支持的操作: {action}"}

    result["execution_summary"] = result.get("message", "操作完成")
    return result


async def _handle_suggest_schedule(
    db: AsyncSession,
    args: dict[str, Any],
    *,
    operator_source: str = "ai",
    operator_external_id: str | None = None,
    operator_user_id: int | None = None,
) -> dict[str, Any]:
    from app.services.schedule_suggestion_service import suggest_schedule

    if not operator_user_id:
        return {"success": False, "message": "无法确定当前操作用户", "execution_summary": "无法确定当前操作用户"}

    text = args.get("text", "")
    title = args.get("title", "")
    event_type = args.get("event_type", "meeting")
    source_map = {"feishu_private": "feishu_private", "feishu_group": "feishu_group", "feishu": "feishu_private"}
    source = source_map.get(operator_source, "web")

    if not title:
        return {"success": False, "message": "请提供日程标题", "execution_summary": "缺少日程标题"}

    result = await suggest_schedule(
        db,
        actor_user_id=operator_user_id,
        text=text,
        title=title,
        source_channel=source,
        event_type=event_type,
    )
    return result


async def _handle_auto_schedule_event(
    db: AsyncSession,
    args: dict[str, Any],
    *,
    operator_source: str = "ai",
    operator_external_id: str | None = None,
    operator_user_id: int | None = None,
) -> dict[str, Any]:
    from app.services.schedule_suggestion_service import auto_schedule_event

    if not operator_user_id:
        return {"success": False, "message": "无法确定当前操作用户", "execution_summary": "无法确定当前操作用户"}
    text = args.get("text", "")
    title = args.get("title", "")
    event_type = args.get("event_type", "meeting")
    if not title:
        return {"success": False, "message": "请提供日程标题", "execution_summary": "缺少日程标题"}
    return await auto_schedule_event(
        db,
        actor_user_id=operator_user_id,
        text=text,
        title=title,
        event_type=event_type,
    )


async def _handle_confirm_or_cancel_schedule(
    db: AsyncSession,
    args: dict[str, Any],
    *,
    operator_source: str = "ai",
    operator_external_id: str | None = None,
    operator_user_id: int | None = None,
) -> dict[str, Any]:
    from app.services.schedule_suggestion_service import (
        confirm_pending_schedule,
        cancel_pending_schedule,
        suggest_schedule,
        get_latest_pending_schedule,
    )

    if not operator_user_id:
        return {"success": False, "message": "无法确定当前操作用户", "execution_summary": "无法确定当前操作用户"}

    action = args.get("action", "")

    if action == "confirm":
        result = await confirm_pending_schedule(db, operator_user_id)
    elif action == "cancel":
        result = await cancel_pending_schedule(db, operator_user_id)
    elif action == "regenerate":
        from app.services.audit_log_service import write_audit_log

        pending = await get_latest_pending_schedule(db, operator_user_id)
        if pending and pending.payload_json:
            title = pending.payload_json.get("title", "未命名")
            original_text = pending.payload_json.get("original_text", "本周或下周")
            source_channel = pending.payload_json.get("source_channel", "web")

            pending.status = "cancelled"
            await db.flush()

            await write_audit_log(
                db,
                action="ai_schedule_suggestion_cancelled",
                actor_user_id=operator_user_id,
                target_type="pending_ai_action",
                target_id=str(pending.id),
                detail="cancelled schedule suggestion (regenerate)",
            )

            result = await suggest_schedule(
                db,
                actor_user_id=operator_user_id,
                text=original_text,
                title=title,
                source_channel=source_channel,
            )
        else:
            result = {"success": False, "message": "没有待确认的日程安排建议可重新生成。请告诉我你想安排什么事项。"}
    else:
        result = {"success": False, "message": f"不支持的操作: {action}"}

    result["execution_summary"] = result.get("message", "操作完成")
    return result


async def _handle_execute_candidate_schedule_strategy(
    db: AsyncSession,
    args: dict[str, Any],
    *,
    operator_source: str = "ai",
    operator_external_id: str | None = None,
    operator_user_id: int | None = None,
) -> dict[str, Any]:
    from app.services.schedule_suggestion_service import execute_candidate_schedule_strategy

    if not operator_user_id:
        return {"success": False, "message": "无法确定当前操作用户", "execution_summary": "无法确定当前操作用户"}

    candidate_dates = args.get("candidate_dates")
    if isinstance(candidate_dates, str):
        candidate_dates = [candidate_dates]
    if not isinstance(candidate_dates, list):
        candidate_dates = None

    return await execute_candidate_schedule_strategy(
        db,
        actor_user_id=operator_user_id,
        base_event_id=int(args["base_event_id"]) if args.get("base_event_id") is not None else None,
        candidate_dates=[str(x) for x in candidate_dates] if candidate_dates else None,
        time_point=str(args.get("time_point")) if args.get("time_point") is not None else None,
        title=str(args.get("title")) if args.get("title") is not None else None,
        strategy=str(args.get("strategy") or "create_all_candidates"),
        auto_cancel_others_on_complete=bool(args.get("auto_cancel_others_on_complete")),
        event_type=str(args.get("event_type") or "meeting"),
        original_text=str(args.get("text") or args.get("original_text") or ""),
    )


TOOL_MAP: dict[str, Callable[..., Awaitable[dict[str, Any]]]] = {
    "resolve_project": _handle_resolve_project,
    "resolve_customer": _handle_resolve_customer,
    "update_project": _handle_update_project,
    "update_customer": _handle_update_customer,
    "create_customer_interaction": _handle_create_customer_interaction,
    "resolve_user": _handle_resolve_user,
    "manage_collaborator": _handle_manage_collaborator,
    "add_resource_activity": _handle_add_resource_activity,
    "transfer_owner": _handle_transfer_owner,
    "confirm_or_cancel_transfer": _handle_confirm_or_cancel_transfer,
    "suggest_schedule": _handle_suggest_schedule,
    "auto_schedule_event": _handle_auto_schedule_event,
    "confirm_or_cancel_schedule": _handle_confirm_or_cancel_schedule,
    "execute_candidate_schedule_strategy": _handle_execute_candidate_schedule_strategy,
}


# ---------- 权限预留：当前默认全部允许 ----------
def can_query(*_: Any, **__: Any) -> bool:
    return True


def can_update(*_: Any, **__: Any) -> bool:
    return True


def can_delete(*_: Any, **__: Any) -> bool:
    return True


def can_undo(*_: Any, **__: Any) -> bool:
    return True


# ---------- 遗留工具：list / create / upsert / update_project_fields 等 ----------

async def _execute_legacy_tool(
    db: AsyncSession,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    operator_source: str = "ai",
    operator_external_id: str | None = None,
    operator_user_id: int | None = None,
) -> dict[str, Any]:
    """保留 list / create / upsert / update_project_fields 等；operator_user_id 有值时按归属隔离。"""
    if tool_name == "list_projects":
        stmt = select(Project).order_by(Project.id)
        if operator_user_id is not None:
            collab_exists = exists().where(
                ProjectCollaborator.project_id == Project.id,
                ProjectCollaborator.user_id == operator_user_id,
            )
            stmt = stmt.where(or_(Project.owner_user_id == operator_user_id, collab_exists))
            logger.info("project query executed under bound_user_id=%s", operator_user_id)
        result = await db.execute(stmt)
        rows = list(result.scalars().all())
        data = [ProjectInDB.model_validate(r).model_dump(mode="json") for r in rows]
        return {"success": True, "result": data, "execution_summary": f"共 {len(data)} 个项目"}

    if tool_name == "list_all_projects":
        stmt = select(Project).order_by(Project.deadline.asc().nulls_last(), Project.id)
        if operator_user_id is not None:
            collab_exists = exists().where(
                ProjectCollaborator.project_id == Project.id,
                ProjectCollaborator.user_id == operator_user_id,
            )
            stmt = stmt.where(or_(Project.owner_user_id == operator_user_id, collab_exists))
        owner_filter = arguments.get("owner") if isinstance(arguments.get("owner"), str) else None
        if owner_filter and owner_filter.strip():
            stmt = stmt.where(Project.owner.ilike(f"%{owner_filter.strip()}%"))
        result = await db.execute(stmt)
        rows = list(result.scalars().all())
        key_fields = ["project_no", "name", "deadline", "goal", "owner", "update_date"]
        data = []
        for r in rows:
            raw = ProjectInDB.model_validate(r).model_dump(mode="json")
            item = {k: raw.get(k) for k in key_fields if k in raw}
            if item.get("deadline") and isinstance(item["deadline"], str):
                item["deadline"] = item["deadline"].split("T")[0]
            if item.get("update_date") and isinstance(item["update_date"], str):
                item["update_date"] = item["update_date"].replace("Z", "").split(".")[0][:19]
            data.append(item)
        return {
            "success": True,
            "result": data,
            "execution_summary": f"共 {len(data)} 个项目（已脱敏）",
        }

    if tool_name == "list_customers":
        stmt = select(Customer).order_by(Customer.id)
        if operator_user_id is not None:
            collab_exists = exists().where(
                CustomerCollaborator.customer_id == Customer.id,
                CustomerCollaborator.user_id == operator_user_id,
            )
            stmt = stmt.where(or_(Customer.owner_user_id == operator_user_id, collab_exists))
        result = await db.execute(stmt)
        rows = list(result.scalars().all())
        data = [CustomerInDB.model_validate(r).model_dump(mode="json") for r in rows]
        return {"success": True, "result": data, "execution_summary": f"共 {len(data)} 个客户"}

    if tool_name in ("create_project", "upsert_project"):
        project_name = arguments.get("project_name") or arguments.get("name")
        owner = arguments.get("owner")
        deadline = arguments.get("deadline")
        if not project_name or not str(project_name).strip():
            return {
                "success": False,
                "error": "missing required fields",
                "execution_summary": "缺少必填项：项目名称 (name / project_name)",
            }
        payload = {**arguments, "name": project_name.strip()}
        if payload.get("owner_user_id") is None:
            if operator_user_id is not None:
                payload["owner_user_id"] = operator_user_id
            else:
                return {
                    "success": False,
                    "error": "无法创建项目：缺少当前操作者用户 ID",
                    "execution_summary": "无法创建项目：缺少当前操作者用户 ID",
                }
        try:
            body = ProjectCreate.model_validate(payload)
        except Exception as e:
            logger.exception("create_project/upsert_project validation failed")
            return {"success": False, "error": str(e), "execution_summary": str(e)}
        project_no = getattr(body, "project_no", None)
        if not project_no or not str(project_no).strip():
            project_no = await _get_next_project_no(db)
        else:
            project_no = str(project_no).strip()
        try:
            orm = Project(
                project_no=project_no,
                name=body.name,
                deadline=body.deadline,
                goal=body.goal,
                owner=body.owner,
                requirements=body.requirements,
                customer_name=body.customer_name,
                update_date=datetime.now(timezone.utc),
                owner_user_id=operator_user_id if operator_user_id is not None else None,
            )
            db.add(orm)
            await db.flush()
            await db.refresh(orm)
            new_value = _project_to_log_value(orm)
            log = AuditLog(
                target_type=TARGET_TYPE_PROJECT,
                target_id=orm.id,
                action=ACTION_CREATE,
                old_value=None,
                new_value=new_value,
                operator_source=operator_source,
                operator_external_id=operator_external_id,
            )
            db.add(log)
            await db.flush()
            # 关联客户：customer_ids 或 customer_names（解析后）
            customer_ids_arg = arguments.get("customer_ids")
            customer_names_arg = arguments.get("customer_names")
            ids_to_link: list[int] = []
            if customer_ids_arg is not None:
                if isinstance(customer_ids_arg, (list, tuple)):
                    for x in customer_ids_arg:
                        try:
                            ids_to_link.append(int(x))
                        except (TypeError, ValueError):
                            pass
                else:
                    try:
                        ids_to_link.append(int(customer_ids_arg))
                    except (TypeError, ValueError):
                        pass
            names_to_resolve: list[str] = []
            if customer_names_arg is not None:
                if isinstance(customer_names_arg, (list, tuple)):
                    names_to_resolve = [str(x).strip() for x in customer_names_arg if x and str(x).strip()]
                elif customer_names_arg:
                    names_to_resolve = [str(customer_names_arg).strip()]
            for name in names_to_resolve:
                resolve_result = await resolve_customer_impl(db, name, owner_user_id=operator_user_id)
                if resolve_result.get("success") and resolve_result.get("customer_id") is not None:
                    cid = resolve_result["customer_id"]
                    if cid not in ids_to_link:
                        ids_to_link.append(cid)
                elif resolve_result.get("candidates"):
                    await db.rollback()
                    return {
                        "success": False,
                        "error": "客户歧义",
                        "execution_summary": f"客户「{name}」存在多个匹配，请补充更具体的名称或公司。",
                        "candidates": resolve_result.get("candidates"),
                    }
                else:
                    await db.rollback()
                    return {
                        "success": False,
                        "error": "未找到客户",
                        "execution_summary": f"未找到唯一匹配的客户「{name}」，请确认名称。",
                    }
            for cid in ids_to_link:
                db.add(ProjectCustomer(project_id=orm.id, customer_id=cid))
            if ids_to_link:
                orm.customer_id = ids_to_link[0]
            await db.flush()
            await db.refresh(orm)
            data = ProjectInDB.model_validate(orm).model_dump(mode="json")
            summary_parts = ["已创建项目【" + body.name + "】。"]
            if ids_to_link:
                summary_parts.append("已关联 " + str(len(ids_to_link)) + " 个客户。")
            summary_parts.append("可前往项目详情页查看。")
            return {
                "success": True,
                "data": data,
                "result": {
                    **data,
                    "project_id": orm.id,
                    "project_no": (orm.project_no or "").strip(),
                    "name": (orm.name or "").strip(),
                    "detail_url": f"/projects/{orm.id}",
                    "customer_ids": ids_to_link,
                },
                "execution_summary": "".join(summary_parts),
            }
        except Exception as e:
            logger.exception("create_project/upsert_project execution failed")
            return {"success": False, "error": str(e), "execution_summary": str(e)}

    if tool_name == "update_project_fields":
        project_id = arguments.get("project_id")
        project_name = arguments.get("project_name")
        orm = None
        if project_id is not None:
            orm = await db.get(Project, int(project_id))
            if orm and operator_user_id is not None and orm.owner_user_id != operator_user_id:
                orm = None  # 无权限
        elif project_name:
            resolved = await resolve_project_impl(db, (project_name or "").strip(), owner_user_id=operator_user_id)
            if resolved and resolved.get("success"):
                orm = await db.get(Project, resolved["project_id"])
        if orm is None:
            msg = "未找到项目"
            if project_name:
                resolved = await resolve_project_impl(db, (project_name or "").strip(), owner_user_id=operator_user_id)
                if isinstance(resolved, dict):
                    msg = resolved.get("message", msg)
            return {"success": False, "error": msg, "execution_summary": msg}
        old_value = _project_to_log_value(orm)
        update_data = {
            CN_FIELD_MAP.get(k, k): v for k, v in arguments.items()
            if k not in ("project_id", "project_name") and v is not None
        }
        updated_labels = []
        for key, value in update_data.items():
            if hasattr(orm, key):
                if key == "deadline" and isinstance(value, str):
                    value = date.fromisoformat(value.split("T")[0]) if value else None
                setattr(orm, key, value)
                label = next((cn for cn, en in CN_FIELD_MAP.items() if en == key), key)
                updated_labels.append(label)
        orm.update_date = datetime.now(timezone.utc)
        await db.flush()
        await db.refresh(orm)
        new_value = _project_to_log_value(orm)
        log = AuditLog(
            target_type=TARGET_TYPE_PROJECT,
            target_id=orm.id,
            action=ACTION_UPDATE,
            old_value=old_value,
            new_value=new_value,
            operator_source=operator_source,
            operator_external_id=operator_external_id,
        )
        db.add(log)
        await db.flush()
        project_no_display = (orm.project_no or "").strip() or f"id={orm.id}"
        fields_str = "、".join(updated_labels) if updated_labels else "（无字段变更）"
        summary = f"成功更新 {project_no_display} 的 {fields_str}"
        return {
            "success": True,
            "result": ProjectInDB.model_validate(orm).model_dump(mode="json"),
            "execution_summary": summary,
        }

    if tool_name == "create_customer":
        body = CustomerCreate.model_validate(arguments)
        orm = Customer(
            name=body.name,
            origin=body.origin,
            company=body.company,
            profile=body.profile,
            contact=body.contact,
            future_direction=body.future_direction,
            owner_user_id=operator_user_id if operator_user_id is not None else None,
        )
        db.add(orm)
        await db.flush()
        await db.refresh(orm)
        new_value = _customer_to_log_value(orm)
        log = AuditLog(
            target_type=TARGET_TYPE_CUSTOMER,
            target_id=orm.id,
            action=ACTION_CREATE,
            old_value=None,
            new_value=new_value,
            operator_source=operator_source,
            operator_external_id=operator_external_id,
        )
        db.add(log)
        await db.flush()
        data = CustomerInDB.model_validate(orm).model_dump(mode="json")
        return {
            "success": True,
            "result": data,
            "execution_summary": f"已为您创建客户 [{body.name}]",
        }

    if tool_name == "get_calendar_events":
        return await get_calendar_events(
            db,
            start=arguments.get("start"),
            end=arguments.get("end"),
            project_id=int(arguments["project_id"]) if arguments.get("project_id") is not None else None,
            owner_user_id=operator_user_id,
        )

    if tool_name == "create_calendar_event":
        return await create_calendar_event(
            db,
            title=arguments.get("title") or "未命名",
            start_time=arguments.get("start_time") or "",
            end_time=arguments.get("end_time") or "",
            description=arguments.get("description"),
            type=arguments.get("type") or "event",
            project_id=int(arguments["project_id"]) if arguments.get("project_id") is not None else None,
            status=arguments.get("status"),
            candidate_group_id=arguments.get("candidate_group_id"),
            candidate_policy=arguments.get("candidate_policy"),
            auto_cancel_others_on_complete=arguments.get("auto_cancel_others_on_complete"),
            owner_user_id=operator_user_id,
        )

    if tool_name == "update_calendar_event":
        event_id = arguments.get("event_id")
        if event_id is None:
            return {"success": False, "error": "缺少 event_id", "execution_summary": "缺少 event_id"}
        return await update_calendar_event(
            db,
            event_id=int(event_id),
            title=arguments.get("title"),
            start_time=arguments.get("start_time"),
            end_time=arguments.get("end_time"),
            description=arguments.get("description"),
            type=arguments.get("type"),
            project_id=int(arguments["project_id"]) if arguments.get("project_id") is not None else None,
            status=arguments.get("status"),
            candidate_group_id=arguments.get("candidate_group_id"),
            candidate_policy=arguments.get("candidate_policy"),
            auto_cancel_others_on_complete=arguments.get("auto_cancel_others_on_complete"),
            owner_user_id=operator_user_id,
        )

    if tool_name == "delete_calendar_event":
        event_id = arguments.get("event_id")
        if event_id is None:
            return {"success": False, "error": "缺少 event_id", "execution_summary": "缺少 event_id"}
        return await delete_calendar_event(db, int(event_id), owner_user_id=operator_user_id)

    if tool_name == "execute_compound_schedule":
        from app.services.compound_schedule_service import execute_compound_schedule_plan

        txt = (arguments.get("text") or arguments.get("original_text") or "").strip()
        if not txt:
            return {"success": False, "error": "缺少 text（用户原文）", "execution_summary": "缺少原文"}
        pid = arguments.get("project_id")
        raw = await execute_compound_schedule_plan(
            db,
            txt,
            operator_user_id=operator_user_id,
            project_id=int(pid) if pid is not None else None,
            operator_source=operator_source,
        )
        return {
            "success": raw.get("success"),
            "result": raw.get("result"),
            "execution_summary": raw.get("execution_summary") or "",
            "error": raw.get("error"),
            "message": raw.get("assistant_text"),
        }

    if tool_name == "create_reminder_task":
        from app.services.reminder_service import create_reminder_task_service

        sr = arguments.get("schedule_rule")
        if isinstance(sr, str):
            try:
                sr = json.loads(sr)
            except json.JSONDecodeError:
                sr = None
        if sr is not None and not isinstance(sr, dict):
            sr = None
        raw_ch = str(arguments.get("channel") or "").strip()
        if operator_source == "web":
            channel = "local" if raw_ch in ("", "feishu_private") else raw_ch
        else:
            channel = raw_ch or "feishu_private"
        return await create_reminder_task_service(
            db,
            operator_user_id=operator_user_id,
            title=str(arguments.get("title") or ""),
            content=arguments.get("content"),
            channel=channel,
            reminder_type=str(arguments.get("reminder_type") or "one_time"),
            schedule_rule=sr,
            related_event_id=int(arguments["related_event_id"]) if arguments.get("related_event_id") is not None else None,
            related_project_id=int(arguments["related_project_id"]) if arguments.get("related_project_id") is not None else None,
            related_customer_id=int(arguments["related_customer_id"]) if arguments.get("related_customer_id") is not None else None,
            end_at=arguments.get("end_at"),
            trigger_at=arguments.get("trigger_at"),
            operator_source=operator_source,
        )

    if tool_name == "list_reminder_tasks":
        from app.services.reminder_service import list_reminder_tasks_service

        sf = arguments.get("status")
        return await list_reminder_tasks_service(
            db,
            operator_user_id=operator_user_id,
            status_filter=str(sf) if sf else None,
        )

    if tool_name == "cancel_reminder_task":
        from app.services.reminder_service import cancel_reminder_task_service

        tid = arguments.get("task_id") or arguments.get("reminder_task_id")
        if tid is None:
            return {"success": False, "error": "缺少 task_id", "execution_summary": "缺少 task_id"}
        return await cancel_reminder_task_service(db, operator_user_id=operator_user_id, task_id=int(tid))

    if tool_name == "update_reminder_task":
        from app.services.reminder_service import update_reminder_task_service

        tid = arguments.get("task_id") or arguments.get("reminder_task_id")
        if tid is None:
            return {"success": False, "error": "缺少 task_id", "execution_summary": "缺少 task_id"}
        sr = arguments.get("schedule_rule")
        if isinstance(sr, str):
            try:
                sr = json.loads(sr)
            except json.JSONDecodeError:
                sr = None
        if sr is not None and not isinstance(sr, dict):
            sr = None
        return await update_reminder_task_service(
            db,
            operator_user_id=operator_user_id,
            task_id=int(tid),
            title=arguments.get("title"),
            content=arguments.get("content"),
            end_at=arguments.get("end_at"),
            is_enabled=arguments.get("is_enabled") if arguments.get("is_enabled") is not None else None,
            schedule_rule=sr,
            status=arguments.get("status"),
        )

    return {"success": False, "error": f"未知工具: {tool_name}", "execution_summary": f"未知工具: {tool_name}"}


async def execute_tool_call(
    db: AsyncSession,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    operator_source: str = "ai",
    operator_external_id: str | None = None,
    operator_user_id: int | None = None,
) -> dict[str, Any]:
    """
    执行单条 tool 调用。优先走 TOOL_MAP（resolve_* / update_*），否则走遗留工具；每次执行后写 SystemLog。
    operator_user_id：飞书群聊/私聊时传入 bound_user_id，用于按用户隔离数据（查询/修改归属）。
    """
    logger.info("Tool call: %s params=%s operator_user_id=%s", tool_name, arguments, operator_user_id)
    if tool_name in ("list_projects", "list_customers", "list_all_projects", "get_calendar_events", "resolve_project", "resolve_customer", "resolve_user", "list_reminder_tasks") and not can_query(tool_name=tool_name, arguments=arguments, operator_source=operator_source, operator_external_id=operator_external_id):
        return {"success": False, "error": "permission denied", "execution_summary": "无权限执行查询"}
    if tool_name in ("update_project", "update_customer", "update_project_fields", "create_project", "upsert_project", "create_customer", "create_calendar_event", "update_calendar_event", "create_customer_interaction", "manage_collaborator", "add_resource_activity", "transfer_owner", "confirm_or_cancel_transfer", "suggest_schedule", "auto_schedule_event", "confirm_or_cancel_schedule", "execute_candidate_schedule_strategy", "create_reminder_task", "cancel_reminder_task", "update_reminder_task", "execute_compound_schedule") and not can_update(tool_name=tool_name, arguments=arguments, operator_source=operator_source, operator_external_id=operator_external_id):
        return {"success": False, "error": "permission denied", "execution_summary": "无权限执行修改"}
    if tool_name in ("delete_calendar_event",) and not can_delete(tool_name=tool_name, arguments=arguments, operator_source=operator_source, operator_external_id=operator_external_id):
        return {"success": False, "error": "permission denied", "execution_summary": "无权限执行删除"}
    if tool_name in ("undo_project", "undo_customer") and not can_undo(tool_name=tool_name, arguments=arguments, operator_source=operator_source, operator_external_id=operator_external_id):
        return {"success": False, "error": "permission denied", "execution_summary": "无权限执行撤销"}

    try:
        if tool_name in TOOL_MAP:
            handler = TOOL_MAP[tool_name]
            result = await handler(
                db,
                arguments,
                operator_source=operator_source,
                operator_external_id=operator_external_id,
                operator_user_id=operator_user_id,
            )
            if not isinstance(result, dict):
                result = {"success": True, "data": result, "execution_summary": "执行完成"}
            elif not result.get("success") and "message" in result and "error" not in result:
                result["error"] = result["message"]
            db.add(SystemLog(level="INFO", module="AI_TOOL", message=f"{tool_name} executed"))
            await db.flush()
            logger.info("Tool result: %s success=%s", tool_name, result.get("success"))
            return result
        result = await _execute_legacy_tool(
            db,
            tool_name,
            arguments,
            operator_source=operator_source,
            operator_external_id=operator_external_id,
            operator_user_id=operator_user_id,
        )
        if not isinstance(result, dict):
            result = {"success": True, "data": result, "execution_summary": "执行完成"}
        db.add(SystemLog(level="INFO", module="AI_TOOL", message=f"{tool_name} executed"))
        await db.flush()
        logger.info("Tool result: %s success=%s", tool_name, result.get("success"))
        return result
    except Exception as e:
        logger.exception("Tool execution failed: %s", tool_name)
        result = {"success": False, "error": str(e), "message": str(e), "execution_summary": str(e)}
        return result


async def execute_tool_calls(
    db: AsyncSession,
    tool_calls: list[dict[str, Any]],
    *,
    operator_source: str = "ai",
    operator_external_id: str | None = None,
    operator_user_id: int | None = None,
) -> list[dict[str, Any]]:
    """批量执行 tool_calls（Ollama 返回格式）。operator_user_id 用于飞书按用户隔离。"""
    results = []
    for tc in tool_calls:
        fn = tc.get("function") or tc.get("function_call")
        if not fn:
            results.append({"success": False, "error": "缺少 function", "execution_summary": "缺少 function"})
            continue
        name = fn.get("name") if isinstance(fn, dict) else getattr(fn, "name", None)
        raw_args = fn.get("arguments") if isinstance(fn, dict) else getattr(fn, "arguments", "{}")
        if isinstance(raw_args, str):
            try:
                arguments = json.loads(raw_args)
            except json.JSONDecodeError:
                arguments = {}
        else:
            arguments = raw_args or {}
        out = await execute_tool_call(
            db,
            name,
            arguments,
            operator_source=operator_source,
            operator_external_id=operator_external_id,
            operator_user_id=operator_user_id,
        )
        out["tool_call_id"] = tc.get("id")
        out["tool_name"] = name
        results.append(out)
    return results
