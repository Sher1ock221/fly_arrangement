/**
 * 会话类型
 */

/** 会话实体 */
export interface Conversation {
  id: number;
  title: string;
  /** 来源：web | feishu_private | feishu_group（前端仅展示 web / feishu_private） */
  source?: string;
  projectId?: number;
  createdAt: string;
  updatedAt: string;
}

/** 创建会话时的 payload（新建对话通常只用默认标题，其余由后端/前端生成） */
export interface ConversationCreate {
  title?: string;
}
