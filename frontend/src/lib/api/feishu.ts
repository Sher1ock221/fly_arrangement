import type {
  FeishuConfigRead,
  FeishuConfigTestResult,
  FeishuConfigUpdatePayload,
} from "@/types/feishu";
import type {
  FeishuRecentError,
  FeishuRecentEvent,
  FeishuSimulatePayload,
  FeishuSimulateResponse,
  FeishuStatusResponse,
} from "@/types/ai";

import { getApiBase } from "@/lib/apiBase";

async function request<T>(
  path: string,
  options?: RequestInit & { params?: Record<string, string> }
): Promise<T> {
  const { params, ...init } = options ?? {};
  const base = getApiBase();
  const url = new URL(path.startsWith("http") ? path : `${base}${path}`);
  if (params) {
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  }
  const requestUrl = url.toString();
  try {
    const res = await fetch(requestUrl, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...init.headers,
      },
    });
    if (!res.ok) {
      const text = await res.text();
      console.error("[API] request failed", {
        request_url: requestUrl,
        response_status: res.status,
        error_message: text || `HTTP ${res.status}`,
      });
      throw new Error(text || `HTTP ${res.status}`);
    }
    if (res.status === 204) return undefined as T;
    return res.json() as Promise<T>;
  } catch (e) {
    const err = e instanceof Error ? e : new Error(String(e));
    console.error("[API] request error", {
      request_url: requestUrl,
      error_message: err.message,
      response_status: "(network error or no response)",
    });
    throw e;
  }
}

function toQueryParams(input: Record<string, string | undefined | null>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(input)) {
    if (v == null || v === "") continue;
    out[k] = v;
  }
  return out;
}

export const feishuApi = {
  getFeishuStatus: () => request<FeishuStatusResponse>("/api/v1/ai/feishu-status"),
  getFeishuConfig: () => request<FeishuConfigRead>("/api/v1/ai/feishu-config"),
  updateFeishuConfig: (body: FeishuConfigUpdatePayload) =>
    request<FeishuConfigRead>("/api/v1/ai/feishu-config", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  saveFeishuConfigCompat: (body: FeishuConfigUpdatePayload) =>
    request<FeishuConfigRead>("/api/v1/ai/feishu-config", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  testFeishuConfig: (body?: FeishuConfigUpdatePayload) =>
    request<FeishuConfigTestResult>("/api/v1/ai/feishu-config/test", {
      method: "POST",
      body: JSON.stringify(body ?? {}),
    }),
  simulateFeishuMessage: (body: FeishuSimulatePayload) =>
    request<FeishuSimulateResponse>("/api/v1/ai/feishu-simulate", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getFeishuRecentEvents: (params?: { limit?: number; process_status?: string; failed_only?: boolean }) =>
    request<{ ok: boolean; items: FeishuRecentEvent[] }>("/api/v1/ai/feishu-recent-events", {
      params: toQueryParams({
        limit: params?.limit?.toString(),
        process_status: params?.process_status,
        failed_only: params?.failed_only ? "true" : undefined,
      }),
    }),
  getFeishuRecentErrors: (params?: { limit?: number; module_prefix?: string }) =>
    request<{ ok: boolean; items: FeishuRecentError[] }>("/api/v1/ai/feishu-recent-errors", {
      params: toQueryParams({
        limit: params?.limit?.toString(),
        module_prefix: params?.module_prefix,
      }),
    }),
};
