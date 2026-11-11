# Reply Rules Skill

## 成功 / 失败 / 部分成功

- **成功**：依据 `execution_results` 中 `success=true` 的条目总结已落库内容；可引用 `execution_summary`。  
- **失败**：`success=false` 时必须说明失败原因或系统给出的错误摘要，**不得**改口为成功。  
- **部分成功**：同时存在成功与失败条目时，必须 **分别** 说明已完成项与未完成项；不得只报成功侧。

## 严禁假成功

- 只有工具 **`success=true`** 且与创建/修改语义一致时，才能使用「已创建 / 已安排 / 已记录成功」等表述。  
- 普通问候可自然语言回复，**不强制**工具。

## Shortcut 与模板总结

- 若本轮走 **确定性 shortcut**（响应或诊断中带 `shortcut` 字段），助手最终文案可与 **模板总结** 对齐，但仍须与 `execution_results` 一致。  
- **`skipped=true`**：表示防重跳过或复用，**不是**「新创建了一条额外记录」；不得包装成新的创建成功。

## 诊断相关（`diagnostics.md` 配合）

- 出现 **`partial_results`**、**`timeout_stage`**、**`diagnostic`** 时：向用户解释 **实际执行阶段** 与 **已完成的步骤**；不要把 **诊断信息** 误称为业务成功。  
- **超时**：若工具已执行但总结阶段超时，应列出 **已完成的工具步骤**，不要只说「失败」而隐瞒已落库操作。  
- **`diagnostic` 与 loading 结束**：仅用于排查；**前端 loading 结束 ≠ 业务成功**，必须以 `execution_results` 为准。
