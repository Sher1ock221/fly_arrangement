import type { ChatMessageCreate } from "@/types/chat";
import type { AiChatResponse, AIConfig, AIConfigSave } from "@/types/ai";
import type { CalendarEvent, CalendarEventCreate, CalendarEventUpdate } from "@/types/calendar";
import type { Project, ProjectCreate, ProjectUpdate } from "@/types/project";
import type { Customer, CustomerCreate, CustomerUpdate, CustomerDetail, CustomerInteractionCreate, CustomerInteractionUpdate } from "@/types/customer";
import type { PaginatedResponse } from "@/types/common";
import type { SystemLog, ChatRecord } from "@/types/logs";
import type { Conversation } from "@/types/conversation";
import { getApiBase } from "@/lib/apiBase";

const AUTH_TOKEN_KEY = "fly_arrangement_access_token";

export class ApiRequestError extends Error {
  status: number;
  responseText: string;
  requestUrl?: string;
  constructor(message: string, status: number, responseText: string, requestUrl?: string) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.responseText = responseText;
    this.requestUrl = requestUrl;
  }
}

/** 解析 FastAPI 的 JSON 错误体中的 detail（字符串或 Ollama 结构化对象），供聊天等接口展示 */
export function formatApiErrorUserMessage(responseText: string): string {
  const raw = (responseText || "").trim();
  if (!raw) return "请求失败";
  try {
    const parsed = JSON.parse(raw) as {
      detail?:
        | string
        | {
            message?: string;
            status?: string;
            base_url?: string;
            model_name?: string;
            timeout_stage?: string;
            partial_results?: unknown;
          };
    };
    const d = parsed.detail;
    if (typeof d === "string") return d;
    if (d && typeof d === "object") {
      const status = d.status;
      if (status === "busy" && typeof d.message === "string" && d.message) {
        return d.message;
      }
      if (status === "cancelled") {
        return typeof d.message === "string" && d.message ? d.message : "已取消本次请求";
      }
      const baseUrl = d.base_url;
      const msg = typeof d.message === "string" ? d.message : "";
      const stage = typeof d.timeout_stage === "string" ? d.timeout_stage : "";
      const intentHint =
        typeof d === "object" &&
        d &&
        (d as { detected_intent?: string }).detected_intent === "calendar" &&
        stage === "ollama_first_call"
          ? "\n【提示】若句子已是明确日程（含明天、下午三点等），可尝试用更完整时间表述以触发本地日程快捷创建。"
          : "";
      const stageHint =
        stage === "ollama_summary"
          ? "\n【阶段】AI 在总结执行结果时超时；若下方列出「已完成的步骤」，说明工具已执行。"
          : stage === "ollama_first_call"
            ? "\n【阶段】本次主要耗时在 Ollama 模型生成（首轮或工具规划）。轻薄本可尝试更小模型或使用更明确的业务指令。" +
              intentHint
            : stage === "tool_execution"
              ? "\n【阶段】工具执行阶段异常或超时。"
              : stage === "config"
                ? "\n【阶段】加载 AI 配置时超时。"
                : stage === "intent"
                  ? "\n【阶段】意图识别阶段超时。"
                  : stage === "client_wait"
                    ? "\n【阶段】客户端等待超时（请检查网络或 Ollama 是否长时间无响应）。"
                    : stage && stage !== "unknown"
                      ? `\n【阶段】${stage}`
                      : "";
      if (status === "connection_refused" && baseUrl) {
        return `Ollama 服务不可连接，请确认模型服务已启动：${baseUrl}${stageHint}`;
      }
      if (status === "http_error" && baseUrl) {
        return msg
          ? `${msg}（${baseUrl}）${stageHint}`
          : `无法访问 Ollama（${baseUrl}），请确认服务已启动且地址、端口正确。${stageHint}`;
      }
      if (msg) return `${msg}${stageHint}`;
    }
  } catch {
    // 非 JSON 时退回原文
  }
  return raw;
}

export function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(AUTH_TOKEN_KEY);
}

export function setStoredToken(token: string | null): void {
  if (typeof window === "undefined") return;
  if (token == null) localStorage.removeItem(AUTH_TOKEN_KEY);
  else localStorage.setItem(AUTH_TOKEN_KEY, token);
}

/** 401 时调用：清除 token 后由调用方负责跳转登录页 */
let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: (() => void) | null): void {
  onUnauthorized = fn;
}

