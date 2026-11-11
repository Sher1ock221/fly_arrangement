/**
 * 日志与审计类型
 */
export interface SystemLog {
  id: number;
  level: "INFO" | "ERROR" | string;
  module: string;
  message: string;
  stack_trace?: string | null;
  timestamp: string;
}

export interface ChatRecord {
  id: number;
  user_message: string;
  ai_response: string;
  tool_calls?: unknown;
  channel?: "web" | "feishu" | string;
  external_user_id?: string | null;
  external_chat_id?: string | null;
  source_conversation_id?: number | null;
  external_message_id?: string | null;
  timestamp: string;
}
