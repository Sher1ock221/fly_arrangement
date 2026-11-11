"use client";

import { useState, useRef, useEffect } from "react";
import { useQueryClient, useQuery } from "@tanstack/react-query";
import {
  MessageCircle,
  Send,
  Minimize2,
  User,
  Bot,
  Loader2,
  RefreshCw,
  AlertCircle,
  AlertTriangle,
} from "lucide-react";
import { toast } from "sonner";
import ReactMarkdown from "react-markdown";
import { aiConfigApi, ApiRequestError, formatApiErrorUserMessage } from "@/lib/apiClient";
import { queryKeys } from "@/lib/queryKeys";
import type { AIMessage, AiChatDiagnostic, ExecutionResultItem } from "@/types/ai";
import { formatShortcutBadgeLabel } from "@/lib/shortcutDisplay";
import { normalizeExecutionResults, processExecutionResults } from "@/lib/aiExecutionProcessor";
import { ExecutionSteps } from "@/components/chat/ExecutionSteps";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

interface ChatMessage extends AIMessage {
  executionSummary?: string | string[];
  toolCallWarning?: string;
  isRefusal?: boolean;
}

function isVagueProcessedReply(content: string): boolean {
  const t = (content || "").trim();
  if (!t) return false;
  return (
    t === "已处理。" ||
    t === "已处理" ||
    t === "好的" ||
    t === "收到" ||
    t === "好的，已处理。" ||
    t === "好的，已处理" ||
    t === "已完成。" ||
    t === "已完成"
  );
}

function isRefusalReply(content: string): boolean {
  const t = (content || "").trim();
  if (!t) return false;
  return /无法理解|暂时无法执行|我暂时无法执行|超出.*范围|请提供更具体的信息/.test(t);
}

/** 从 execution_results 的 execution_summary 解析智能提示 */
function getSmartHints(results: ExecutionResultItem[]): string[] {
  const hints: string[] = [];
  const seen = new Set<string>();
  for (const r of results) {
    const summary = r.execution_summary;
    if (!summary || !r.success) continue;
    // 客户沟通记录归档
    const result = r.result as { customer_name?: string } | undefined;
    if (r.tool_name === "create_customer_interaction" && result?.customer_name) {
      const text = `已归档到客户 ${result.customer_name}`;
      if (!seen.has(text)) {
        seen.add(text);
        hints.push(text);
      }
    }
    // 负责人改为 XXX / 负责人已更新为 XXX
    const ownerMatch = summary.match(/负责人(?:已更新)?改为\s*([^，；。]+)/);
    if (ownerMatch) {
      const text = `✅ 负责人已更新为 ${ownerMatch[1].trim()}`;
      if (!seen.has(text)) {
        seen.add(text);
        hints.push(text);
      }
    }
    // 截止日期设定为 2026-03-07 或 已识别"明天"为 2026-03-07
    const dateSetMatch = summary.match(/截止日期设定为\s*(\d{4}-\d{2}-\d{2})/);
    if (dateSetMatch) {
      const text = `📅 已设置截止日期为 ${dateSetMatch[1]}`;
      if (!seen.has(text)) {
        seen.add(text);
        hints.push(text);
      }
    }
    const dateInferMatch = summary.match(/已识别[「"']([^」"']+)[」"']为\s*(\d{4}-\d{2}-\d{2})/);
    if (dateInferMatch) {
      const text = `📅 已识别「${dateInferMatch[1]}」为 ${dateInferMatch[2]}`;
      if (!seen.has(text)) {
        seen.add(text);
        hints.push(text);
      }
    }
  }
  return hints;
}

interface AIChatWindowProps {
  defaultOpen?: boolean;
  onToggle?: (open: boolean) => void;
}

