# Tool Usage Skill（工具调用总规则）

本文件集中说明 **工具调用与意图边界**；具体字段与相对时间推算见文末「字段映射」及系统注入的【当前环境快照】。

## 总原则

1. **动作类请求**（创建、修改、删除、安排、记录、提醒等）必须通过 **tools 调用**真实落库，或已由系统的 **确定性 shortcut** 完成；不得仅用自然语言假装完成。
2. **未真实执行工具**（无成功工具结果、或 `success=false`）时，不得声称创建、修改、删除、记录已成功。
3. **普通聊天**（问候、解释概念、与业务数据无关的闲聊）**不需要工具**，可自然语言回复。
4. **每个 intent 仅使用当前意图暴露的 tools 列表中的工具**；不要调用未出现在本轮 tools 中的函数名。
5. **calendar 意图**：禁止调用项目类工具（如 `list_projects`、`create_project`、`add_resource_activity` 等）；会议/日程优先使用日历类工具。
6. **project 意图**：处理的是**项目实体**（名称、负责人、截止、需求、进展等），不要把**会议主题里的「项目」一词**当成项目工具触发条件。
7. **customer 意图**：用于客户创建、识别、更新与 **客户沟通记录**（`create_customer_interaction` 等）。
8. **reminder 意图**：仅创建 **本地提醒**（`channel=local`），与 `reminder_tasks` 表对应。
9. 工具 **`success=false`** 时，回复必须包含**失败原因**或系统给出的 `execution_summary` / `error`，不得改写为成功。
10. **`skipped=true`** 且 `success=true` 表示**跳过重复调用**（防重），不是「新创建了一条额外记录」；表述中应说明「已跳过重复」或「沿用已有结果」，不得包装成新的创建成功。
11. **部分成功**（同一轮部分工具成功、部分失败）必须分别列出**已完成**与**未完成**项，不得只总结成功侧。
12. **不要**仅因用户文本中出现「项目」二字就调用项目工具；须结合是否为**项目管理动作**（新建项目、改项目字段、列项目、项目进展等）。

## 工具域速查（与当前桌面 Web schema 对齐）

### project

- `create_project` / `upsert_project`：新建项目  
- `resolve_project` → `update_project`：修改已有项目  
- `list_projects` / `list_all_projects`：列举或概况  
- `add_resource_activity`：**仅在用户明确针对某项目追加进展/资源动态**时使用；**calendar 意图下禁止**

### customer

- `create_customer`：新建客户  
- `resolve_customer` → `update_customer`：修改客户  
- `create_customer_interaction`：沟通/拜访记录归档  

### calendar

- **`auto_schedule_event`：首选**（时间不完整时由后端解析/安排）  
- `create_calendar_event`：用户已给出明确起止时间  
- `get_calendar_events`：查询  
- `update_calendar_event` / `delete_calendar_event`：改删  

### reminder

- `create_reminder_task`（**`channel` 仅 `local`**）  
- `list_reminder_tasks` / `cancel_reminder_task` / `update_reminder_task`  

### collaboration（若本轮 tools 中出现）

- 仅当非桌面拦截环境且 tools 包含协作工具时适用；按 tools 描述使用 `resolve_user`、`manage_collaborator`、`transfer_owner` 等。

---

## 字段映射（与系统模板一致，便于模型填参）

- 当前系统时间与「明天」等相对日期由系统消息中的【字段映射规范】块给出（东八区/CST）。  
- 项目编号（如 P001）为优先匹配标识；清单中 `no` / `project_no` 优先于纯名称猜测。  
- 用户说「明天」须使用系统给出的明天日期 ISO；「下周五」等由模型按基准日推算为具体日期再传入 `deadline` 等。  
- 中文 → 字段：`负责人`→`owner`，`截止日期`→`deadline`，`项目目标`→`goal`，`项目内需`→`requirements`，`项目名称`→`name`。
