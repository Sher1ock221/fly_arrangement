from __future__ import annotations

import re


def detect_action_intent(user_text: str) -> str | None:
    """
    轻量动作意图识别，用于 Web/桌面端工具路由与兜底重试。
    返回：calendar / project / customer / reminder / collaboration / None

    优先级（与业务一致）：
    1. 明确的项目创建/修改/删除/查询
    2. 明确的客户意图
    3. 提醒
    4. 会议/日程（含「会议内容…商讨项目架构」等，不因句中出现「项目」二字误判为项目工具）
    5. 协作
    6. 其它含「项目」但无明确项目管理语义的 → 不当作 project
    """
    if not user_text or not isinstance(user_text, str):
        return None
    text = user_text.strip()
    if not text:
        return None

    # ---------- 1. 明确的项目管理 / 项目动态 ----------
    if re.search(r"(新建|创建)\s*一个?\s*项目", text) or re.search(r"(新建|创建)项目", text):
        return "project"
    if re.search(r"(修改|更新|删除)\s*项目", text):
        return "project"
    if re.search(r"列出\s*(了)?\s*(所有|全部)?\s*项目", text) or re.search(
        r"(所有|全部)\s*项目", text
    ):
        return "project"
    if re.search(r"(查询|查看).{0,8}项目", text) and re.search(
        r"(列表|清单|有哪些|多少|几个)", text
    ):
        return "project"
    if re.search(r"项目(负责人|截止日期|截止|状态|名称)", text):
        return "project"
    if re.search(r"(给|为|帮).{0,40}项目", text) and re.search(
        r"(进展|动态|记录|资源活动|添加|追加|一条)", text
    ):
        return "project"

    # ---------- 2. 客户 ----------
    customer_keywords = (
        "新建客户",
        "新增客户",
        "新增一个客户",
        "创建一个客户",
        "创建客户",
        "客户拜访",
        "拜访客户",
        "跟进客户",
        "客户记录",
        "合作意向",
        "客户沟通",
        "归档到客户",
        "create_customer",
    )
    if re.search(r"(新增|新建|创建)\s*(?:一个\s*)?客户", text):
        return "customer"
    if any(k in text for k in customer_keywords) or (
        "客户" in text and any(x in text for x in ("拜访", "跟进", "沟通", "见了面", "聊了"))
    ):
        return "customer"

    # ---------- 3. 提醒 ----------
    reminder_keywords = (
        "提醒我",
        "设置提醒",
        "定时提醒",
        "重复提醒",
        "每天提醒",
    )
    if any(k in text for k in reminder_keywords):
        return "reminder"

    # ---------- 4. 会议 / 日程（优先于弱「项目」词） ----------
    calendar_topic_markers = (
        "会议",
        "开会",
        "参加会议",
        "日程",
        "行程",
        "日历",
        "约会",
        "议程",
        "培训",
        "汇报",
        "考试",
    )
    calendar_action_markers = (
        "新建",
        "创建",
        "新增",
        "添加",
        "安排",
        "预约",
        "添加到日历",
        "新增日程",
        "创建日程",
        "安排会议",
    )
    time_markers = (
        "今天",
        "明天",
        "后天",
        "下周",
        "本周",
        "这周",
        "上午",
        "下午",
        "晚上",
        "几点",
        "点",
    )
    has_cal_topic = any(k in text for k in calendar_topic_markers)
    has_cal_action = any(k in text for k in calendar_action_markers)
    has_time = any(k in text for k in time_markers) or bool(re.search(r"\d{1,2}\s*:\s*\d{2}", text))
    if has_cal_topic and (has_cal_action or has_time or "会议内容" in text):
        return "calendar"
    if any(k in text for k in ("日程", "行程", "日历")) and (has_cal_action or has_time):
        return "calendar"

    # ---------- 5. 协作 ----------
    collaboration_keywords = (
        "添加协作者",
        "转移负责人",
        "共享",
        "授权",
        "协作",
        "确认转移",
        "取消转移",
    )
    if any(k in text for k in collaboration_keywords):
        return "collaboration"

    # ---------- 6. 其它「项目」相关弱匹配（不再用裸「项目」触发） ----------
    project_weak = ("截止", "负责人", "需求", "任务", "里程碑", "交付")
    if "项目" in text and any(k in text for k in project_weak):
        return "project"

    return None
