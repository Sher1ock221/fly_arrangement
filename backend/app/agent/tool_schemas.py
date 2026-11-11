from __future__ import annotations

import copy
from typing import Any

from app.schemas.customer import CustomerCreate, CustomerUpdate
from app.schemas.project import ProjectCreate, ProjectUpdate


def build_tool_schemas() -> list[dict[str, Any]]:
    """基于 Project/Customer 的 Pydantic Schema 生成 Ollama 兼容的 tools 定义；含 resolve_* 与 update_* 规范。"""
    project_update_schema = ProjectUpdate.model_json_schema()
    project_create_schema = ProjectCreate.model_json_schema()
    customer_update_schema = CustomerUpdate.model_json_schema()
    customer_create_schema = CustomerCreate.model_json_schema()

    return [
        # ---------- 实体解析：必须先调用再 update ----------
        {
            "type": "function",
            "function": {
                "name": "resolve_project",
                "description": "根据项目名称或编号查询项目",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "resolve_customer",
                "description": "根据客户名称或公司名解析出 customer_id。必须先调用此工具获得 customer_id 后，再调用 update_customer。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "客户名称或公司名称"},
                    },
                    "required": ["query"],
                },
            },
        },
        # ---------- 按 id 更新（需先 resolve 获得 id） ----------
        {
            "type": "function",
            "function": {
                "name": "update_project",
                "description": "更新项目字段；需 project_id（通常先 resolve_project）。customer_ids/customer_names 更新关联客户；append=true 追加、false 覆盖。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "integer"},
                        "name": {"type": "string"},
                        "owner": {"type": "string"},
                        "deadline": {"type": "string"},
                        "goal": {"type": "string"},
                        "requirements": {"type": "string"},
                        "customer_id": {"type": "integer", "description": "单客户兼容"},
                        "customer_ids": {"type": "array", "items": {"type": "integer"}, "description": "关联客户 ID"},
                        "customer_names": {"type": "array", "items": {"type": "string"}, "description": "关联客户名→解析为 ID"},
                        "append": {"type": "boolean", "description": "关联客户：true 追加，false 覆盖"},
                    },
                    "required": ["project_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "update_customer",
                "description": "更新客户信息。可传 customer_id 或 customer_name（传名称时会先解析，歧义时需用户澄清）。支持字段：company, position, business_direction, notes, acquaintance_source, contact, profile, future_direction, origin 等。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "customer_id": {"type": "integer", "description": "要修改的客户 ID（与 customer_name 二选一）"},
                        "customer_name": {"type": "string", "description": "客户名称，与 customer_id 二选一；用于解析后更新"},
                        **{k: v for k, v in customer_update_schema.get("properties", {}).items() if k != "customer_id"},
                    },
                    "required": [],
                },
            },
        },
        # ---------- 新建项目 ----------
        {
            "type": "function",
            "function": {
                "name": "upsert_project",
                "description": "当用户提到新建、增加或创建一个项目时，必须调用此函数。可传 name、deadline、goal、owner、requirements；可传 customer_ids 或 customer_names 同时关联多个客户。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "项目名称，必填"},
                        "deadline": {"type": "string", "description": "截止日期，ISO 如 YYYY-MM-DD"},
                        "goal": {"type": "string", "description": "项目目标"},
                        "owner": {"type": "string", "description": "负责人"},
                        "requirements": {"type": "string", "description": "项目内需"},
                        "customer_name": {"type": "string", "description": "单客户名称（与 customer_names/customer_ids 可选）"},
                        "customer_ids": {"type": "array", "items": {"type": "integer"}, "description": "关联客户 ID 列表"},
                        "customer_names": {"type": "array", "items": {"type": "string"}, "description": "关联客户名称列表，如「韩某」「王敏」"},
                    },
                    "required": ["name"],
                },
            },
        },
        # 规范：当用户提到「修改某个项目的某个字段」且未先 resolve 时，可退化为按名称匹配（仍建议先 resolve_project）
        {
            "type": "function",
            "function": {
                "name": "update_project_fields",
                "description": "（兜底）当用户提到修改已有项目时，若未先调用 resolve_project，可用此工具通过 project_id 或 project_name 指定项目并更新字段。建议优先使用 resolve_project + update_project 流程。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "integer", "description": "项目 ID，与 project_name 二选一"},
                        "project_name": {"type": "string", "description": "项目名称或关键词，用于模糊匹配（与 project_id 二选一）"},
                        **{k: v for k, v in project_update_schema.get("properties", {}).items()},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_project",
                "description": "新建项目。必填 name；可选 deadline、goal、owner、requirements；可 customer_ids/customer_names 关联客户。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "项目名称"},
                        "deadline": {"type": "string", "description": "截止 YYYY-MM-DD"},
                        "goal": {"type": "string", "description": "目标"},
                        "owner": {"type": "string", "description": "负责人"},
                        "requirements": {"type": "string", "description": "内需"},
                        "customer_name": {"type": "string", "description": "单客户名（可选）"},
                        "customer_ids": {"type": "array", "items": {"type": "integer"}, "description": "客户 ID"},
                        "customer_names": {"type": "array", "items": {"type": "string"}, "description": "客户名列表"},
                    },
                    "required": ["name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_customer",
                "description": "新建客户；字段见 parameters（name 等必填项以 schema 为准）。",
                "parameters": {
                    "type": "object",
                    "properties": customer_create_schema.get("properties", {}),
                    "required": customer_create_schema.get("required", ["name"]),
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_projects",
                "description": "查询当前所有项目列表（用于确认项目 ID 或内容后再执行修改）。",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_all_projects",
                "description": "获取全部项目的精简列表，用于总结、统计、项目概况。若用户要求总结/统计/查看所有项目或询问项目概况，必须先调用此工具。返回仅含关键字段（项目名、截止日期、目标、负责人、更新日期），便于分类分析。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string", "description": "可选。仅列出该负责人的项目。"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_customers",
                "description": "查询当前所有客户列表（用于确认客户 ID 或内容后再执行修改）。",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_customer_interaction",
                "description": "归档客户沟通/拜访记录。需能确定客户：customer_id 优先，或 customer_name 唯一匹配；歧义则勿写入、请用户澄清。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "customer_id": {"type": "integer", "description": "客户 ID（优先）"},
                        "customer_name": {"type": "string", "description": "无 ID 时用于匹配"},
                        "meeting_time": {"type": "string", "description": "ISO 或相对词：昨天/今天/上周等"},
                        "talk_summary": {"type": "string", "description": "沟通摘要"},
                        "cooperation_direction": {"type": "string", "description": "合作方向"},
                        "cooperation_intent": {"type": "string", "description": "意向"},
                        "next_cooperation_plan": {"type": "string", "description": "下次计划"},
                        "specific_needs": {"type": "string", "description": "具体需求"},
                        "importance": {"type": "integer", "description": "1~5，重点可 4~5"},
                        "raw_input": {"type": "string", "description": "用户原文"},
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_calendar_events",
                "description": "查询日历日程列表。可按时间范围 start/end（ISO 字符串）和 project_id 筛选。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "start": {"type": "string", "description": "开始时间 ISO"},
                        "end": {"type": "string", "description": "结束时间 ISO"},
                        "project_id": {"type": "integer", "description": "项目 ID 筛选"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_calendar_event",
                "description": "创建日程；已知明确 start_time/end_time（ISO）时使用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "标题"},
                        "start_time": {"type": "string", "description": "开始时间 ISO"},
                        "end_time": {"type": "string", "description": "结束时间 ISO"},
                        "description": {"type": "string", "description": "描述"},
                        "type": {"type": "string", "enum": ["event", "project", "meeting", "task"]},
                        "project_id": {"type": "integer", "description": "关联项目 ID"},
                    },
                    "required": ["title", "start_time", "end_time"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "update_calendar_event",
                "description": "更新日历日程。需提供 event_id。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "event_id": {"type": "integer"},
                        "title": {"type": "string"},
                        "start_time": {"type": "string"},
                        "end_time": {"type": "string"},
                        "description": {"type": "string"},
                        "type": {"type": "string", "enum": ["event", "project", "meeting", "task"]},
                        "project_id": {"type": "integer"},
                    },
                    "required": ["event_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "delete_calendar_event",
                "description": "删除一条日历日程。需提供 event_id。",
                "parameters": {
                    "type": "object",
                    "properties": {"event_id": {"type": "integer"}},
                    "required": ["event_id"],
                },
            },
        },
        # ---------- 协作管理工具 ----------
        {
            "type": "function",
            "function": {
                "name": "resolve_user",
                "description": "根据用户姓名或用户名解析出 user_id。在共享资源或转移负责人时，必须先调用此工具获得目标用户 ID。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "用户姓名或用户名，如「张三」「李四」"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "manage_collaborator",
                "description": "管理资源的共享协作者。action=add 添加协作者，action=remove 移除协作者，action=list 列出协作者。仅 owner 可添加/移除协作者，owner 和 collaborator 均可查看列表。需要先通过 resolve_user 获取 target_user_id。resource_type 取值：project / customer / calendar_event。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["add", "remove", "list"], "description": "操作类型"},
                        "resource_type": {"type": "string", "enum": ["project", "customer", "calendar_event"], "description": "资源类型"},
                        "resource_id": {"type": "integer", "description": "资源 ID（项目 ID / 客户 ID / 日程 ID）"},
                        "target_user_id": {"type": "integer", "description": "目标用户 ID（add/remove 时必填）"},
                    },
                    "required": ["action", "resource_type", "resource_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "add_resource_activity",
                "description": "为 project/customer/calendar_event 写一条协作动态（进展/跟进/评论）；需明确资源与内容。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "resource_type": {"type": "string", "enum": ["project", "customer", "calendar_event"], "description": "资源类型"},
                        "resource_id": {"type": "integer", "description": "资源 ID"},
                        "content": {"type": "string", "description": "正文"},
                        "update_type": {"type": "string", "enum": ["progress", "note", "requirement"], "description": "项目用；默认 note"},
                    },
                    "required": ["resource_type", "resource_id", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "transfer_owner",
                "description": "发起资源负责人转移。仅 owner 可操作。此操作需要二次确认：第一次调用只创建待确认动作，系统会提示用户确认；用户回复「确认转移」后才真正执行。需要先通过 resolve_user 获取目标用户 ID，通过 resolve_project 或 resolve_customer 获取资源 ID。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "resource_type": {"type": "string", "enum": ["project", "customer", "calendar_event"], "description": "资源类型"},
                        "resource_id": {"type": "integer", "description": "资源 ID"},
                        "target_user_id": {"type": "integer", "description": "新负责人的用户 ID"},
                    },
                    "required": ["resource_type", "resource_id", "target_user_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "confirm_or_cancel_transfer",
                "description": "确认或取消待确认的负责人转移操作。当用户回复「确认转移」「确认」时调用 action=confirm，回复「取消」「取消转移」时调用 action=cancel。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["confirm", "cancel"], "description": "确认或取消"},
                    },
                    "required": ["action"],
                },
            },
        },
        # ---------- 智能排程工具 ----------
        {
            "type": "function",
            "function": {
                "name": "auto_schedule_event",
                "description": "自动解析时间并排程创建日程；多数安排请求首选。返回含 event_id / final_start / final_end 等。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "用户原文"},
                        "title": {"type": "string", "description": "标题"},
                        "event_type": {"type": "string", "enum": ["event", "project", "meeting", "task"], "description": "类型，默认 meeting"},
                    },
                    "required": ["text", "title"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "suggest_schedule",
                "description": "建议模式（非默认）。仅在用户明确要求“推荐几个时间再选”时调用：返回 1~3 个候选时间并创建待确认建议。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "用户原始输入全文，用于解析时间范围和时长"},
                        "title": {"type": "string", "description": "日程标题，如「和张三的需求沟通」「客户回访」「项目复盘」"},
                        "event_type": {"type": "string", "enum": ["event", "project", "meeting", "task"], "description": "日程类型，默认 meeting"},
                    },
                    "required": ["text", "title"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "confirm_or_cancel_schedule",
                "description": "确认、取消或重新生成待确认的日程安排建议。当用户回复「可以」「合适」「就这个」「确认安排」「行」「好的，安排吧」时调用 action=confirm；回复「取消」「算了」「不安排了」时调用 action=cancel；回复「换一个时间」「不行」「再找别的时间」时调用 action=regenerate 重新推荐。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["confirm", "cancel", "regenerate"], "description": "confirm=确认安排 / cancel=取消 / regenerate=重新建议"},
                    },
                    "required": ["action"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "execute_candidate_schedule_strategy",
                "description": "执行候选日程策略：将候选日期集合按同一明确时间批量创建为候选事件，并可设置互斥自动取消规则。用于「1号或2号晚上8点半」「两天都安排上」「1号完成后2号自动取消」等连续指令。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "base_event_id": {"type": "integer", "description": "可选，基于已有事件扩展候选策略"},
                        "candidate_dates": {"type": "array", "items": {"type": "string"}, "description": "候选日期列表，ISO 日期如 YYYY-MM-DD"},
                        "time_point": {"type": "string", "description": "明确时间点 HH:MM，如 20:30"},
                        "title": {"type": "string", "description": "日程标题"},
                        "strategy": {"type": "string", "enum": ["create_all_candidates"], "description": "当前仅支持批量创建候选"},
                        "auto_cancel_others_on_complete": {"type": "boolean", "description": "是否在一条确认完成后自动取消同组其它候选"},
                        "event_type": {"type": "string", "enum": ["event", "project", "meeting", "task"]},
                        "text": {"type": "string", "description": "用户原文补充，用于缺省信息回填"},
                    },
                    "required": ["strategy"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "execute_compound_schedule",
                "description": "复合多天培训/行程：主日程+子节点+（可选）每日本地提醒；传用户原文 text。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "用户原始整句需求"},
                        "project_id": {"type": "integer", "description": "可选，关联项目 ID"},
                    },
                    "required": ["text"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_reminder_task",
                "description": "创建提醒任务写入 reminder_tasks；桌面 web 仅 local。主行程用日历类工具配合。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "标题"},
                        "content": {"type": "string", "description": "正文"},
                        "channel": {
                            "type": "string",
                            "enum": ["feishu_private", "local"],
                            "description": "local=本机；feishu_private=会话通道（仅非 web）",
                        },
                        "reminder_type": {
                            "type": "string",
                            "enum": ["one_time", "recurring", "relative_to_event"],
                            "description": "one_time | recurring | relative_to_event",
                        },
                        "schedule_rule": {
                            "type": "object",
                            "description": "recurring：freq/trigger_time/by_weekdays/until；one_time：trigger_at；relative_to_event：offset_minutes、anchor",
                        },
                        "related_event_id": {"type": "integer", "description": "关联日程 ID"},
                        "related_project_id": {"type": "integer"},
                        "related_customer_id": {"type": "integer"},
                        "end_at": {"type": "string", "description": "recurring 截止 ISO"},
                        "trigger_at": {"type": "string", "description": "one_time 触发 ISO"},
                    },
                    "required": ["title", "reminder_type"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_reminder_tasks",
                "description": "列出当前用户的提醒计划；可传 status 筛选如 active。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "description": "可选：active / paused / completed / cancelled / failed"},
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "cancel_reminder_task",
                "description": "取消一条提醒计划。需 task_id；不确定时可先 list_reminder_tasks。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "integer", "description": "提醒任务 ID"},
                    },
                    "required": ["task_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "update_reminder_task",
                "description": "更新提醒：改正文、截止时间、schedule_rule、暂停(is_enabled=false)等。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "integer"},
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "end_at": {"type": "string"},
                        "is_enabled": {"type": "boolean"},
                        "schedule_rule": {"type": "object"},
                        "status": {"type": "string", "enum": ["active", "paused"]},
                    },
                    "required": ["task_id"],
                },
            },
        },
    ]


