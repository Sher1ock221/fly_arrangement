# 飞书接入生产检查清单

本文用于飞书 webhook 接入的试运行/上线前检查，按“配置 -> 联调 -> 观测 -> 风险”执行。

## 1. 飞书后台配置检查

- 应用类型：确认是企业自建应用，不是个人测试应用。
- 机器人能力：已启用机器人，且允许接收私聊与群聊消息。
- 事件订阅：已开启事件订阅，并订阅消息事件（message receive）。
- 回调地址：`https://<你的公网域名>/api/v1/ai/feishu-webhook`。
- 回调验证：URL 验证 challenge 成功。
- 群聊能力：机器人已在群内，且允许被 @ 触发。
- 权限项建议：最小够用原则，优先申请消息接收与消息发送相关权限。

## 2. 环境变量检查

后端 `.env` 至少要有：

- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`
- `FEISHU_VERIFICATION_TOKEN`
- `FEISHU_ENCRYPT_KEY`（可选）
- `FEISHU_ENABLE_SIGNATURE_CHECK`
- `PUBLIC_API_BASE_URL`
- `FEISHU_ENABLE_WHITELIST`
- `FEISHU_WHITELIST_OPEN_IDS`

建议：

- 试运行环境将 `FEISHU_ENABLE_SIGNATURE_CHECK=true`。
- 若灰度发布，先开白名单：`FEISHU_ENABLE_WHITELIST=true` 并填写少量 `open_id`。
- `PUBLIC_API_BASE_URL` 必须是飞书可访问的 HTTPS 地址（用于撤销链接）。

## 3. 回调验证检查

- challenge：飞书后台校验通过。
- 私聊文本：机器人可回复文本 + 回执卡片。
- 群聊不 @：消息应被 ignored，不回消息。
- 群聊 @：触发 AI 与工具执行，返回结果。
- 非文本消息：返回“当前仅支持文本消息”提示。
- 撤销按钮：可打开 `/api/v1/ai/feishu-undo` 并执行成功。

## 4. 数据与日志检查

联调后检查数据库：

- `feishu_users`：用户是否落库、`last_seen_at` 是否更新。
- `feishu_conversations`：是否创建会话映射。
- `feishu_message_events`：状态是否有 `success/failed/ignored/processing`。
- `chat_records`：是否写入 `channel=feishu` 与 `external_*` 字段。
- `audit_logs`：是否写入 `operator_source=feishu`。
- `feishu_tokens`：是否缓存 `tenant_access_token`。

联调后检查日志：

- `system_logs` 中是否有 `feishu.webhook`、`feishu.bot`、`feishu.token`、`feishu.undo` 模块记录。
- 错误日志是否带 message_id / open_id / chat_id 等关键字段。

## 5. 运行监控建议

建议至少看以下指标（按 24h 维度）：

- `failed` 事件数量与占比（阈值建议：失败率 > 5% 告警）。
- `ignored` 占比（突然升高可能是群聊 @ 解析异常或白名单误开）。
- token 状态（是否长期不存在或频繁刷新失败）。
- webhook 处理耗时（`duration_ms`，关注长尾请求）。
- 重复消息比率（相同 `event_id/message_id` 重复到达比例）。

## 6. 风险与建议

- cpolar 风险：免费/临时隧道可能抖动，建议生产使用稳定 HTTPS 域名。
- 同步处理风险：大模型慢响应会放大 webhook 时延，建议后续切异步队列（Celery/RQ）。
- 白名单策略：试运行阶段建议开启白名单，稳定后再全量开放。
- 安全策略：保持验签开启，避免关闭 `FEISHU_ENABLE_SIGNATURE_CHECK`。
- 回滚策略：保留数据库快照与 Alembic 回滚路径，发布前先演练一次。

## 7. 发布后首日巡检

- 每 30 分钟检查一次 `feishu-status` 面板。
- 对最近失败事件逐条抽样，确认是否为业务错误还是配置错误。
- 抽查 3 条私聊与 3 条群聊 @ 流程，确保会话映射与回执一致。