export function AIChatWindow({ defaultOpen = false, onToggle }: AIChatWindowProps) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(defaultOpen);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [slowGenHint, setSlowGenHint] = useState(false);
  const listEndRef = useRef<HTMLDivElement>(null);
  const chatAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    listEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (!loading) {
      setSlowGenHint(false);
      return;
    }
    const t = window.setTimeout(() => setSlowGenHint(true), 30000);
    return () => window.clearTimeout(t);
  }, [loading]);

  const toggleOpen = () => {
    const next = !open;
    setOpen(next);
    onToggle?.(next);
  };

  const handleSend = async () => {
    const text = input.trim();
    if (!text || loading) return;

    const userMsg: ChatMessage = {
      id: `u-${Date.now()}`,
      role: "user",
      content: text,
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);
    const ac = new AbortController();
    chatAbortRef.current = ac;

    try {
      const history = messages.map((m) => ({ id: m.id, role: m.role, content: m.content }));
      const combined = [...history, { id: userMsg.id, role: "user" as const, content: text }];
      const API_CHAT_MESSAGE_CAP = 12;
      const payload =
        combined.length > API_CHAT_MESSAGE_CAP
          ? combined.slice(-API_CHAT_MESSAGE_CAP)
          : combined;
      const res = await aiConfigApi.chat(
        {
          messages: payload.map((m) => ({ role: m.role, content: m.content })),
        },
        { signal: ac.signal }
      );

      const executionResults = normalizeExecutionResults(res.execution_results ?? []);
      const { executionSummary: executionSummaryList, executionErrors } = processExecutionResults(
        executionResults,
        queryClient
      );

      const contentFromApi =
        (typeof (res as { content?: string }).content === "string"
          ? (res as { content: string }).content
          : null) ??
        (typeof res.message === "object" && res.message && "content" in res.message
          ? (res.message.content as string) ?? ""
          : "");
      const assistantContent =
        contentFromApi || executionSummaryList?.join("\n") || "任务已完成";

      const smartHints = getSmartHints(executionResults as ExecutionResultItem[]);
      const isSummaryReply = executionResults.some(
        (r) => r.success === true && r.tool_name === "list_all_projects"
      );
      const toolCallWarning =
        executionResults.length === 0 && isVagueProcessedReply(assistantContent)
          ? "AI 未能成功触发操作，请尝试更明确的指令"
          : undefined;
      const refusal = isRefusalReply(assistantContent);

      const diag = (res as { diagnostic?: AiChatDiagnostic }).diagnostic;
      const assistantMsg: ChatMessage = {
        id: `a-${Date.now()}`,
        role: "assistant",
        content: assistantContent,
        executionSummary: executionSummaryList.length > 0 ? executionSummaryList : undefined,
        executionErrors: executionErrors.length > 0 ? executionErrors : undefined,
        execution_results: executionResults.length > 0 ? executionResults : undefined,
        smartHints: smartHints.length > 0 ? smartHints : undefined,
        isSummaryReply,
        toolCallWarning,
        isRefusal: refusal,
        ...(diag && typeof diag === "object" ? { ai_debug: diag } : {}),
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (e) {
      if (e instanceof ApiRequestError && e.status === 499) {
        setMessages((prev) => [
          ...prev,
          { id: `a-${Date.now()}`, role: "assistant", content: "已取消本次请求。" },
        ]);
        return;
      }
      const errMsg =
        e instanceof ApiRequestError
          ? formatApiErrorUserMessage(e.responseText)
          : e instanceof Error
            ? e.message
            : "请求失败";
      let partialAppend = "";
      if (e instanceof ApiRequestError) {
        try {
          const parsed = JSON.parse(e.responseText) as {
            detail?:
              | string
              | { partial_results?: Array<{ tool_name?: string; tool?: string; success?: boolean; error?: string }> };
          };
          const d = parsed?.detail;
          if (d && typeof d === "object" && Array.isArray(d.partial_results) && d.partial_results.length) {
            const lines = d.partial_results.map((r) => {
              const t = typeof r.tool_name === "string" ? r.tool_name : typeof r.tool === "string" ? r.tool : "?";
              const ok = r.success === true ? "成功" : "失败";
              const er = typeof r.error === "string" && r.error ? `：${r.error}` : "";
              return `- ${t}：${ok}${er}`;
            });
            partialAppend = `\n\n已完成的步骤：\n${lines.join("\n")}`;
          }
        } catch {
          // ignore
        }
      }
      setMessages((prev) => [
        ...prev,
        { id: `a-${Date.now()}`, role: "assistant", content: `错误：${errMsg}${partialAppend}` },
      ]);
    } finally {
      chatAbortRef.current = null;
      setLoading(false);
    }
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={toggleOpen}
        className={cn(
          "fixed right-6 bottom-6 z-40 flex h-14 w-14 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-lg transition hover:scale-105",
          "focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
        )}
        title="打开 AI 助手"
        aria-label="打开 AI 助手"
      >
        <MessageCircle className="h-6 w-6" />
      </button>
    );
  }

  return (
    <div className="fixed right-6 bottom-6 z-40 flex w-[380px] flex-col overflow-hidden rounded-xl border border-border bg-card shadow-xl">
      <div className="flex items-center justify-between border-b border-border bg-muted/50 px-3 py-2">
        <span className="flex items-center gap-2 text-sm font-medium">
          <Bot className="h-4 w-4 text-primary" />
          AI 助手
        </span>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={toggleOpen}
          title="最小化"
          aria-label="最小化"
        >
          <Minimize2 className="h-4 w-4" />
        </Button>
      </div>
      <div className="flex max-h-[360px] min-h-[280px] flex-1 flex-col">
        <div className="flex-1 overflow-y-auto p-3 space-y-3">
          {messages.length === 0 && (
            <p className="text-center text-muted-foreground text-sm py-6">
              输入指令修改项目或客户，例如：「把项目 1 的负责人改为张三」
            </p>
          )}
          {messages.map((m, index) => (
            <div
              key={m.id ?? `msg-${index}`}
              className={cn(
                "flex gap-2",
                m.role === "user" ? "justify-end" : "justify-start"
              )}
            >
              <div
                className={cn(
                  "flex max-w-[85%] flex-col gap-1",
                  m.role === "user" ? "items-end" : "items-start"
                )}
              >
                <div
                  className={cn(
                    "flex items-start gap-2 rounded-lg px-3 py-2",
                    m.role === "user"
                      ? "bg-primary text-primary-foreground"
                      : m.isRefusal
                        ? "bg-orange-50 text-foreground border border-orange-200 dark:bg-orange-950/30 dark:border-orange-900"
                        : "bg-muted"
                  )}
                >
                  {m.role === "assistant" && (
                    <Bot className="h-4 w-4 shrink-0 mt-0.5 text-muted-foreground" />
                  )}
                  <div className="min-w-0 flex-1">
                    {m.role === "assistant" ? (
                      <div className="text-sm max-w-none break-words [&_ul]:list-disc [&_ul]:pl-4 [&_ol]:list-decimal [&_ol]:pl-4 [&_strong]:font-semibold [&_p]:my-1 [&_li]:my-0.5">
                        <ReactMarkdown>
                          {!m.content && m.executionSummary
                            ? Array.isArray(m.executionSummary)
                              ? m.executionSummary.join("\n")
                              : m.executionSummary
                            : m.content}
                        </ReactMarkdown>
                      </div>
                    ) : (
                      <p className="text-sm whitespace-pre-wrap break-words">{m.content}</p>
                    )}
                    {m.executionErrors && m.executionErrors.length > 0 && (
                      <div className="mt-2 flex items-start gap-1.5 rounded bg-destructive/10 px-2 py-1.5 text-xs text-destructive">
                        <AlertCircle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                        <span>
                          {m.executionErrors.length === 1
                            ? `执行失败：${m.executionErrors[0]}`
                            : `执行失败：\n${m.executionErrors.map((e, i) => `${i + 1}. ${e}`).join("\n")}`}
                        </span>
                      </div>
                    )}
                  </div>
                  {m.role === "user" && (
                    <User className="h-4 w-4 shrink-0 mt-0.5 opacity-80" />
                  )}
                </div>
                {m.role === "assistant" && m.ai_debug?.shortcut && (
                  <div className="mt-1 text-xs text-emerald-800 dark:text-emerald-300/90">
                    本地快速处理：{formatShortcutBadgeLabel(String(m.ai_debug.shortcut))}
                  </div>
                )}
                {m.role === "assistant" && m.execution_results && m.execution_results.length > 0 && (
                  <ExecutionSteps steps={m.execution_results} />
                )}
                {m.role === "assistant" && m.ai_debug && (
                  <details className="mt-1 rounded border border-border/60 bg-muted/30 px-2 py-1 text-[11px] text-muted-foreground max-w-full">
                    <summary className="cursor-pointer select-none">本轮请求诊断（耗时）</summary>
                    <div className="mt-1 space-y-0.5 font-mono break-all">
                      {m.ai_debug.request_id && <div>request_id: {m.ai_debug.request_id}</div>}
                      {m.ai_debug.shortcut && <div>shortcut: {m.ai_debug.shortcut}</div>}
                      {m.ai_debug.detected_intent != null && (
                        <div>intent: {String(m.ai_debug.detected_intent)}</div>
                      )}
                      {m.ai_debug.use_tools != null && <div>use_tools: {String(m.ai_debug.use_tools)}</div>}
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
                {m.executionSummary && (
                  <div className="flex flex-col gap-1 mt-1">
                    {Array.isArray(m.executionSummary)
                      ? m.executionSummary.map((line, i) => (
                          <span key={i} className="flex items-center gap-1 text-xs text-muted-foreground">
                            <RefreshCw className="h-3 w-3 shrink-0" />
                            {line.startsWith("✅") ? line : `✅ ${line}`}
                          </span>
                        ))
                      : (
                          <span className="flex items-center gap-1 text-xs text-muted-foreground">
                            <RefreshCw className="h-3 w-3" />
                            {m.executionSummary}
                          </span>
                        )}
                  </div>
                )}
                {m.toolCallWarning && (
                  <span className="mt-1 flex items-center gap-1 text-xs text-amber-700 dark:text-amber-400">
                    <AlertTriangle className="h-3.5 w-3.5" />
                    {m.toolCallWarning}
                  </span>
                )}
                {m.smartHints && m.smartHints.length > 0 && (
                  <div className="flex flex-col gap-1 mt-1">
                    {m.smartHints.map((hint, i) => (
                      <span key={i} className="text-xs text-green-700 dark:text-green-400">
                        {hint}
                      </span>
                    ))}
                  </div>
                )}
                {m.isSummaryReply && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="mt-2 gap-1.5"
                  onClick={() => {
                    queryClient.invalidateQueries({ queryKey: queryKeys.projects() });
                    toast.success("项目列表已刷新");
                  }}
                >
                    <RefreshCw className="h-3.5 w-3.5" />
                    刷新列表
                  </Button>
                )}
              </div>
            </div>
          ))}
          {loading && (
            <>
              <div className="flex justify-start items-center gap-1.5 text-xs text-muted-foreground px-1">
                <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0" />
                <span>AI 正在思考...</span>
              </div>
              <div className="flex justify-start gap-2">
                <div className="flex flex-col gap-1 rounded-lg bg-muted px-3 py-2">
                  <div className="flex items-center gap-2">
                    <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                    <span className="text-sm text-muted-foreground">AI 正在思考...</span>
                  </div>
                  {slowGenHint ? (
                    <p className="text-xs text-muted-foreground pl-6">
                      若超过 30 秒仍在等待，多为 Ollama 生成较慢；轻薄本可尝试更小模型或改用更明确的业务指令。
                    </p>
                  ) : null}
                </div>
              </div>
            </>
          )}
          <div ref={listEndRef} />
        </div>
        <div className="border-t border-border p-2">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSend();
            }}
            className="flex gap-2"
          >
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="输入指令…"
              className="flex-1"
              disabled={loading}
            />
            {loading ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="shrink-0"
                onClick={() => chatAbortRef.current?.abort()}
              >
                取消
              </Button>
            ) : null}
            <Button type="submit" size="icon" disabled={loading || !input.trim()}>
              <Send className="h-4 w-4" />
              <span className="sr-only">发送</span>
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}
