# Customer Skill

适用意图：

- 新建客户、创建客户  
- 修改客户资料  
- 拜访、沟通、跟进、客户记录、合作意向  

## 工具规则

- **仅新增/创建客户**（如「新增一个客户名字叫 X」「新建客户 X」、无沟通归档语义）：只调用 **`create_customer`**，不要调用 `create_customer_interaction`。  
- 新建客户：`create_customer`  
- 修改客户：先 `resolve_customer`，再 `update_customer`  
- **客户沟通归档**：`create_customer_interaction`（见面、聊天、电话沟通等）  

## 与复合业务（`compound_business.md`）对齐

- 当用户 **一句话** 同时要求「项目 + 客户 + 沟通」且符合高置信句式时，系统可能已由 **shortcut** 处理；若未命中 shortcut，则由你按工具分步完成。  
- 例：「帮我记录一下，今天和 **H客户** 沟通了 **AIweb应用部署** 的事情」→ **customer 意图**：识别或创建客户 H，再 **`create_customer_interaction`** 写入沟通摘要；**不要**误用 `add_resource_activity` 除非用户明确说是项目进展。

## 强制规则（沟通记录）

- 用户明确要求 **记录沟通 / 跟进 / 聊了 / 沟通了 / 交流了** 等归档语义时：**必须先** `resolve_customer` 或 `create_customer` **再必须** 调用 **`create_customer_interaction`** 写入 `talk_summary`（或等价字段）。  
- **禁止**在仅执行了 `create_customer`（或仅 resolve）且 **未** 调用 `create_customer_interaction` 时，回复「已记录沟通」「已归档」等成功表述。  
- 若信息不足以写 `talk_summary`，应追问用户补充摘要，而不是结束对话。

## 约束

- 客户无法 **唯一匹配** 时，要求用户确认，不得假写入。  
- **`success=false`** 时不得声称已记录沟通。  
- 不得假成功。
