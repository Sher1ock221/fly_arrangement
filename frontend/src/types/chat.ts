/**
 * 聊天消息类型
 */

import type { AiChatDiagnostic, ExecutionResult } from "@/types/ai";

/** 创建/发送消息时的 payload（仅 role + content） */
export interface ChatMessageCreate {
  role: "user" | "assistant";
  content: string;
}

/** 聊天消息实体（UI 状态、存储） */
export interface ChatMessage {
  id: number;
  conversationId: number;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
  /** 助手消息可选：工具执行结果，用于展示步骤与「查看客户详情」等 */
  execution_results?: ExecutionResult[];
  /** 可选：本轮 AI 请求的诊断耗时（来自 /api/v1/ai/chat 的 diagnostic） */
  ai_debug?: AiChatDiagnostic;
}