_INTENT_TOOL_NAMES: dict[str, frozenset[str]] = {
    "project": frozenset({
        "resolve_project",
        "update_project",
        "upsert_project",
        "create_project",
        "update_project_fields",
        "list_projects",
        "list_all_projects",
        "add_resource_activity",
    }),
    "customer": frozenset({
        "resolve_customer",
        "update_customer",
        "create_customer",
        "list_customers",
        "create_customer_interaction",
    }),
    "calendar": frozenset({
        "get_calendar_events",
        "create_calendar_event",
        "update_calendar_event",
        "delete_calendar_event",
        "auto_schedule_event",
        "suggest_schedule",
        "confirm_or_cancel_schedule",
        "execute_candidate_schedule_strategy",
        "execute_compound_schedule",
    }),
    "reminder": frozenset({
        "create_reminder_task",
        "list_reminder_tasks",
        "cancel_reminder_task",
        "update_reminder_task",
    }),
    "collaboration": frozenset({
        "resolve_user",
        "resolve_project",
        "resolve_customer",
        "manage_collaborator",
        "add_resource_activity",
        "transfer_owner",
        "confirm_or_cancel_transfer",
        "list_projects",
        "list_customers",
        "get_calendar_events",
    }),
}


def apply_web_desktop_tool_schema_copy(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    桌面 web：create_reminder_task 仅展示 local，避免误选非本机渠道。
    """
    out: list[dict[str, Any]] = []
    for item in tools:
        if not isinstance(item, dict) or item.get("type") != "function":
            out.append(copy.deepcopy(item))
            continue
        fn = item.get("function")
        if not isinstance(fn, dict):
            out.append(copy.deepcopy(item))
            continue
        name = str(fn.get("name") or "")
        dup = copy.deepcopy(item)
        dfn = dup["function"]
        if name == "create_reminder_task" and isinstance(dfn, dict):
            params = dfn.get("parameters")
            if isinstance(params, dict):
                props = params.get("properties")
                if isinstance(props, dict) and isinstance(props.get("channel"), dict):
                    ch = props["channel"]
                    ch["enum"] = ["local"]
                    ch["description"] = "桌面版仅支持 local：写入本地提醒计划。"
            dfn["description"] = (
                "创建本地定时提醒计划（reminder_tasks），在「我的提醒」中查看。"
                " 与日历工具配合：主行程用日历工具，关键节点用 one_time，每日/工作日用 recurring。"
            )
        out.append(dup)
    return out


def build_tool_schemas_for_intent(
    intent: str | None,
    *,
    operator_source: str = "web",
) -> list[dict[str, Any]]:
    """
    按动作意图返回较小的 tools 列表，减轻小模型负担。
    operator_source 非 web 时返回完整工具集（含会话等扩展渠道）。
    """
    full = build_tool_schemas()
    if operator_source != "web":
        return full
    if not intent or intent not in _INTENT_TOOL_NAMES:
        return apply_web_desktop_tool_schema_copy(full)
    allow = _INTENT_TOOL_NAMES[intent]
    filtered: list[dict[str, Any]] = []
    for item in full:
        if not isinstance(item, dict) or item.get("type") != "function":
            continue
        fn = item.get("function")
        if not isinstance(fn, dict):
            continue
        if fn.get("name") in allow:
            filtered.append(copy.deepcopy(item))
    return apply_web_desktop_tool_schema_copy(filtered)
