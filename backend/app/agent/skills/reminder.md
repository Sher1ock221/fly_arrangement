# Reminder Skill

适用意图：

- 提醒我、设置提醒、定时提醒、重复提醒、每日提醒  

## 工具规则

- 使用 `create_reminder_task`  
- 单次提醒：`reminder_type=one_time`  
- 重复提醒：`reminder_type=recurring`（按 `schedule_rule`）  

## 桌面本地提醒

- **网页 / 桌面 Web 聊天路径**下，**仅** `channel=local`：写入本地 **`reminder_tasks`**，在应用「我的提醒」中查看与触发。  
- 这是 **本地记账式 / 本地调度** 的提醒计划，**不依赖**外部 IM 推送。  

## 约束

- **`success=false`** 或未调用成功时，不得声称「提醒已创建成功」。  
- **不要**引导用户绑定外部平台身份；桌面版不使用外部私聊渠道创建提醒。