export interface UserInfo {
  id: number;
  username: string;
  display_name: string | null;
  role: string;
  is_active: boolean;
  must_change_password: boolean;
  last_login_at: string | null;
  created_at?: string | null;
  bound_feishu_identities_count?: number;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: UserInfo;
}

export const authApi = {
  login: (body: { username: string; password: string }) =>
    request<LoginResponse>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  me: (token: string | null) =>
    request<UserInfo>("/api/v1/auth/me", { token: token || undefined }),
  updateMe: (body: { display_name?: string | null }) =>
    request<UserInfo>("/api/v1/auth/me", {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  changePassword: (body: { old_password: string; new_password: string }) =>
    request<UserInfo>("/api/v1/auth/change-password", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};

export const adminApi = {
  listUsers: (
    token: string | null,
    params?: { q?: string; role?: string; is_active?: boolean; page?: number; page_size?: number }
  ) =>
    request<{ ok: boolean; page: number; page_size: number; total: number; items: unknown[] }>(
      "/api/v1/admin/users",
      {
        params: toQueryParams({
          q: params?.q,
          role: params?.role,
          is_active: params?.is_active === true ? "true" : params?.is_active === false ? "false" : undefined,
          page: params?.page?.toString(),
          page_size: params?.page_size?.toString(),
        }),
        token: token || undefined,
      }
    ),
  createUser: (token: string | null, body: { username: string; password: string; display_name?: string; role?: string; is_active?: boolean; must_change_password?: boolean }) =>
    request<{ ok: boolean; user: unknown }>("/api/v1/admin/users", {
      method: "POST",
      body: JSON.stringify(body),
      token: token || undefined,
    }),
  updateUser: (token: string | null, userId: number, body: { display_name?: string; role?: string; is_active?: boolean; must_change_password?: boolean }) =>
    request<{ ok: boolean; user: unknown }>(`/api/v1/admin/users/${userId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
      token: token || undefined,
    }),
  resetPassword: (token: string | null, userId: number, body: { new_password: string; must_change_password?: boolean }) =>
    request<{ ok: boolean; user: unknown }>(`/api/v1/admin/users/${userId}/reset-password`, {
      method: "POST",
      body: JSON.stringify(body),
      token: token || undefined,
    }),
  setUserActive: (token: string | null, userId: number, is_active: boolean) =>
    request<{ ok: boolean; user: unknown }>(
      `/api/v1/admin/users/${userId}/set-active?is_active=${is_active}`,
      { method: "POST", token: token || undefined }
    ),
  deleteUser: (token: string | null, userId: number) =>
    request<{ ok: boolean; message: string }>(`/api/v1/admin/users/${userId}`, {
      method: "DELETE",
      token: token || undefined,
    }),
  listAuditLogs: (
    token: string | null,
    params?: { action?: string; target_type?: string; actor_user_id?: number; q?: string; start_date?: string; end_date?: string; page?: number; page_size?: number }
  ) =>
    request<{ ok: boolean; page: number; page_size: number; total: number; items: unknown[] }>(
      "/api/v1/admin/audit-logs",
      {
        params: toQueryParams({
          action: params?.action,
          target_type: params?.target_type,
          actor_user_id: params?.actor_user_id?.toString(),
          q: params?.q,
          start_date: params?.start_date,
          end_date: params?.end_date,
          page: params?.page?.toString(),
          page_size: params?.page_size?.toString(),
        }),
        token: token || undefined,
      }
    ),
  dashboardSummary: (token: string | null) =>
    request<{
      ok: boolean;
      total_users: number;
      active_users: number;
      admin_users: number;
      normal_users: number;
      total_feishu_identities: number;
      bound_feishu_identities: number;
      unbound_feishu_identities: number;
      ignored_feishu_identities: number;
      recent_audit_logs: { id: number; actor_username: string | null; action: string; target_type: string | null; target_id: string | null; detail: string; created_at: string | null }[];
      recent_login_success_count: number;
    }>("/api/v1/admin/dashboard-summary", { token: token || undefined }),
  projectGovernanceSummary: (token: string | null) =>
    request<{
      ok: boolean;
      legacy_owner_count: number;
      legacy_member_count: number;
      missing_initiator_count: number;
      missing_owner_count: number;
      initiator_owner_conflict_count: number;
      dirty_collaborator_relation_count: number;
      visibility_mismatch_count: number;
      manual_repair_queue_count: number;
      overdue_repair_queue_count: number;
    }>("/api/v1/admin/project-governance/summary", { token: token || undefined }),
  projectGovernanceRepairQueue: (
    token: string | null,
    params?: {
      issue_type?: string;
      status?: string;
      severity?: string;
      active_only?: boolean;
      overdue_only?: boolean;
    }
  ) =>
    request<{ ok: boolean; items: Record<string, unknown>[] }>("/api/v1/admin/project-governance/repair-queue", {
      token: token || undefined,
      params: toQueryParams({
        issue_type: params?.issue_type,
        status: params?.status,
        severity: params?.severity,
        active_only: params?.active_only === true ? true : undefined,
        overdue_only: params?.overdue_only === true ? true : undefined,
      }),
    }),
  startProjectRepairQueue: (token: string | null, queueId: number) =>
    request<{ ok: boolean; item: Record<string, unknown> }>(
      `/api/v1/admin/project-governance/repair-queue/${queueId}/start`,
      {
        method: "POST",
        token: token || undefined,
      }
    ),
  runProjectGovernanceScan: (token: string | null) =>
    request<{
      ok: boolean;
      queued: number;
      visibility_mismatch_new?: number;
      visibility_pairs_scanned?: number;
      visibility_case1_list_visible_detail_forbidden?: number;
      visibility_case2_detail_readable_not_listed?: number;
      visibility_scan_errors?: number;
    }>("/api/v1/admin/project-governance/scan", {
      method: "POST",
      token: token || undefined,
    }),
  updateProjectRepairQueueStatus: (
    token: string | null,
    queueId: number,
    body: { status: "resolved" | "ignored" | "false_positive"; resolution_note?: string | null }
  ) =>
    request<{ ok: boolean; item: Record<string, unknown> }>(
      `/api/v1/admin/project-governance/repair-queue/${queueId}/status`,
      {
        method: "POST",
        body: JSON.stringify(body),
        token: token || undefined,
      }
    ),
  getUserDetail: (token: string | null, userId: number) =>
    request<{
      ok: boolean;
      user: Record<string, unknown> & { bound_feishu_identities: unknown[]; bound_feishu_count: number; project_count: number; customer_count: number; conversation_count: number; calendar_event_count: number };
    }>(`/api/v1/admin/users/${userId}`, { token: token || undefined }),
  getAuditLogDetail: (token: string | null, logId: number) =>
    request<{ ok: boolean; item: Record<string, unknown> }>(
      `/api/v1/admin/audit-logs/${logId}`,
      { token: token || undefined }
    ),
  systemStatus: (token: string | null) =>
    request<{
      ok: boolean;
      app_name: string;
      app_version: string;
      environment: string;
      database_connected: boolean;
      database_url_masked?: string | null;
      default_admin_exists: boolean;
      total_users: number;
      total_active_users: number;
      total_feishu_identities: number;
      total_bound_feishu_identities: number;
      feishu_config_present: boolean;
      feishu_desktop_disabled?: boolean;
      model_config_present: boolean;
      current_server_time: string;
      uptime_seconds?: number | null;
      warnings: string[];
    }>("/api/v1/admin/system-status", { token: token || undefined }),
  systemInfo: (token: string | null) =>
    request<{
      ok: boolean;
      app_name: string;
      app_version: string;
      build_time?: string | null;
      environment: string;
      features: string[];
      enabled_modules: string[];
      notes: string[];
    }>("/api/v1/admin/system-info", { token: token || undefined }),
  exportUsers: (token: string | null, params?: { q?: string; role?: string; is_active?: boolean }) =>
    downloadCsv("/api/v1/admin/export/users", token, params, "users.csv"),
  exportAuditLogs: (token: string | null, params?: { action?: string; target_type?: string; actor_user_id?: number; start_date?: string; end_date?: string; q?: string }) =>
    downloadCsv("/api/v1/admin/export/audit-logs", token, params, "audit_logs.csv"),
};

export type MaintenanceSummary = {
  ok: boolean;
  project_count: number;
  customer_count: number;
  calendar_event_count: number;
  conversation_count: number;
  null_owner_project_count: number;
  null_owner_customer_count: number;
  null_owner_calendar_event_count: number;
  null_owner_conversation_count: number;
  chat_log_count: number;
  system_log_count: number;
  audit_log_count: number;
  feishu_event_count: number;
};

const CONFIRM_TEXTS: Record<string, string> = {
  chat: "CLEAR_CHAT_LOGS",
  system: "CLEAR_SYSTEM_LOGS",
  audit: "CLEAR_AUDIT_LOGS",
  feishu: "CLEAR_FEISHU_LOGS",
  all: "CLEAR_ALL_LOGS",
};

export const maintenanceApi = {
  getSummary: (token: string | null) =>
    request<MaintenanceSummary>("/api/v1/admin/maintenance/summary", { token: token || undefined }),
  clearLogs: (token: string | null, scope: string, confirmText: string) =>
    request<{ ok: boolean; scope: string; deleted_count: number }>(
      "/api/v1/admin/maintenance/logs/clear",
      {
        method: "POST",
        body: JSON.stringify({ scope, confirm_text: confirmText }),
        token: token || undefined,
      }
    ),
  getConfirmTextForScope: (scope: string) => CONFIRM_TEXTS[scope] ?? scope,
  reassignData: (
    token: string | null,
    body: {
      resource_type: string;
      target_user_id: number;
      only_null_owner?: boolean;
      before_datetime?: string | null;
      confirm_text: string;
    }
  ) =>
    request<{ ok: boolean; resource_type: string; updated_count: number }>(
      "/api/v1/admin/maintenance/data/reassign",
      { method: "POST", body: JSON.stringify(body), token: token || undefined }
    ),
  deleteData: (
    token: string | null,
    body: {
      resource_type: string;
      mode: string;
      target_user_id?: number | null;
      ids?: number[] | null;
      before_datetime?: string | null;
      confirm_text: string;
    }
  ) =>
    request<{ ok: boolean; resource_type: string; mode: string; deleted_count: number }>(
      "/api/v1/admin/maintenance/data/delete",
      { method: "POST", body: JSON.stringify(body), token: token || undefined }
    ),
};

async function request<T>(
  path: string,
  options?: RequestInit & { params?: Record<string, string>; token?: string | null; timeoutMs?: number }
): Promise<T> {
  const { params, token: tokenOpt, timeoutMs, ...init } = options ?? {};
  const externalSignal = init.signal;
  const { signal: _omitSignal, ...fetchInit } = init;
  const base = getApiBase();
  const url = new URL(path.startsWith("http") ? path : `${base}${path}`);
  if (params) {
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  }
  const requestUrl = url.toString();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(fetchInit.headers as Record<string, string>),
  };
  const token = tokenOpt ?? getStoredToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  const useComposite =
    (typeof timeoutMs === "number" && timeoutMs > 0) || externalSignal != null;
  const controller = useComposite ? new AbortController() : undefined;
  let userCancelled = false;
  const onExternalAbort = () => {
    userCancelled = true;
    controller?.abort();
  };
  if (externalSignal) {
    if (externalSignal.aborted) {
      userCancelled = true;
      controller?.abort();
    } else {
      externalSignal.addEventListener("abort", onExternalAbort, { once: true });
    }
  }
  const timer =
    controller != null && typeof timeoutMs === "number" && timeoutMs > 0
      ? setTimeout(() => controller.abort(), timeoutMs)
      : undefined;
  try {
    const res = await fetch(requestUrl, {
      ...fetchInit,
      headers,
      signal: controller?.signal,
    });
    if (!res.ok) {
      const text = await res.text();
      if (res.status === 401) {
        // 登录接口本身返回 401（用户名或密码错误）不应触发全局登出/跳转，只作为表单错误处理
        const pathname = url.pathname || "";
        const isLoginPath = pathname.endsWith("/api/v1/auth/login");
        if (!isLoginPath) {
          setStoredToken(null);
          onUnauthorized?.();
        }
      }
      console.error("[API] request failed", {
        request_url: requestUrl,
        response_status: res.status,
        error_message: text || `HTTP ${res.status}`,
      });
      throw new ApiRequestError(text || `HTTP ${res.status}`, res.status, text || "", requestUrl);
    }
    if (res.status === 204) return undefined as T;
    return res.json() as Promise<T>;
  } catch (e) {
    const err = e instanceof Error ? e : new Error(String(e));
    const status = (e as { status?: number }).status;
    console.error("[API] request error", {
      request_url: requestUrl,
      error_message: err.message,
      response_status: status ?? "(network error or no response)",
    });
    if (err.name === "AbortError") {
      if (userCancelled) {
        throw new ApiRequestError(
          "已取消本次请求",
          499,
          JSON.stringify({
            detail: { message: "已取消本次请求", status: "cancelled" },
          }),
          requestUrl
        );
      }
      throw new ApiRequestError(
        "请求超时（已超过客户端等待上限），请稍后重试或检查网络与 Ollama 服务。",
        504,
        JSON.stringify({
          detail: {
            message: "请求超时（已超过客户端等待上限）",
            status: "timeout",
            timeout_stage: "client_wait",
          },
        }),
        requestUrl
      );
    }
    throw e;
  } finally {
    if (timer) clearTimeout(timer);
    if (externalSignal) {
      externalSignal.removeEventListener("abort", onExternalAbort);
    }
  }
}

function toQueryParams(input: Record<string, string | number | boolean | undefined | null>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(input)) {
    if (v == null || v === "") continue;
    out[k] = String(v);
  }
  return out;
}

async function downloadCsv(
  path: string,
  token: string | null,
  params?: Record<string, string | number | boolean | undefined | null>,
  filename: string = "export.csv"
): Promise<void> {
  const base = getApiBase();
  const url = new URL(path.startsWith("http") ? path : `${base}${path}`);
  if (params) {
    Object.entries(toQueryParams(params)).forEach(([k, v]) => url.searchParams.set(k, v));
  }
  const t = token ?? getStoredToken();
  const headers: Record<string, string> = {};
  if (t) headers["Authorization"] = `Bearer ${t}`;
  const res = await fetch(url.toString(), { headers });
  if (!res.ok) {
    const errText = await res.text();
    if (res.status === 401) {
      setStoredToken(null);
      onUnauthorized?.();
    }
    throw new Error(errText || `HTTP ${res.status}`);
  }
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

// --- Projects
export const projectsApi = {
  list: () => request<Project[]>("/api/v1/projects"),
  listSelectableUsers: () =>
    request<{ id: number; username: string; display_name: string | null; role: string }[]>(
      "/api/v1/projects/selectable-users"
    ),
  get: (id: number) => request<Project>(`/api/v1/projects/${id}`),
  create: (body: ProjectCreate) =>
    request<Project>("/api/v1/projects", { method: "POST", body: JSON.stringify(body) }),
  update: (id: number, body: ProjectUpdate) =>
    request<Project>(`/api/v1/projects/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  delete: (id: number) =>
    request<void>(`/api/v1/projects/${id}`, { method: "DELETE" }),
  undo: (id: number) =>
    request<Project>(`/api/v1/projects/${id}/undo`, { method: "POST" }),
  linkCustomers: (projectId: number, customerIds: number[]) =>
    request<{ success: boolean; linked_count: number; skipped_existing_count: number; failed_ids: number[] }>(
      `/api/v1/projects/${projectId}/customers/link`,
      { method: "POST", body: JSON.stringify({ customer_ids: customerIds }) }
    ),
  unlinkCustomer: (projectId: number, customerId: number) =>
    request<{ success: boolean; removed: boolean }>(
      `/api/v1/projects/${projectId}/customers/${customerId}/link`,
      { method: "DELETE" }
    ),
  listOwnerRepairQueue: () =>
    request<{ project_id: number; owner_text: string | null; reason: string; created_at: string | null }[]>(
      "/api/v1/projects/owner-repair-queue"
    ),
  resolveOwnerRepairQueue: (projectId: number, body: { owner_user_id: number }) =>
    request<{ success: boolean; project_id: number; owner_user_id: number }>(
      `/api/v1/projects/owner-repair-queue/${projectId}/resolve`,
      { method: "POST", body: JSON.stringify(body) }
    ),
};

// --- Customers
export const customersApi = {
  list: () => request<Customer[]>("/api/v1/customers"),
  get: (id: number) => request<CustomerDetail>(`/api/v1/customers/${id}`),
  create: (body: CustomerCreate) =>
    request<Customer>("/api/v1/customers", { method: "POST", body: JSON.stringify(body) }),
  update: (id: number, body: CustomerUpdate) =>
    request<Customer>(`/api/v1/customers/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  delete: (id: number) =>
    request<void>(`/api/v1/customers/${id}`, { method: "DELETE" }),
  undo: (id: number) =>
    request<Customer>(`/api/v1/customers/${id}/undo`, { method: "POST" }),
  createInteraction: (customerId: number, body: CustomerInteractionCreate) =>
    request<import("@/types/customer").CustomerInteraction>(
      `/api/v1/customers/${customerId}/interactions`,
      { method: "POST", body: JSON.stringify(body) }
    ),
  updateInteraction: (customerId: number, interactionId: number, body: CustomerInteractionUpdate) =>
    request<import("@/types/customer").CustomerInteraction>(
      `/api/v1/customers/${customerId}/interactions/${interactionId}`,
      { method: "PUT", body: JSON.stringify(body) }
    ),
  deleteInteraction: (customerId: number, interactionId: number) =>
    request<void>(`/api/v1/customers/${customerId}/interactions/${interactionId}`, { method: "DELETE" }),
  linkProjects: (customerId: number, projectIds: number[]) =>
    request<{ success: boolean; linked_count: number; skipped_existing_count: number; failed_ids: number[] }>(
      `/api/v1/customers/${customerId}/projects/link`,
      { method: "POST", body: JSON.stringify({ project_ids: projectIds }) }
    ),
  unlinkProject: (customerId: number, projectId: number) =>
    request<{ success: boolean; removed: boolean }>(
      `/api/v1/customers/${customerId}/projects/${projectId}/link`,
      { method: "DELETE" }
    ),
};

// --- AI 就绪状态（公开，无需 token）
export const aiReadyApi = {
  getReady: () =>
    request<{ ready: boolean; model_ready: boolean; ollama_reachable: boolean; last_warmup_at: string | null }>(
      "/ai/ready"
    ),
};

// --- AI 配置
export const aiConfigApi = {
  getConfig: () => request<AIConfig | null>("/api/v1/ai/config"),
  saveConfig: (body: AIConfigSave) =>
    request<AIConfig>("/api/v1/ai/config", { method: "POST", body: JSON.stringify(body) }),
  testConnection: (body: { base_url: string; model_name: string }) =>
    request<{
      ok: boolean;
      status: string;
      detail: string;
      base_url: string;
      model_name: string;
      available_models: string[];
    }>("/api/v1/ai/test-connection", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  chat: (body: { messages: ChatMessageCreate[] }, opts?: { signal?: AbortSignal }) =>
    request<AiChatResponse>("/api/v1/ai/chat", {
      method: "POST",
      body: JSON.stringify({
        messages: body.messages.map((m) => ({ role: m.role, content: m.content })),
      }),
      timeoutMs: 125_000,
      signal: opts?.signal,
    }),
};

// --- 对话历史（会话列表、创建、更新标题、AI 生成标题）
function mapConversationFromApi(r: {
  id: number;
  title: string;
  source?: string;
  created_at: string;
  updated_at: string;
}): Conversation {
  return {
    id: r.id,
    title: r.title,
    source: r.source ?? "web",
    createdAt: r.created_at,
    updatedAt: r.updated_at,
  };
}

export const conversationApi = {
  list: async (): Promise<Conversation[]> => {
    const raw = await request<
      { id: number; title: string; source?: string; created_at: string; updated_at: string }[]
    >("/api/v1/chat/conversations");
    return raw.map(mapConversationFromApi);
  },
  create: async (title?: string): Promise<Conversation> => {
    const payload = title != null && title !== "" ? { title } : {};
    const r = await request<{
      id: number;
      title: string;
      source?: string;
      created_at: string;
      updated_at: string;
    }>("/api/v1/chat/conversations", { method: "POST", body: JSON.stringify(payload) });
    return mapConversationFromApi(r);
  },
  updateTitle: (id: number, title: string) =>
    request<{
      id: number;
      title: string;
      source?: string;
      created_at: string;
      updated_at: string;
    }>(`/api/v1/chat/conversations/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }).then(mapConversationFromApi),
  delete: (id: number) =>
    request<void>(`/api/v1/chat/conversations/${id}`, { method: "DELETE" }),
  getMessages: async (id: number): Promise<{ role: string; content: string; created_at: string | null }[]> => {
    return request<{ role: string; content: string; created_at: string | null }[]>(
      `/api/v1/chat/conversations/${id}/messages`
    );
  },
  summarizeTitle: (id: number, messages: { role: string; content: string }[]) =>
    request<{ title: string }>(`/api/v1/chat/conversations/${id}/summarize-title`, {
      method: "POST",
      body: JSON.stringify({ messages }),
    }),
};

// --- Logs
export const logsApi = {
  listSystem: (params?: { level?: string; module?: string; user_id?: number; page?: number; page_size?: number }) =>
    request<PaginatedResponse<SystemLog>>("/api/v1/logs/system", {
      params: toQueryParams({
        level: params?.level,
        module: params?.module,
        user_id: params?.user_id?.toString(),
        page: params?.page?.toString(),
        page_size: params?.page_size?.toString(),
      }),
    }),
  listChat: (params?: { q?: string; channel?: string; user_id?: number; page?: number; page_size?: number }) =>
    request<PaginatedResponse<ChatRecord>>("/api/v1/logs/chat", {
      params: toQueryParams({
        q: params?.q,
        channel: params?.channel,
        user_id: params?.user_id?.toString(),
        page: params?.page?.toString(),
        page_size: params?.page_size?.toString(),
      }),
    }),
  clear: () =>
    request<{ ok: boolean; deleted_system: number; deleted_chat: number }>("/api/v1/logs", {
      method: "DELETE",
    }),
};

// --- Reminders (飞书定时提醒计划)
export type ReminderTaskRow = {
  id: number;
  owner_user_id: number;
  channel: string;
  title: string;
  content: string | null;
  related_event_id: number | null;
  related_project_id: number | null;
  related_customer_id: number | null;
  reminder_type: string;
  schedule_rule: Record<string, unknown> | null;
  next_trigger_at: string | null;
  last_trigger_at: string | null;
  end_at: string | null;
  is_enabled: boolean;
  status: string;
  created_at: string | null;
  updated_at: string | null;
};

export const remindersApi = {
  list: (params?: { status?: string }) =>
    request<ReminderTaskRow[]>("/api/v1/reminders", {
      params: toQueryParams({ status: params?.status }),
    }),
  update: (
    id: number,
    body: {
      title?: string;
      content?: string | null;
      end_at?: string | null;
      is_enabled?: boolean;
      schedule_rule?: Record<string, unknown>;
      status?: "active" | "paused";
    }
  ) =>
    request<ReminderTaskRow>(`/api/v1/reminders/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  cancel: (id: number) =>
    request<{ reminder_task_id: number; status: string }>(`/api/v1/reminders/${id}/cancel`, {
      method: "POST",
    }),
};

// --- Calendar
export const calendarApi = {
  getEvent: (id: number) =>
    request<CalendarEvent>(`/api/v1/calendar/events/${id}`),
  listEvents: (params?: { start?: string; end?: string; project_id?: number }) =>
    request<CalendarEvent[]>("/api/v1/calendar/events", {
      params: toQueryParams({
        start: params?.start,
        end: params?.end,
        project_id: params?.project_id?.toString(),
      }),
    }),
  createEvent: (body: CalendarEventCreate) =>
    request<CalendarEvent>("/api/v1/calendar/events", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateEvent: (id: number, body: CalendarEventUpdate) =>
    request<CalendarEvent>(`/api/v1/calendar/events/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteEvent: (id: number) =>
    request<void>(`/api/v1/calendar/events/${id}`, { method: "DELETE" }),
};

// --- Collaboration (projects)
import type { Collaborator, CollaboratorAdd, ProjectActivity, ProjectActivityCreate, CustomerFollowup, CustomerFollowupCreate, CalendarEventComment, CalendarEventCommentCreate, TransferOwnerRequest, TransferOwnerResponse } from "@/types/collaboration";

export const projectCollabApi = {
  listCollaborators: (projectId: number) =>
    request<Collaborator[]>(`/api/v1/projects/${projectId}/collaborators`),
  getShareMembers: (projectId: number) =>
    request<{
      initiator: { user_id: number; display_name: string; username: string; is_active: boolean } | null;
      owner: { user_id: number; display_name: string; username: string; is_active: boolean } | null;
      collaborators: Collaborator[];
      legacy_members: { legacy_key: string; display_name: string; reason: string; created_at?: string | null }[];
    }>(`/api/v1/projects/${projectId}/share-members`),
  addCollaborator: (projectId: number, body: CollaboratorAdd) =>
    request<Collaborator>(`/api/v1/projects/${projectId}/collaborators`, { method: "POST", body: JSON.stringify(body) }),
  removeCollaborator: (projectId: number, userId: number) =>
    request<void>(`/api/v1/projects/${projectId}/collaborators/${userId}`, { method: "DELETE" }),
  cleanupLegacyMember: (projectId: number, legacyKey: string) =>
    request<{ ok: boolean; removed: boolean; legacy_key: string }>(`/api/v1/projects/${projectId}/legacy-members/${legacyKey}`, { method: "DELETE" }),
  listUpdates: (projectId: number) =>
    request<ProjectActivity[]>(`/api/v1/projects/${projectId}/updates`),
  addUpdate: (projectId: number, body: ProjectActivityCreate) =>
    request<ProjectActivity>(`/api/v1/projects/${projectId}/updates`, { method: "POST", body: JSON.stringify(body) }),
  deleteUpdate: (projectId: number, updateId: number) =>
    request<void>(`/api/v1/projects/${projectId}/updates/${updateId}`, { method: "DELETE" }),
  transferOwner: (projectId: number, body: TransferOwnerRequest) =>
    request<TransferOwnerResponse>(`/api/v1/projects/${projectId}/transfer-owner`, { method: "POST", body: JSON.stringify(body) }),
  transferInitiator: (projectId: number, body: TransferOwnerRequest) =>
    request<{ ok: boolean; project_id: number; initiator_user_id: number | null }>(`/api/v1/projects/${projectId}/transfer-initiator`, { method: "POST", body: JSON.stringify(body) }),
};

// --- Collaboration (customers)
export const customerCollabApi = {
  listCollaborators: (customerId: number) =>
    request<Collaborator[]>(`/api/v1/customers/${customerId}/collaborators`),
  addCollaborator: (customerId: number, body: CollaboratorAdd) =>
    request<Collaborator>(`/api/v1/customers/${customerId}/collaborators`, { method: "POST", body: JSON.stringify(body) }),
  removeCollaborator: (customerId: number, userId: number) =>
    request<void>(`/api/v1/customers/${customerId}/collaborators/${userId}`, { method: "DELETE" }),
  listFollowups: (customerId: number) =>
    request<CustomerFollowup[]>(`/api/v1/customers/${customerId}/followups`),
  addFollowup: (customerId: number, body: CustomerFollowupCreate) =>
    request<CustomerFollowup>(`/api/v1/customers/${customerId}/followups`, { method: "POST", body: JSON.stringify(body) }),
  deleteFollowup: (customerId: number, followupId: number) =>
    request<void>(`/api/v1/customers/${customerId}/followups/${followupId}`, { method: "DELETE" }),
  transferOwner: (customerId: number, body: TransferOwnerRequest) =>
    request<TransferOwnerResponse>(`/api/v1/customers/${customerId}/transfer-owner`, { method: "POST", body: JSON.stringify(body) }),
};

// --- Collaboration (calendar events)
export const calendarCollabApi = {
  listCollaborators: (eventId: number) =>
    request<Collaborator[]>(`/api/v1/calendar/events/${eventId}/collaborators`),
  addCollaborator: (eventId: number, body: CollaboratorAdd) =>
    request<Collaborator>(`/api/v1/calendar/events/${eventId}/collaborators`, { method: "POST", body: JSON.stringify(body) }),
  removeCollaborator: (eventId: number, userId: number) =>
    request<void>(`/api/v1/calendar/events/${eventId}/collaborators/${userId}`, { method: "DELETE" }),
  listComments: (eventId: number) =>
    request<CalendarEventComment[]>(`/api/v1/calendar/events/${eventId}/comments`),
  addComment: (eventId: number, body: CalendarEventCommentCreate) =>
    request<CalendarEventComment>(`/api/v1/calendar/events/${eventId}/comments`, { method: "POST", body: JSON.stringify(body) }),
  deleteComment: (eventId: number, commentId: number) =>
    request<void>(`/api/v1/calendar/events/${eventId}/comments/${commentId}`, { method: "DELETE" }),
  transferOwner: (eventId: number, body: TransferOwnerRequest) =>
    request<TransferOwnerResponse>(`/api/v1/calendar/events/${eventId}/transfer-owner`, { method: "POST", body: JSON.stringify(body) }),
};

// Re-export types used by consumers that import from apiClient
export type { AiChatResponse, ExecutionResultItem } from "@/types/ai";
export type { Project, ProjectCreate, ProjectUpdate } from "@/types/project";
export type { Customer, CustomerCreate, CustomerUpdate, CustomerDetail, CustomerInteraction, CustomerInteractionCreate, CustomerInteractionUpdate } from "@/types/customer";
export type { CalendarEvent, CalendarEventCreate, CalendarEventUpdate } from "@/types/calendar";
export type { ChatMessageCreate } from "@/types/chat";
export type { PaginatedResponse } from "@/types/common";
export type { SystemLog, ChatRecord } from "@/types/logs";
export type { AIConfig, AIConfigSave } from "@/types/ai";
export type { Conversation } from "@/types/conversation";
export type { Collaborator, CollaboratorAdd, ProjectActivity, ProjectActivityCreate, CustomerFollowup, CustomerFollowupCreate, CalendarEventComment, CalendarEventCommentCreate, TransferOwnerRequest, TransferOwnerResponse } from "@/types/collaboration";
