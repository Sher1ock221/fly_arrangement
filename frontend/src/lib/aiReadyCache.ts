import type { QueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/lib/queryKeys";

/** 与 GET /ai/ready 返回结构一致，供 React Query 缓存使用 */
export type AiReadyCacheData = {
  ready: boolean;
  model_ready: boolean;
  ollama_reachable: boolean;
  last_warmup_at: string | null;
};

/**
 * 一次真实对话已成功（收到助手正常回复）即视为服务端可用，立即写入 aiReady 缓存，
 * 避免 /ai/ready 仍报 model_ready=false 时预热横条永远不消失。
 */
export function markAiReadyProvenBySuccessfulChat(queryClient: QueryClient) {
  queryClient.setQueryData<AiReadyCacheData>(queryKeys.aiReady(), (prev) => ({
    ready: true,
    model_ready: true,
    ollama_reachable: prev?.ollama_reachable ?? true,
    last_warmup_at: prev?.last_warmup_at ?? new Date().toISOString(),
  }));
}
