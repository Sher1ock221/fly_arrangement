# Diagnostics Skill（诊断与错误回复）

指导模型在 **异常、超时、部分结果** 场景下如何向用户解释；结构化字段以 API 返回为准。

## 上游 / 连接类

1. **`connection_refused`**  
   - 含义：无法连接到 Ollama。  
   - 回复要点：请用户确认 **Ollama 已启动**、**地址与端口**与「AI 配置」一致，本机防火墙允许访问。

2. **`timeout`（状态）**  
   - 含义：Ollama **响应超时**（读超时或规划过慢）。  
   - 回复要点：可能在 **加载模型** 或 **机器资源不足**；可稍后重试、换小模型或拆分指令。

3. **`model_not_found`**  
   - 含义：配置的 **模型名不存在** 于当前 Ollama。  
   - 回复要点：提示当前 `model_name`，建议用户在「AI 配置」中改为 `ollama list` 中存在的标签。

4. **`http_error`**  
   - 含义：Ollama 返回非 2xx HTTP。  
   - 回复要点：可提及 **base_url**、**model_name** 与 HTTP 状态（若系统消息中已提供）；不要编造细节。

## `timeout_stage`（阶段）

可能取值包括但不限于：

- `config`：加载配置阶段异常/超时（若使用）。  
- `intent`：意图阶段（若使用）。  
- `ollama_first_call`：首轮模型调用（含工具规划）。  
- `tool_execution`：工具执行阶段异常/超时（若使用）。  
- `ollama_summary`：基于工具结果生成总结阶段。  
- `unknown`：未分类或其它。

**说明**：若 **工具已执行** 但 **`ollama_summary` 超时**，应优先列出 **已完成的工具步骤**（来自 `execution_results` / `partial_results`），**不要**只说「失败」而隐瞒已落库部分。

## `partial_results`

1. 当响应携带 **`partial_results`** 时，必须同时说明 **已完成** 与 **未完成** 的步骤。  
2. 不得将部分失败 **包装为** 全部成功。

## `diagnostic` 对象

1. `diagnostic`（及 `loaded_skills`、`prompt_chars`、`phase_elapsed_ms` 等）用于 **排查性能与路径**，**不等同于**业务成功。  
2. **前端 loading 结束** 只表示请求返回，**不代表**业务成功；必须以 **`execution_results`** 中各工具的 `success` 为准。  
3. **不要把超时或未返回工具结果** 的情况描述成「已创建日程/项目」等成功断言。

## Shortcut 诊断

若 `diagnostic.shortcut` 或顶层 `shortcut` 字段有值（如 `compound_schedule`、`compound_project_customer_communication`），说明走了 **确定性快捷路径**，与常规 tools 规划不同；回复可与模板总结一致，但仍须与 `execution_results` 对齐。
