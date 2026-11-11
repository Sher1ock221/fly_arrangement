"""
高置信度「新建项目 + 客户 + 沟通记录」复合指令的快速路径。

命中时不走 Ollama 工具规划，直接 execute_tool_call 顺序落库，避免小模型在长 tools schema 下超时。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer import Customer
from app.models.project import Project
from app.services.tool_executor import execute_tool_call

logger = logging.getLogger(__name__)


@dataclass
class ParsedCompoundBiz:
    customer_name: str
    communication: str


def parse_compound_project_customer_communication(text: str) -> ParsedCompoundBiz | None:
    """
    解析「同时新建项目、客户并记录沟通」类句式；解析失败返回 None。
    """
    t = (text or "").strip()
    if not t:
        return None
    if not any(x in t for x in ("新建", "创建", "新增")):
        return None
    if "项目" not in t or "客户" not in t:
        return None

    name: str | None = None
    patterns = (
        r"名字叫做\s*([^\s，,。.；;]+?)\s*的客户",
        r"客户叫\s*([^\s，,。.；;]+)",
        r"叫\s*([^\s，,。.；;]+?)\s*的客户",
        r"客户名称(?:为|是)\s*([^\s，,。.；;]+)",
        r"新增客户\s*([^\s，,。.；;]+)",
        r"同时新增客户\s*([^\s，,。.；;]+)",
    )
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            name = m.group(1).strip()
            break
    if not name or len(name) > 64:
        return None

    comm: str | None = None
    comm_patterns = (
        (r"和(?:这个)?客户聊了一下\s*(.+?)(?:$|[。.；;])", 1),
        (r"聊了一下\s*(.+?)(?:$|[。.；;])", 1),
        (r"沟通(?:了)?\s*(.+?)(?:$|[。.；;])", 1),
        (r"交流(?:了)?\s*(.+?)(?:$|[。.；;])", 1),
        (r"讨论(?:了)?\s*(.+?)(?:$|[。.；;])", 1),
        (r"记录(?:了)?\s*(.+?)(?:$|[。.；;])", 1),
        (r"说了\s*(.+?)(?:$|[。.；;])", 1),
        (r"记录沟通内容[：:]\s*(.+?)(?:$|[。.；;])", 1),
        (r"沟通内容(?:为|是)[：:\s]*(.+?)(?:$|[。.；;])", 1),
    )
    for pat, g in comm_patterns:
        m = re.search(pat, t, flags=re.DOTALL)
        if m:
            comm = m.group(g).strip()
            break
    if not comm or len(comm) < 2:
        return None
    comm = comm.strip()[:2000]
    return ParsedCompoundBiz(customer_name=name, communication=comm)


async def _get_customer_by_name_owner(
    db: AsyncSession, name: str, owner_user_id: int
) -> Customer | None:
    r = await db.execute(
        select(Customer).where(
            Customer.name == name,
            Customer.owner_user_id == owner_user_id,
        ).limit(1)
    )
    return r.scalar_one_or_none()


async def _get_project_by_name_owner(
    db: AsyncSession, name: str, owner_user_id: int
) -> Project | None:
    r = await db.execute(
        select(Project).where(
            Project.name == name,
            Project.owner_user_id == owner_user_id,
        ).limit(1)
    )
    return r.scalar_one_or_none()


def _default_project_name(customer_name: str, comm: str) -> str:
    short = (comm[:24] + "…") if len(comm) > 24 else comm
    return f"{customer_name}客户{short}沟通项目"


async def try_compound_business_shortcut(
    db: AsyncSession,
    user_text: str,
    operator_user_id: int | None,
    *,
    operator_source: str = "web",
) -> dict[str, Any] | None:
    """
    命中高置信度「项目+客户+沟通」时返回与 chat_and_execute_tools 兼容的字典；否则 None。
    """
    if operator_user_id is None:
        return None
    if (operator_source or "").strip() != "web":
        return None

    parsed = parse_compound_project_customer_communication(user_text)
    if parsed is None:
        return None

    logger.info(
        "event=ai_shortcut_matched shortcut=compound_project_customer_communication customer=%r",
        parsed.customer_name,
    )

    execution_results: list[dict[str, Any]] = []
    errors: list[str] = []

    # 1) 客户
    existing_c = await _get_customer_by_name_owner(db, parsed.customer_name, operator_user_id)
    if existing_c:
        cust_res = {
            "success": True,
            "tool_name": "create_customer",
            "skipped": True,
            "execution_summary": f"已存在同名客户「{parsed.customer_name}」，已复用。",
            "result": {"id": existing_c.id, "name": existing_c.name},
        }
        customer_id = existing_c.id
        execution_results.append(cust_res)
    else:
        cust_res = await execute_tool_call(
            db,
            "create_customer",
            {"name": parsed.customer_name},
            operator_source=operator_source,
            operator_external_id=None,
            operator_user_id=operator_user_id,
        )
        cust_res = {**cust_res, "tool_name": "create_customer"}
        execution_results.append(cust_res)
        if not cust_res.get("success"):
            errors.append(cust_res.get("execution_summary") or cust_res.get("error") or "创建客户失败")
            return _compound_failure_result(execution_results, errors, parsed)
        rid = cust_res.get("result")
        customer_id = int(rid["id"]) if isinstance(rid, dict) and rid.get("id") is not None else None
        if customer_id is None:
            errors.append("创建客户后无法读取客户 ID")
            return _compound_failure_result(execution_results, errors, parsed)

    # 2) 项目
    pname = _default_project_name(parsed.customer_name, parsed.communication)
    existing_p = await _get_project_by_name_owner(db, pname, operator_user_id)
    if existing_p:
        proj_res = {
            "success": True,
            "tool_name": "create_project",
            "skipped": True,
            "execution_summary": f"已存在同名项目「{pname}」，已复用。",
            "result": {"project_id": existing_p.id, "name": existing_p.name},
        }
        execution_results.append(proj_res)
    else:
        proj_res = await execute_tool_call(
            db,
            "create_project",
            {
                "name": pname,
                "project_name": pname,
                "customer_ids": [customer_id],
            },
            operator_source=operator_source,
            operator_external_id=None,
            operator_user_id=operator_user_id,
        )
        proj_res = {**proj_res, "tool_name": "create_project"}
        execution_results.append(proj_res)
        if not proj_res.get("success"):
            errors.append(proj_res.get("execution_summary") or proj_res.get("error") or "创建项目失败")
            return _compound_failure_result(execution_results, errors, parsed)

    # 3) 沟通记录
    inter_res = await execute_tool_call(
        db,
        "create_customer_interaction",
        {
            "customer_id": customer_id,
            "talk_summary": parsed.communication,
            "raw_input": user_text,
        },
        operator_source=operator_source,
        operator_external_id=None,
        operator_user_id=operator_user_id,
    )
    inter_res = {**inter_res, "tool_name": "create_customer_interaction"}
    execution_results.append(inter_res)
    if not inter_res.get("success"):
        errors.append(inter_res.get("execution_summary") or inter_res.get("error") or "记录沟通失败")
        return _compound_failure_result(execution_results, errors, parsed)

    summary = (
        f"已为你处理：客户「{parsed.customer_name}」已创建或已存在并复用；"
        f"项目「{pname}」已创建或已存在并复用；"
        f"已记录沟通：{parsed.communication}"
    )
    logger.info("event=ai_chat_finished shortcut=compound_project_customer_communication success=1")
    return {
        "success": True,
        "shortcut": "compound_project_customer_communication",
        "message": {"role": "assistant", "content": summary},
        "execution_results": execution_results,
        "detected_intent": "compound_project_customer",
        "use_tools": False,
        "template_summary": True,
    }


def _compound_failure_result(
    execution_results: list[dict[str, Any]],
    errors: list[str],
    parsed: ParsedCompoundBiz,
) -> dict[str, Any]:
    msg = "；".join(errors) if errors else "复合指令处理未完成。"
    logger.warning(
        "event=ai_chat_failed shortcut=compound_project_customer_communication success=0 errors=%r",
        errors,
    )
    return {
        "success": False,
        "shortcut": "compound_project_customer_communication",
        "message": {"role": "assistant", "content": f"已尝试快速处理，但未全部完成：{msg}"},
        "execution_results": execution_results,
        "detected_intent": "compound_project_customer",
        "use_tools": True,
        "partial_results": execution_results,
        "error_status": "compound_business_partial",
    }


# ---------- 仅「客户 + 沟通记录」shortcut（非项目+客户+沟通复合）----------

_COMM_ACTION_MARKERS = (
    "记录",
    "沟通",
    "聊",
    "聊了",
    "交流",
    "跟进",
    "拜访",
    "电话",
    "说了",
    "讨论",
)

_NAME_BAD = frozenset(
    {
        "今天",
        "这个",
        "那位",
        "一下",
        "记录",
        "客户",
        "沟通",
        "事情",
        "情况",
        "内容",
    }
)


def _is_compound_project_customer_shape(text: str) -> bool:
    """与复合业务 shortcut 同形：必须让 compound 优先，避免本 shortcut 抢占。"""
    t = (text or "").strip()
    if not t:
        return False
    if parse_compound_project_customer_communication(t) is not None:
        return True
    if "客户" in t and "项目" in t and any(x in t for x in ("新建", "创建", "新增")):
        return True
    return False


def user_text_suggests_customer_communication_record(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return any(m in t for m in _COMM_ACTION_MARKERS)


def parse_customer_name_for_interaction_record(text: str) -> str | None:
    """从「和H客户」「客户H」等句式提取客户简称；失败返回 None。"""
    t = (text or "").strip()
    if not t:
        return None
    patterns = (
        r"和\s*([A-Za-z0-9\u4e00-\u9fff]{1,32})\s*客户",
        r"跟\s*([A-Za-z0-9\u4e00-\u9fff]{1,32})\s*客户",
        r"与\s*([A-Za-z0-9\u4e00-\u9fff]{1,32})\s*客户",
        r"对\s*([A-Za-z0-9\u4e00-\u9fff]{1,32})\s*客户",
        r"客户叫\s*([^\s，,。.；;]{1,32})",
        r"名字叫\s*([^\s，,。.；;]{1,32}?)\s*的客户",
        r"客户\s*([A-Za-z0-9\u4e00-\u9fff]{1,32})(?=\s*沟通)",
        r"客户\s*([A-Za-z0-9\u4e00-\u9fff]{1,32})(?=\s*聊)",
        r"客户\s*([A-Za-z0-9\u4e00-\u9fff]{1,32})(?=\s*交流)",
        r"记录(?:一下)?\s*([A-Za-z0-9\u4e00-\u9fff]{1,32})\s*客户",
        r"([A-Za-z0-9\u4e00-\u9fff]{1,32})客户(?=\s*沟通)",
        r"([A-Za-z0-9\u4e00-\u9fff]{1,32})客户(?=\s*[,，])",
        r"客户\s*([A-Za-z0-9\u4e00-\u9fff]{1,32})(?=[,，。.])",
    )
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            name = (m.group(1) or "").strip()
            if 1 <= len(name) <= 64 and name not in _NAME_BAD:
                return name
    return None


_TALK_GENERIC_TAIL_RE = re.compile(
    r"(?:的事情|的事项|这个事情|相关内容|等情况)$",
)

_JUNK_TALK_ONLY = frozenset({"事情", "情况", "内容", "相关", "这个", "事项"})


def _finalize_talk_summary_fragment(raw: str) -> str:
    """去掉句尾泛化尾巴；不截断业务词（部署/方案/需求等保留在主体中）。"""
    s = (raw or "").strip()
    s = re.sub(r"\s+", " ", s)
    for _ in range(4):
        ns = _TALK_GENERIC_TAIL_RE.sub("", s).strip()
        if ns == s or len(ns) < 2:
            break
        s = ns
    return s.strip()


def _is_meaningful_talk_summary(s: str) -> bool:
    if not s or len(s) < 2:
        return False
    return s not in _JUNK_TALK_ONLY


def parse_talk_summary_for_interaction_record(text: str) -> str | None:
    """提取沟通摘要；失败返回 None。优先显式分隔，其次动作词后片段；避免非贪婪在句中「事情」处误截断。"""
    t = (text or "").strip()
    if not t:
        return None

    # 1) 显式「沟通内容 / 跟进内容 / 记录内容」
    explicit = (
        r"沟通内容是\s*(.+?)(?:$|[。\n;；!！?？])",
        r"沟通内容[：:]\s*(.+?)(?:$|[。\n;；!！?？])",
        r"沟通内容(?:为|是)\s*[：:]?\s*(.+?)(?:$|[。\n;；!！?？])",
        r"跟进内容是\s*(.+?)(?:$|[。\n;；!！?？])",
        r"跟进内容[：:]\s*(.+?)(?:$|[。\n;；!！?？])",
        r"记录内容是\s*(.+?)(?:$|[。\n;；!！?？])",
        r"记录内容[：:]\s*(.+?)(?:$|[。\n;；!！?？])",
    )
    for pat in explicit:
        m = re.search(pat, t, flags=re.DOTALL)
        if m:
            s = _finalize_talk_summary_fragment(m.group(1))
            if _is_meaningful_talk_summary(s):
                return s[:2000]

    # 2) 「…了」+ 以「的事情/的事项」收束（必须用锚定尾巴，禁止可选内嵌「事情」+ `$` 误匹配）
    anchored_thing = (
        r"沟通了\s*(.+)\s*的事情(?:\s*$|[。\n;；!！?？])",
        r"沟通了\s*(.+)\s*的事项(?:\s*$|[。\n;；!！?？])",
        r"聊了(?:一下)?\s*(.+)\s*的事情(?:\s*$|[。\n;；!！?？])",
        r"交流(?:了)?\s*(.+)\s*的事情(?:\s*$|[。\n;；!！?？])",
        r"跟进了\s*(.+)\s*的事情(?:\s*$|[。\n;；!！?？])",
        r"讨论了\s*(.+)\s*的事情(?:\s*$|[。\n;；!！?？])",
        r"说了\s*(.+)\s*的事情(?:\s*$|[。\n;；!！?？])",
    )
    for pat in anchored_thing:
        m = re.search(pat, t, flags=re.DOTALL)
        if m:
            s = _finalize_talk_summary_fragment(m.group(1))
            if _is_meaningful_talk_summary(s):
                return s[:2000]

    # 3) 无「的事情」收束：聊到逗号/句末/求助语前
    tail_delim = r"(?=，|,|帮我|请|。|$|[\n;；!！?？])"
    loose = (
        rf"聊了(?:一下)?\s*([^，,。\n;；]{{2,2000}}){tail_delim}",
        rf"沟通(?:了)?\s*([^。;\n;；]{{2,2000}})(?:$|[。\n;；!！?？])",
        rf"交流(?:了)?\s*([^。;\n;；]{{2,2000}})(?:$|[。\n;；!！?？])",
        rf"跟进了\s*([^。;\n;；]{{2,2000}})(?:$|[。\n;；!！?？])",
        rf"讨论了\s*([^。;\n;；]{{2,2000}})(?:$|[。\n;；!！?？])",
        rf"拜访(?:了)?\s*([^。;\n;；]{{2,2000}})(?:$|[。\n;；!！?？])",
        rf"说了\s*([^。;\n;；]{{2,2000}})(?:$|[。\n;；!！?？])",
    )
    for pat in loose:
        m = re.search(pat, t, flags=re.DOTALL)
        if m:
            s = _finalize_talk_summary_fragment(m.group(1))
            if _is_meaningful_talk_summary(s):
                return s[:2000]

    # 4) 冒号类兜底
    colon_tail = (
        r"跟进[：:]\s*(.+)$",
        r"记录[：:]\s*(.+)$",
    )
    for pat in colon_tail:
        m = re.search(pat, t, flags=re.DOTALL)
        if m:
            s = _finalize_talk_summary_fragment(m.group(1))
            if _is_meaningful_talk_summary(s):
                return s[:2000]

    return None


_SIMPLE_CREATE_VERBS = ("新增", "新建", "创建")
_SIMPLE_CREATE_COMM_MARKERS = (
    "沟通",
    "聊",
    "交流",
    "跟进",
    "记录",
    "拜访",
    "电话",
    "说了",
    "讨论",
)

_SIMPLE_CREATE_NAME_BAD = frozenset(
    _NAME_BAD
    | {
        "姓名",
        "名称",
        "叫做",
        "帮我",
        "一个",
        "资料",
        "信息",
    }
)


def simple_customer_create_text_matches(user_text: str) -> bool:
    t = (user_text or "").strip()
    if not t:
        return False
    if "项目" in t:
        return False
    if any(m in t for m in _SIMPLE_CREATE_COMM_MARKERS):
        return False
    # 「客户名称叫 X」无创建动词也应命中（与产品句式一致）
    if re.search(r"客户名称(?:叫|是)", t):
        return True
    if not any(v in t for v in _SIMPLE_CREATE_VERBS):
        return False
    if "客户" not in t:
        return False
    return True


def parse_simple_customer_create_name(text: str) -> str | None:
    """从纯「新增/创建客户」句式解析客户名；失败返回 None。"""
    t = (text or "").strip()
    if not t:
        return None
    patterns = (
        r"(?:新增|新建|创建)\s*(?:一个\s*)?客户\s*[，,]\s*名字(?:叫|是)\s*[：:]*\s*([^\s，,。.；;！!？?]{1,64})",
        r"(?:名字|姓名)(?:叫|是)\s*[：:]*\s*([^\s，,。.；;！!？?]{1,64})",
        r"名字是\s*[：:]*\s*([^\s，,。.；;！!？?]{1,64})",
        r"客户名称(?:叫|是)\s*[：:]*\s*([^\s，,。.；;！!？?]{1,64})",
        r"(?:帮我)?\s*(?:新增|新建|创建)\s*客户\s*[，,]?\s*名字是\s*[：:]*\s*([^\s，,。.；;！!？?]{1,64})",
        r"(?:新增|新建|创建)\s*(?:一个\s*)?客户[，,]?\s*(?:名字|名称)(?:叫|是)\s*[：:]*\s*([^\s，,。.；;！!？?]{1,64})",
        r"(?:新增|新建|创建)\s*(?:一个\s*)?客户\s*([A-Za-z0-9\u4e00-\u9fff]{1,64})(?=\s*$|[，,。.；;！!？?\s]|的)",
    )
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            name = (m.group(1) or "").strip()
            if 1 <= len(name) <= 64 and name not in _SIMPLE_CREATE_NAME_BAD:
                return name
    return None


async def try_simple_customer_create_shortcut(
    user_text: str,
    db: AsyncSession,
    operator_user_id: int | None,
    *,
    operator_source: str = "web",
) -> dict[str, Any] | None:
    """
    轻量「仅创建客户」确定性路径；不走 Ollama。
    须在 customer_interaction_record 之后调用，以免「记录沟通」被误判为只建客户。
    """
    if operator_user_id is None:
        return None
    if (operator_source or "").strip() != "web":
        return None
    t = (user_text or "").strip()
    if not simple_customer_create_text_matches(t):
        return None
    if _is_compound_project_customer_shape(t):
        return None
    cname = parse_simple_customer_create_name(t)
    if not cname:
        return None

    logger.info("event=ai_shortcut_matched shortcut=simple_customer_create customer=%r", cname)

    execution_results: list[dict[str, Any]] = []

    existing_c = await _get_customer_by_name_owner(db, cname, operator_user_id)
    if existing_c:
        execution_results.append(
            {
                "success": True,
                "tool_name": "create_customer",
                "skipped": True,
                "execution_summary": f"已存在同名客户「{cname}」，已复用。",
                "result": {"id": existing_c.id, "name": existing_c.name},
            }
        )
        summary = f"客户「{cname}」已存在（customer_id={existing_c.id}），已复用，无需重复创建。"
        logger.info("event=ai_chat_finished shortcut=simple_customer_create success=1 reused=1")
        return {
            "success": True,
            "shortcut": "simple_customer_create",
            "message": {"role": "assistant", "content": summary},
            "execution_results": execution_results,
            "detected_intent": "customer",
            "use_tools": True,
            "template_summary": True,
        }

    cust_res = await execute_tool_call(
        db,
        "create_customer",
        {"name": cname},
        operator_source=operator_source,
        operator_external_id=None,
        operator_user_id=operator_user_id,
    )
    cust_res = {**cust_res, "tool_name": "create_customer"}
    execution_results.append(cust_res)
    if not cust_res.get("success"):
        err = cust_res.get("execution_summary") or cust_res.get("error") or "创建客户失败"
        logger.warning("event=ai_chat_finished shortcut=simple_customer_create success=0")
        return {
            "success": False,
            "shortcut": "simple_customer_create",
            "message": {"role": "assistant", "content": f"未能创建客户：{err}"},
            "execution_results": execution_results,
            "detected_intent": "customer",
            "use_tools": True,
            "template_summary": False,
            "error_status": "simple_customer_create_failed",
        }

    summary = f"已创建客户「{cname}」（本地归档）。"
    logger.info("event=ai_chat_finished shortcut=simple_customer_create success=1")
    return {
        "success": True,
        "shortcut": "simple_customer_create",
        "message": {"role": "assistant", "content": summary},
        "execution_results": execution_results,
        "detected_intent": "customer",
        "use_tools": True,
        "template_summary": True,
    }


async def try_customer_interaction_shortcut(
    user_text: str,
    db: AsyncSession,
    operator_user_id: int | None,
    *,
    operator_source: str = "web",
) -> dict[str, Any] | None:
    """
    命中「记录/沟通 + 某客户」且非复合项目句式时，直接 resolve/create + create_customer_interaction。
    """
    if operator_user_id is None:
        return None
    if (operator_source or "").strip() != "web":
        return None
    t = (user_text or "").strip()
    if not t:
        return None
    if _is_compound_project_customer_shape(t):
        return None
    if not user_text_suggests_customer_communication_record(t):
        return None
    if re.search(r"(?:新增|新建|创建)\s*(?:一个\s*)?客户", t) and not any(
        x in t for x in ("沟通", "聊", "记录", "跟进", "拜访", "交流", "讨论", "电话", "说了")
    ):
        return None

    cname = parse_customer_name_for_interaction_record(t)
    if not cname:
        return None

    talk = parse_talk_summary_for_interaction_record(t)
    if not talk:
        logger.warning("event=ai_shortcut_failed shortcut=customer_interaction_record reason=no_talk_summary")
        return {
            "success": False,
            "shortcut": "customer_interaction_record",
            "message": {
                "role": "assistant",
                "content": "未能从话里解析出沟通摘要。请用「和某某客户沟通了……」或「沟通内容：……」再说一次。",
            },
            "execution_results": [],
            "detected_intent": "customer",
            "use_tools": False,
            "template_summary": False,
            "error_status": "customer_interaction_record_parse_failed",
        }

    logger.info(
        "event=ai_shortcut_matched shortcut=customer_interaction_record customer=%r talk_len=%s",
        cname,
        len(talk),
    )

    execution_results: list[dict[str, Any]] = []

    existing_c = await _get_customer_by_name_owner(db, cname, operator_user_id)
    res_res = await execute_tool_call(
        db,
        "resolve_customer",
        {"query": cname},
        operator_source=operator_source,
        operator_external_id=None,
        operator_user_id=operator_user_id,
    )
    res_res = {**res_res, "tool_name": "resolve_customer"}
    execution_results.append(res_res)

    customer_id: int | None
    if existing_c is not None:
        customer_id = int(existing_c.id)
    elif res_res.get("success"):
        cid_raw = res_res.get("customer_id")
        if cid_raw is None and isinstance(res_res.get("result"), dict):
            cid_raw = res_res["result"].get("customer_id")
        customer_id = int(cid_raw) if cid_raw is not None else None
        if customer_id is None:
            return {
                "success": False,
                "shortcut": "customer_interaction_record",
                "message": {"role": "assistant", "content": "解析客户失败，请稍后重试。"},
                "execution_results": execution_results,
                "detected_intent": "customer",
                "use_tools": True,
                "error_status": "customer_interaction_record_failed",
            }
    else:
        cust_res = await execute_tool_call(
            db,
            "create_customer",
            {"name": cname},
            operator_source=operator_source,
            operator_external_id=None,
            operator_user_id=operator_user_id,
        )
        cust_res = {**cust_res, "tool_name": "create_customer"}
        execution_results.append(cust_res)
        if not cust_res.get("success"):
            err = cust_res.get("execution_summary") or cust_res.get("error") or "创建客户失败"
            return {
                "success": False,
                "shortcut": "customer_interaction_record",
                "message": {"role": "assistant", "content": f"未能完成客户步骤：{err}"},
                "execution_results": execution_results,
                "detected_intent": "customer",
                "use_tools": True,
                "error_status": "customer_interaction_record_failed",
            }
        rid = cust_res.get("result")
        customer_id = int(rid["id"]) if isinstance(rid, dict) and rid.get("id") is not None else None
        if customer_id is None:
            return {
                "success": False,
                "shortcut": "customer_interaction_record",
                "message": {"role": "assistant", "content": "创建客户后无法读取客户 ID。"},
                "execution_results": execution_results,
                "detected_intent": "customer",
                "use_tools": True,
                "error_status": "customer_interaction_record_failed",
            }

    inter_res = await execute_tool_call(
        db,
        "create_customer_interaction",
        {
            "customer_id": customer_id,
            "talk_summary": talk,
            "raw_input": user_text,
        },
        operator_source=operator_source,
        operator_external_id=None,
        operator_user_id=operator_user_id,
    )
    inter_res = {**inter_res, "tool_name": "create_customer_interaction"}
    execution_results.append(inter_res)
    if not inter_res.get("success"):
        err = inter_res.get("execution_summary") or inter_res.get("error") or "写入沟通记录失败"
        return {
            "success": False,
            "shortcut": "customer_interaction_record",
            "message": {"role": "assistant", "content": f"未能写入沟通记录：{err}"},
            "execution_results": execution_results,
            "detected_intent": "customer",
            "use_tools": True,
            "error_status": "customer_interaction_record_failed",
        }

    summary = (
        f"已为客户「{cname}」记录沟通：{talk}"
        f"（customer_id={customer_id}，本地归档）。"
    )
    logger.info("event=ai_chat_finished shortcut=customer_interaction_record success=1 customer_id=%s", customer_id)
    return {
        "success": True,
        "shortcut": "customer_interaction_record",
        "message": {"role": "assistant", "content": summary},
        "execution_results": execution_results,
        "detected_intent": "customer",
        "use_tools": True,
        "template_summary": True,
    }
