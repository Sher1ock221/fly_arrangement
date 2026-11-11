# Calendar Skill

适用意图：

- 新增日程、创建日程、安排日程  
- 明天、后天、下周等相对时间  
- 会议、开会、参加会议（含「新建一个明天的会议」「会议内容是…」）  
- 行程、日历、约会、议程、培训、考试等  

## 语义区分（重要）

- 「会议内容是商讨项目架构」中的「项目」指 **会议主题 / 议程**，**不要**调用 `list_all_projects`、`list_projects`、`add_resource_activity`、`create_project` 等 **项目域** 工具。  
- 会议主题 / 正文应写入日历的 **`title` / `description`**，或交给 **`auto_schedule_event`** 的 `text` 原文。  

## 意图优先级（相对 project）

- 当用户 **明确在安排会议 / 日程 / 开会**（含「新建…会议」「明天下午三点开会」等）时，**优先按 calendar 意图** 处理，即使句中出现「项目」「架构」等词。  
- **`add_resource_activity`** 属于 **项目资源动态**；在 **calendar 意图下禁止调用**。

## 工具规则

- **首选** `auto_schedule_event`（时间不完整时由后端解析与避让）。  
- 当用户 **明确给出** `start_time` / `end_time`（ISO）时，可用 `create_calendar_event`。  
- 用户未给具体时间时，**不要卡住**，优先 `auto_schedule_event`。  
- 需要查已有安排时用 `get_calendar_events`。  

## 最小示例

- 用户：新增一个明天的日程，我要去广数厅参加会议  
- 应调用：`auto_schedule_event`  
- 参数建议：`text`=用户原文，`title`=去广数厅参加会议，`event_type`=`meeting`  

严禁只回复「好的，我帮你安排」而不返回 **tool_calls**。
