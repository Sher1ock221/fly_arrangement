# Collaboration Skill

适用意图（当 **tools 中包含协作类工具** 且产品允许执行时）：

- 共享、添加协作者、移除协作者  
- 转移负责人、确认或取消转移  

## 桌面纯净版说明

- **桌面 Web（纯净版）当前会拦截协作类意图**，不进入本 Skill 对应的工具规划路径；用户将收到本地能力说明。  
- **不要**让模型尝试通过 **外部协作通道** 发送消息、拉群或完成跨租户通知。  
- 若未来在非桌面环境且 tools 可用，再按下列工具链执行。

## 工具规则（非拦截环境）

- 添加/移除协作者：`resolve_user` → `resolve_project` / `resolve_customer` → `manage_collaborator`  
- 转移负责人：`resolve_user` → `transfer_owner`；用户确认类回复用 `confirm_or_cancel_transfer`  
- 权限不足时须清楚说明原因（结合工具返回的 `execution_summary`）。
