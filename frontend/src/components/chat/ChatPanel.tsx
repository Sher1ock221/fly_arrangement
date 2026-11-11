"use client";

import { useState, useRef, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Send, Loader2, User, Bot, CalendarCheck, RefreshCw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/types/chat";
import { ExecutionSteps } from "@/components/chat/ExecutionSteps";
import type { ExecutionResult } from "@/types/ai";
import { aiReadyApi } from "@/lib/apiClient";
import { markAiReadyProvenBySuccessfulChat } from "@/lib/aiReadyCache";
import { queryKeys } from "@/lib/queryKeys";
import { formatShortcutBadgeLabel } from "@/lib/shortcutDisplay";

const STORAGE_KEY = "ai_chat_history";
const QUICK_PROMPTS = ["帮我总结本周进展", "创建一个新项目", "我有哪些待办事项"];

export interface ChatPanelProps {
  mode: "page" | "widget";
  /** 至少包含 role 与 content（兼容完整 ChatMessage 或简单 { role, content }） */
  messages: Array<
    | { role: "user" | "assistant"; content: string }
    | (ChatMessage & { execution_results?: ExecutionResult[] })
  >;
  onSend: (text: string) => Promise<void>;
  /** 中止当前 AI 请求（由 ChatContext.cancelPendingChat 提供） */
  onCancelPending?: () => void;
  loading: boolean;
  /** 切换会话拉取消息中：勿展示上一会话内容 */
  messagesLoading?: boolean;
  messagesError?: boolean;
  onRetryMessages?: () => void;
  /**
   * 无消息时的占位：welcome = 新会话引导（仅悬浮窗无当前会话等场景）；
   * no-messages = 历史会话空列表文案
   */
  emptyPlaceholder?: "welcome" | "no-messages";
  /** 可选：聚焦输入框（用于新建对话后自动聚焦） */
  inputRef?: React.RefObject<HTMLInputElement | null>;
}

export function ChatPanel({
  mode,
  messages,
  onSend,
  onCancelPending,
  loading,
  messagesLoading = false,
  messagesError = false,
  onRetryMessages,
  emptyPlaceholder = "no-messages",
  inputRef: inputRefProp,
}: ChatPanelProps) {
  const queryClient = useQueryClient();
  const listEndRef = useRef<HTMLDivElement>(null);
  const internalInputRef = useRef<HTMLInputElement>(null);
  const inputRef = inputRefProp ?? internalInputRef;
  const isMobile = useMobile();
  const [inputValue, setInputValue] = useState("");
  const [keyboardInset, setKeyboardInset] = useState(0);
  const [hasSuccessfulAiResponse, setHasSuccessfulAiResponse] = useState(false);
  const [slowGenHint, setSlowGenHint] = useState(false);

  const aiReadyQuery = useQuery({
    queryKey: queryKeys.aiReady(),
    queryFn: () => aiReadyApi.getReady(),
    // ready=true 或已通过对话证明可用后不再轮询；仍为 false 时每 5 秒拉一次
    refetchInterval: (query) =>
      query.state.data?.ready === true || hasSuccessfulAiResponse ? false : 5000,
    staleTime: 0,
  });
  const aiReady = aiReadyQuery.data;

  const lastAssistantMessage = [...messages]
    .reverse()
    .find((m) => m.role === "assistant");

  /** 最后一条助手消息表明对话已成功：有正文、或有任一工具成功执行，且不是「错误：」类回复 */
  const hasCurrentSuccessfulAssistantReply = (() => {
    const m = lastAssistantMessage;
    if (!m || m.role !== "assistant") return false;
    const text = (m.content ?? "").trim();
    if (text.startsWith("错误：")) return false;
    if (text.length > 0) return true;
    const er =
      "execution_results" in m && Array.isArray((m as ChatMessage).execution_results)
        ? (m as ChatMessage).execution_results
        : undefined;
    return Boolean(er?.some((r: ExecutionResult) => r.success));
  })();

  /**
   * 是否可视为「AI 已可用」：以 /ai/ready 为主，但任意一次成功回复可推翻 ready=false
   * （避免 Ollama 未标 model_ready、但实际 /api/v1/ai/chat 已可用的假预热态）。
   */
  const aiEffectivelyReady =
    (aiReadyQuery.isSuccess && aiReady?.ready === true) ||
    hasSuccessfulAiResponse ||
    hasCurrentSuccessfulAssistantReply;

  useEffect(() => {
    if (messagesLoading) return;
    if (messages.length === 0) {
      setHasSuccessfulAiResponse(false);
      return;
    }
    if (hasCurrentSuccessfulAssistantReply) {
      setHasSuccessfulAiResponse(true);
    }
  }, [messages, messagesLoading, hasCurrentSuccessfulAssistantReply]);

  useEffect(() => {
    if (!loading) {
      setSlowGenHint(false);
      return;
    }
    const t = window.setTimeout(() => setSlowGenHint(true), 30000);
    return () => window.clearTimeout(t);
  }, [loading]);

  useEffect(() => {
    if (hasCurrentSuccessfulAssistantReply) {
      markAiReadyProvenBySuccessfulChat(queryClient);
    }
  }, [hasCurrentSuccessfulAssistantReply, queryClient]);

  const showAiWarmupBanner =
    aiReadyQuery.isSuccess &&
    aiReady?.ready === false &&
    !aiEffectivelyReady &&
    !messagesLoading;

  useEffect(() => {
    listEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (typeof window === "undefined" || !window.visualViewport) return;
    const vv = window.visualViewport;
    const updateInset = () => {
      const inset = Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
      setKeyboardInset(inset);
    };
    updateInset();
    vv.addEventListener("resize", updateInset);
    vv.addEventListener("scroll", updateInset);
    return () => {
      vv.removeEventListener("resize", updateInset);
      vv.removeEventListener("scroll", updateInset);
    };
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const text = inputValue.trim();
    if (!text || loading) return;
    setInputValue("");
    await onSend(text);
  };

  return (
    <div
      className={cn(
        "flex flex-col bg-background",
        "h-full min-h-0"
      )}
    >
      <div className="flex-1 min-h-0 overflow-y-auto px-3 py-3 md:px-6 md:py-4">
        <div className="mx-auto w-full max-w-6xl space-y-3">
          {showAiWarmupBanner && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/40 px-3 py-2 text-sm text-amber-800 dark:text-amber-200">
              <Loader2 className="inline h-4 w-4 animate-spin mr-1.5 align-middle" />
              AI 正在预热，请稍候再发送消息
            </div>
          )}
          {messagesLoading && (
            <div className="flex flex-col items-center justify-center gap-3 py-16 text-sm text-muted-foreground">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
              <p>正在加载对话…</p>
            </div>
          )}
          {!messagesLoading && messagesError && (
            <div className="flex flex-col items-center justify-center gap-4 py-12 text-center text-sm">
              <p className="text-destructive">对话加载失败，请重试</p>
              {onRetryMessages && (
                <Button type="button" variant="outline" size="sm" onClick={() => onRetryMessages()}>
                  重试
                </Button>
              )}
            </div>
          )}
          {!messagesLoading && !messagesError && messages.length === 0 && emptyPlaceholder === "welcome" && (
            <div className="py-6 text-sm text-muted-foreground">
              <p className="text-center">你好，我是一名企业项目管理助手，主要可以帮你做这些事：</p>
              {mode === "widget" && (
                <div className="mt-3 grid grid-cols-1 gap-2">
                  {QUICK_PROMPTS.map((q) => (
                    <button
                      key={q}
                      type="button"
                      onClick={() => void onSend(q)}
                      disabled={loading}
                      className="rounded-lg border border-border bg-card px-3 py-2 text-left text-xs hover:bg-muted disabled:opacity-50"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
          {!messagesLoading && !messagesError && messages.length === 0 && emptyPlaceholder === "no-messages" && (
            <div className="py-12 text-center text-sm text-muted-foreground">该会话暂无消息</div>
          )}
          {!messagesLoading &&
            !messagesError &&
            messages.map((m, i) => (
            <div
              key={"id" in m && typeof (m as ChatMessage).id === "number" ? (m as ChatMessage).id : i}
              className={cn(
                "flex gap-2",
                m.role === "user" ? "justify-end" : "justify-start"
              )}
            >
              {m.role === "assistant" && (
                <div className="shrink-0 mt-1 rounded-full bg-[#f5f5f5] dark:bg-muted p-1.5">
                  <Bot className="h-4 w-4 text-muted-foreground" />
                </div>
              )}
              <div className="flex flex-col gap-1.5 max-w-[85%]">
                <div
                  className={cn(
                    "rounded-2xl px-4 py-2.5 text-sm break-words",
                    m.role === "user"
                      ? "bg-[#1677ff] text-white rounded-br-md"
                      : "bg-[#f5f5f5] dark:bg-muted text-foreground rounded-bl-md"
                  )}
                >
                  <span className="whitespace-pre-wrap">{m.content}</span>
                </div>
                {m.role === "assistant" &&
                  "ai_debug" in m &&
                  m.ai_debug &&
                  typeof m.ai_debug.shortcut === "string" &&
                  m.ai_debug.shortcut && (
                    <div className="text-xs text-emerald-800 dark:text-emerald-300/90 px-1">
                      本地快速处理：{formatShortcutBadgeLabel(m.ai_debug.shortcut)}
                    </div>
                  )}
                {m.role === "assistant" &&
                  "execution_results" in m &&
                  Array.isArray(m.execution_results) &&
                  (m.execution_results as ExecutionResult[]).some(
                    (r) => r.tool_name === "suggest_schedule" && r.success
                  ) &&
                  !loading && (
                    <div className="flex gap-2 mt-0.5">
                      <button
                        type="button"
                        onClick={() => void onSend("确认安排")}
                        disabled={loading}
                        className="inline-flex items-center gap-1 rounded-lg border border-green-200 bg-green-50 dark:bg-green-900/20 dark:border-green-800 px-3 py-1.5 text-xs text-green-700 dark:text-green-400 hover:bg-green-100 dark:hover:bg-green-900/40 transition-colors disabled:opacity-50"
                      >
                        <CalendarCheck className="h-3.5 w-3.5" />
                        确认安排
                      </button>
                      <button
                        type="button"
                        onClick={() => void onSend("换一个时间")}
                        disabled={loading}
                        className="inline-flex items-center gap-1 rounded-lg border border-blue-200 bg-blue-50 dark:bg-blue-900/20 dark:border-blue-800 px-3 py-1.5 text-xs text-blue-700 dark:text-blue-400 hover:bg-blue-100 dark:hover:bg-blue-900/40 transition-colors disabled:opacity-50"
                      >
                        <RefreshCw className="h-3.5 w-3.5" />
                        换个时间
                      </button>
                      <button
                        type="button"
                        onClick={() => void onSend("取消安排")}
                        disabled={loading}
                        className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-gray-50 dark:bg-gray-900/20 dark:border-gray-700 px-3 py-1.5 text-xs text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-900/40 transition-colors disabled:opacity-50"
                      >
                        <X className="h-3.5 w-3.5" />
                        取消
                      </button>
                    </div>
                  )}
                {"execution_results" in m &&
                  Array.isArray(m.execution_results) &&
                  m.execution_results.length > 0 && (
                    <div className="mt-0.5">
                      <ExecutionSteps steps={m.execution_results as ExecutionResult[]} />
                    </div>
                  )}
                {"ai_debug" in m && m.ai_debug && (
                  <details className="mt-0.5 rounded-md border border-border/50 bg-muted/20 px-2 py-1 text-[11px] text-muted-foreground max-w-full">
                    <summary className="cursor-pointer select-none">本轮请求诊断（耗时）</summary>
                    <div className="mt-1 space-y-0.5 font-mono break-all">
                      {m.ai_debug.request_id && <div>request_id: {m.ai_debug.request_id}</div>}
                      {m.ai_debug.shortcut && <div>shortcut: {m.ai_debug.shortcut}</div>}
                      {m.ai_debug.detected_intent != null && (
                        <div>intent: {String(m.ai_debug.detected_intent)}</div>
                      )}
                      {m.ai_debug.phase_elapsed_ms &&
                        Object.keys(m.ai_debug.phase_elapsed_ms).length > 0 && (
                          <div className="pt-0.5">
                            phase_ms:{" "}
                            {Object.entries(m.ai_debug.phase_elapsed_ms)
                              .map(([k, v]) => `${k}=${v}`)
                              .join(", ")}
                          </div>
                        )}
                    </div>
                  </details>
                )}
              </div>
              {m.role === "user" && (
                <div className="shrink-0 mt-1 rounded-full bg-[#1677ff] p-1.5">
                  <User className="h-4 w-4 text-white" />
                </div>
              )}
            </div>
          ))}
          {!messagesLoading && !messagesError && loading && (
            <div className="flex justify-start gap-2">
              <div className="shrink-0 mt-1 rounded-full bg-[#f5f5f5] dark:bg-muted p-1.5">
                <Bot className="h-4 w-4 text-muted-foreground" />
              </div>
              <div className="rounded-2xl rounded-bl-md bg-[#f5f5f5] dark:bg-muted px-4 py-2.5 text-sm text-muted-foreground flex flex-col gap-1">
                <div className="flex items-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin shrink-0" />
                  <span>思考中...</span>
                </div>
                {slowGenHint ? (
                  <p className="text-xs text-muted-foreground/90 pl-6">
                    模型仍在生成中，可继续等待或点「取消」。若长时间无响应，多为 Ollama
                    生成较慢；轻薄本可尝试更小模型或改用更明确的业务指令。
                  </p>
                ) : null}
              </div>
            </div>
          )}
          <div ref={listEndRef} />
        </div>
      </div>

      <form
        onSubmit={handleSubmit}
        className={cn(
          "border-t border-border shrink-0 bg-background px-3 py-3 md:px-6 md:py-4",
          (mode === "widget" || isMobile) && "sticky bottom-0"
        )}
        style={{ paddingBottom: `calc(max(0.75rem, env(safe-area-inset-bottom)) + ${keyboardInset}px)` }}
      >
        <div className="mx-auto flex w-full max-w-6xl gap-2">
          <Input
            ref={inputRef as React.RefObject<HTMLInputElement>}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="输入消息..."
            disabled={loading}
            className="flex-1"
          />
          {loading && onCancelPending ? (
            <Button
              type="button"
              variant="outline"
              className="h-10 shrink-0"
              onClick={() => onCancelPending()}
            >
              取消
            </Button>
          ) : null}
          <Button type="submit" size="icon" className="h-10 w-10" disabled={loading || !inputValue.trim()}>
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
            <span className="sr-only">发送</span>
          </Button>
        </div>
      </form>
    </div>
  );
}
