from __future__ import annotations

import json
from typing import Any


def _normalize_dedupe_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return [_normalize_dedupe_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _normalize_dedupe_value(v) for k, v in value.items()}
    return value


def build_tool_dedupe_key(tool_name: str, arguments: dict[str, Any]) -> str | None:
    create_tools = {
        "create_project",
        "upsert_project",
        "create_calendar_event",
        "auto_schedule_event",
        "create_customer",
        "create_reminder_task",
        "create_customer_interaction",
        "execute_candidate_schedule_strategy",
        "execute_compound_schedule",
    }
    if tool_name not in create_tools:
        return None

    pick_fields: dict[str, Any]
    if tool_name in ("create_project", "upsert_project"):
        pick_fields = {
            "name": arguments.get("name") or arguments.get("project_name"),
            "deadline": arguments.get("deadline"),
            "owner": arguments.get("owner"),
            "goal": arguments.get("goal"),
            "requirements": arguments.get("requirements"),
        }
    elif tool_name == "auto_schedule_event":
        pick_fields = {
            "title": arguments.get("title"),
            "text": arguments.get("text"),
            "event_type": arguments.get("event_type"),
        }
    elif tool_name == "create_calendar_event":
        pick_fields = {
            "title": arguments.get("title"),
            "start_time": arguments.get("start_time"),
            "end_time": arguments.get("end_time"),
        }
    elif tool_name == "create_customer":
        pick_fields = {
            "name": arguments.get("name"),
            "company": arguments.get("company"),
            "contact": arguments.get("contact"),
        }
    elif tool_name == "create_reminder_task":
        pick_fields = {
            "title": arguments.get("title"),
            "reminder_type": arguments.get("reminder_type"),
            "trigger_at": arguments.get("trigger_at"),
            "schedule_rule": arguments.get("schedule_rule"),
            "related_event_id": arguments.get("related_event_id"),
        }
    elif tool_name == "create_customer_interaction":
        pick_fields = {
            "customer_id": arguments.get("customer_id"),
            "customer_name": arguments.get("customer_name"),
            "meeting_time": arguments.get("meeting_time"),
            "talk_summary": arguments.get("talk_summary"),
            "raw_input": arguments.get("raw_input"),
        }
    elif tool_name == "execute_candidate_schedule_strategy":
        pick_fields = {
            "title": arguments.get("title"),
            "candidate_dates": arguments.get("candidate_dates"),
            "time_point": arguments.get("time_point"),
            "strategy": arguments.get("strategy"),
        }
    elif tool_name == "execute_compound_schedule":
        pick_fields = {
            "text": arguments.get("text"),
            "project_id": arguments.get("project_id"),
        }
    else:
        return None

    normalized = _normalize_dedupe_value(pick_fields)
    payload = {"tool_name": tool_name, "fields": normalized}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
