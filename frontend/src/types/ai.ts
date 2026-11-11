/**
 * AI 聊天与工具执行相关类型定义。
 */

/** 单条工具执行结果（后端可能返回 tool 或 tool_name） */
export interface ExecutionResult {
  tool?: string;
  tool_name?: string;
  success: boolean;
  execution_summary?: string;
  error?: string;
  /** 成功时：create_customer_interaction 返回 customer_id, customer_name, interaction_id, detail_url, message */
  result?: {
    id?: number;
    customer_id?: number;
    customer_name?: string;
    interaction_id?: number;
    detail_url?: string;
    message?: string;
    name?: string;
    project_id?: number;
    project_no?: string;
    /** 歧义时后端返回的候选客户列表 */
    candidates?: Array<{ name?: string; company?: string | null; position?: string | null }>;
    [k: string]: unknown;
  };
  /** 歧义时后端返回的候选客户（与 result.candidates 二选一） */
  candidates?: Array<{ name?: string; company?: string | null; position?: string | null }>;
}

export interface ExecutionResultItem extends ExecutionResult {
  tool_name: string;
  tool_call_id?: string;
  result?: { id?: number; name?: string; project_id?: number; project_no?: string; [k: string]: unknown };
}

/** /api/v1/ai/chat 成功时附带的诊断信息（与后端 diagnostic 一致） */
export type AiChatDiagnostic = {
  request_id?: string;
  model_name?: string;
  base_url?: string;
  user_text_length?: number;
  detected_intent?: string | null;
  use_tools?: boolean | null;
  tool_schema_count?: number;
  loaded_skills?: string[];
  prompt_chars?: number;
  phase_elapsed_ms?: Record<string, number>;
  timeout_stage?: string | null;
  error_status?: string | null;
  shortcut?: string | null;
  local_smalltalk_hit?: boolean;
  disable_thinking_applied?: boolean;
};

/** 聊天接口返回的 execution_results 为未知结构，需经 normalizeExecutionResults 后使用 */
export interface ChatApiResponse {
  content?: string;
  message?: { role?: string; content?: string; tool_calls?: unknown[] };
  execution_results?: unknown[];
  diagnostic?: AiChatDiagnostic;
}

export interface AiChatResponse {
  /** 兼容：部分后端直接返回 content */
  content?: string;
  message?: { role?: string; content?: string; tool_calls?: unknown[] };
  execution_results?: ExecutionResultItem[];
  diagnostic?: AiChatDiagnostic;
  request_id?: string;
  shortcut?: string;
  template_summary?: boolean;
  partial_results?: unknown[];
  error_status?: string;
}

/** AI 聊天窗口单条消息（含执行步骤等 UI 用字段） */
export interface AIMessage {
  id?: string;
  role: "user" | "assistant";
  content: string;
  execution_results?: ExecutionResult[];
  executionSummary?: string | string[];
  executionErrors?: string[];
  smartHints?: string[];
  isSummaryReply?: boolean;
  ai_debug?: AiChatDiagnostic;
}

export interface AIConfig {
  id: number;
  model_name: string;
  base_url: string;
  is_active: boolean;
}

export interface AIConfigSave {
  model_name: string;
  base_url: string;
  is_active?: boolean;
}

export interface FeishuEventItem {
  id: number;
  event_id?: string | null;
  message_id?: string | null;
  chat_id?: string | null;
  open_id?: string | null;
  event_type: string;
  message_type?: string | null;
  process_status: string;
  retry_count: number;
  created_at?: string | null;
  error_message?: string | null;
  duration_ms?: number | null;
  possible_config_issue?: boolean;
}

export interface FeishuErrorItem {
  id: number;
  timestamp?: string | null;
  module: string;
  message: string;
}

export interface FeishuStatusResponse {
  ok: boolean;
  error?: string;
  config_source?: "db" | "env" | "mixed" | string;
  basic_config: {
    app_id_configured: boolean;
    app_secret_configured: boolean;
    verification_token_configured: boolean;
    encrypt_key_configured: boolean;
    signature_check_enabled: boolean;
    whitelist_enabled: boolean;
    public_api_base_url?: string | null;
    webhook_path: string;
    undo_path: string;
  };
  capabilities: {
    challenge_supported: boolean;
    signature_check_enabled: boolean;
    group_at_supported: boolean;
    p2p_supported: boolean;
    undo_supported: boolean;
    async_mode: boolean;
  };
  token_status: {
    exists: boolean;
    expire_at?: string | null;
    is_expired?: boolean | null;
    remain_seconds?: number | null;
  };
  event_stats: {
    total: number;
    success: number;
    failed: number;
    ignored: number;
    processing: number;
    last_24h_total: number;
    last_24h_failed: number;
  };
  failed_events: FeishuEventItem[];
  recent_webhook_errors: FeishuErrorItem[];
  diagnostics?: {
    is_ready_for_webhook: boolean;
    is_ready_for_card_undo: boolean;
    missing_items: string[];
    warnings: string[];
  };
}

export interface FeishuConfigResponse {
  app_id?: string | null;
  app_secret_masked?: string | null;
  app_id_configured: boolean;
  app_secret_configured: boolean;
  verification_token_masked?: string | null;
  verification_token_configured: boolean;
  encrypt_key_masked?: string | null;
  encrypt_key_configured: boolean;
  signature_check?: boolean;
  enable_whitelist: boolean;
  whitelist_open_ids: string;
  enable_signature_check: boolean;
  bot_name: string;
  public_api_base_url?: string | null;
  public_api_base_url_configured?: boolean;
  source_summary?: "db" | "env" | "mixed" | string;
  config_source?: "db" | "env" | "mixed" | string;
  webhook_url?: string | null;
  undo_url?: string | null;
  whitelist_count?: number;
}

export interface FeishuConfigSavePayload {
  app_id?: string;
  app_secret?: string;
  verification_token?: string;
  encrypt_key?: string;
  signature_check?: boolean;
  enable_whitelist?: boolean;
  whitelist_open_ids?: string;
  enable_signature_check?: boolean;
  bot_name?: string;
  public_api_base_url?: string;
  keep_existing_app_secret?: boolean;
  keep_existing_verification_token?: boolean;
  keep_existing_encrypt_key?: boolean;
}

export interface FeishuSimulatePayload {
  chat_type: "p2p" | "group_at";
  open_id: string;
  chat_id?: string;
  text: string;
  is_at_bot?: boolean;
  message_id?: string;
  event_id?: string;
}

export interface FeishuSimulateResponse {
  success: boolean;
  process_status: string;
  ai_reply: string;
  execution_results: Array<Record<string, unknown>>;
  conversation_id?: number | null;
  feishu_event_record_id?: number | null;
  error?: string;
}

export type FeishuRecentEvent = FeishuEventItem;
export type FeishuRecentError = FeishuErrorItem;
