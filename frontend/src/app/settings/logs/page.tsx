"use client";

import { useState, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Loader2,
  RefreshCw,
  Copy,
  ChevronDown,
  ChevronRight,
  AlertTriangle,
  MessageSquareText,
  Bug,
} from "lucide-react";
import { toast } from "sonner";
import { aiConfigApi, logsApi, adminApi, type AiChatResponse, type ChatRecord, type SystemLog } from "@/lib/apiClient";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { formatLocalDateTime } from "@/lib/time";

function formatTs(ts: string | undefined | null): string {
  if (!ts) return "-";
  return formatLocalDateTime(ts);
}

function hasNonEmptyToolCalls(toolCalls: unknown): boolean {
  if (toolCalls == null) return false;
  if (Array.isArray(toolCalls)) return toolCalls.length > 0;
  if (typeof toolCalls === "string")
    return toolCalls.trim().length > 0 && toolCalls.trim() !== "{}" && toolCalls.trim() !== "[]";
  if (typeof toolCalls === "object") return Object.keys(toolCalls as Record<string, unknown>).length > 0;
  return true;
}

function formatJsonForDisplay(value: unknown): string {
  if (value == null) return "（无）";
  if (typeof value === "string") {
    const t = value.trim();
    if (!t) return "（无）";
    try {
      return JSON.stringify(JSON.parse(t), null, 2);
    } catch {
      return value;
    }
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

async function copyToClipboard(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success("已复制到剪贴板");
  } catch {
    toast.error("复制失败（浏览器权限限制）");
  }
}

export default function LogsPage() {
  const queryClient = useQueryClient();
  const [logSearch, setLogSearch] = useState("");
  const [moduleFilter, setModuleFilter] = useState("");
  const [channelFilter, setChannelFilter] = useState<"all" | "web" | "feishu">("all");
  const [userFilter, setUserFilter] = useState<number | "">("");
  const [chatPage, setChatPage] = useState(1);
  const [sysPage, setSysPage] = useState(1);
  const [expandedChatIds, setExpandedChatIds] = useState<Set<number>>(new Set());
  const [selectedSystemLog, setSelectedSystemLog] = useState<SystemLog | null>(null);
  const [regenLoadingId, setRegenLoadingId] = useState<number | null>(null);
  const [regenResult, setRegenResult] = useState<{
    record: ChatRecord;
    response: AiChatResponse;
  } | null>(null);
  const pageSize = 20;

  const { data: userOptions = [] } = useQuery({
    queryKey: ["logs", "users"],
    queryFn: async () => {
      const res = await adminApi.listUsers(null, { page: 1, page_size: 200 });
      const items = (res.items as any[]) || [];
      return items.map((u) => ({
        id: Number(u.id),
        username: String(u.username ?? ""),
        display_name: u.display_name != null ? String(u.display_name) : null,
      }));
    },
    staleTime: 5 * 60 * 1000,
  });

  const { data: chatLogs, isLoading: chatLoading } = useQuery({
    queryKey: ["logs", "chat", logSearch, channelFilter, userFilter, chatPage, pageSize],
    queryFn: () =>
      logsApi.listChat({
        q: logSearch || undefined,
        channel: channelFilter === "all" ? undefined : channelFilter,
        user_id: typeof userFilter === "number" ? userFilter : undefined,
        page: chatPage,
        page_size: pageSize,
      }),
  });

  const { data: systemLogs, isLoading: sysLoading } = useQuery({
    queryKey: ["logs", "system", moduleFilter, userFilter, sysPage, pageSize],
    queryFn: () =>
      logsApi.listSystem({
        module: moduleFilter || undefined,
        user_id: typeof userFilter === "number" ? userFilter : undefined,
        page: sysPage,
        page_size: pageSize,
      }),
  });

  useEffect(() => {
    setChatPage(1);
    setSysPage(1);
  }, [logSearch, moduleFilter, channelFilter, userFilter]);

  const filteredSystemItems = (systemLogs?.items ?? []).filter((x) => {
    const q = logSearch.trim().toLowerCase();
    if (!q) return true;
    return (
      x.message?.toLowerCase().includes(q) ||
      x.module?.toLowerCase().includes(q) ||
      (x.stack_trace || "").toLowerCase().includes(q)
    );
  });

  const handleReExecute = async (record: ChatRecord) => {
    const userText = (record.user_message || "").trim();
    if (!userText) {
      toast.error("该条记录的 user_message 为空，无法重新执行");
      return;
    }
    setRegenLoadingId(record.id);
    try {
      const res = await aiConfigApi.chat({ messages: [{ role: "user", content: userText }] });
      setRegenResult({ record, response: res });
      await queryClient.invalidateQueries({ queryKey: ["logs", "chat"] });
      toast.success("已重新执行（结果已打开）");
    } catch (e) {
      const raw = e instanceof Error ? e.message : String(e);
      toast.error(raw || "重新执行失败");
    } finally {
      setRegenLoadingId(null);
    }
  };

  return (
    <div className="mx-auto max-w-5xl">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-muted-foreground" />
            日志与审计
          </CardTitle>
          <CardDescription>
            查看 AI 对话记录与系统运行日志，支持搜索、复制与手动刷新。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex-1">
              <Input
                value={logSearch}
                onChange={(e) => setLogSearch(e.target.value)}
                placeholder="搜索日志内容（支持对话与运行日志）…"
              />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <select
                className="h-10 rounded-md border border-input bg-background px-3 text-sm"
                value={channelFilter}
                onChange={(e) => setChannelFilter(e.target.value as "all" | "web" | "feishu")}
                title="聊天来源"
              >
                <option value="all">全部来源</option>
                <option value="web">Web</option>
                <option value="feishu">Feishu</option>
              </select>
              <select
                className="h-10 rounded-md border border-input bg-background px-3 text-sm"
                value={moduleFilter}
                onChange={(e) => setModuleFilter(e.target.value)}
                title="系统模块"
              >
                <option value="">全部模块</option>
                <option value="feishu.webhook">feishu.webhook</option>
                <option value="feishu.bot">feishu.bot</option>
                <option value="feishu.token">feishu.token</option>
              </select>
              <select
                className="h-10 rounded-md border border-input bg-background px-3 text-sm min-w-[180px]"
                value={userFilter === "" ? "" : String(userFilter)}
                onChange={(e) => {
                  const v = e.target.value;
                  setUserFilter(v ? Number(v) : "");
                }}
                title="按用户筛选"
              >
                <option value="">全部用户</option>
                {userOptions.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.display_name || u.username}（{u.username} / {u.id}）
                  </option>
                ))}
              </select>
            </div>
            <Button
              type="button"
              variant="outline"
              onClick={async () => {
                await queryClient.invalidateQueries({ queryKey: ["logs"] });
                toast.success("已刷新日志");
              }}
            >
              <RefreshCw className="mr-2 h-4 w-4" />
              刷新
            </Button>
          </div>

          <Tabs defaultValue="chat">
            <TabsList>
              <TabsTrigger value="chat">
                <MessageSquareText className="mr-2 h-4 w-4" />
                对话记录
              </TabsTrigger>
              <TabsTrigger value="system">
                <Bug className="mr-2 h-4 w-4" />
                运行日志
              </TabsTrigger>
            </TabsList>

            <TabsContent value="chat">
              {chatLoading ? (
                <p className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  加载中…
                </p>
              ) : (
                <div className="space-y-3">
                  {(chatLogs?.items ?? []).length === 0 ? (
                    <p className="text-sm text-muted-foreground">暂无对话记录</p>
                  ) : (
                    <div className="space-y-3">
                      {(chatLogs?.items ?? []).map((r: ChatRecord) => {
                        const expanded = expandedChatIds.has(r.id);
                        const missingSummary =
                          (!r.ai_response || !r.ai_response.trim()) && hasNonEmptyToolCalls(r.tool_calls);
                        return (
                          <div key={r.id} className="relative pl-6">
                            <div className="absolute left-2 top-2 h-2 w-2 rounded-full bg-muted-foreground" />
                            <div className="absolute left-[0.55rem] top-4 bottom-0 w-px bg-border" />
                            <div className="rounded-lg border border-border bg-background p-4">
                              <div className="flex items-start justify-between gap-3">
                                <div className="min-w-0">
                                  <p className="text-xs text-muted-foreground">{formatTs(r.timestamp)}</p>
                                  <p className="mt-0.5 text-[11px] text-muted-foreground">
                                    channel={r.channel || "web"}
                                    {r.external_user_id ? ` · user=${r.external_user_id}` : ""}
                                    {r.external_chat_id ? ` · chat=${r.external_chat_id}` : ""}
                                    {r.source_conversation_id ? ` · conv=${r.source_conversation_id}` : ""}
                                    {r.external_message_id ? ` · msg=${r.external_message_id}` : ""}
                                  </p>
                                  <p className="mt-1 text-sm font-medium break-words">
                                    {r.user_message || "（空）"}
                                  </p>
                                </div>
                                <div className="flex items-center gap-2 shrink-0">
                                  <Button
                                    type="button"
                                    variant="outline"
                                    size="sm"
                                    disabled={regenLoadingId === r.id}
                                    onClick={() => handleReExecute(r)}
                                    title="重新执行（将本条 user_message 重新发送给 AI）"
                                    aria-label="重新执行"
                                  >
                                    {regenLoadingId === r.id ? (
                                      <>
                                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                                        重新执行
                                      </>
                                    ) : (
                                      <>
                                        <RefreshCw className="mr-2 h-4 w-4" />
                                        重新执行
                                      </>
                                    )}
                                  </Button>
                                  <Button
                                    type="button"
                                    variant="ghost"
                                    size="icon"
                                    onClick={() => copyToClipboard(JSON.stringify(r, null, 2))}
                                    title="复制"
                                    aria-label="复制"
                                  >
                                    <Copy className="h-4 w-4" />
                                  </Button>
                                  <Button
                                    type="button"
                                    variant="ghost"
                                    size="icon"
                                    onClick={() => {
                                      setExpandedChatIds((prev) => {
                                        const next = new Set(prev);
                                        if (next.has(r.id)) next.delete(r.id);
                                        else next.add(r.id);
                                        return next;
                                      });
                                    }}
                                    title={expanded ? "收起" : "展开"}
                                    aria-label={expanded ? "收起" : "展开"}
                                  >
                                    {expanded ? (
                                      <ChevronDown className="h-4 w-4" />
                                    ) : (
                                      <ChevronRight className="h-4 w-4" />
                                    )}
                                  </Button>
                                </div>
                              </div>

                              {expanded && (
                                <div className="mt-3 space-y-3">
                                  <div>
                                    <p className="text-xs font-semibold text-muted-foreground">AI 回复</p>
                                    {missingSummary && (
                                      <div
                                        className="mt-2 flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100"
                                        role="alert"
                                      >
                                        <AlertTriangle className="h-4 w-4 shrink-0" />
                                        <span className="font-medium">⚠️ 模型未生成总结回复</span>
                                        <span className="text-amber-800/90 dark:text-amber-200/90">
                                          （仅返回了 tool_calls）
                                        </span>
                                      </div>
                                    )}
                                    <p className="mt-1 text-sm whitespace-pre-wrap break-words">
                                      {r.ai_response || "（空）"}
                                    </p>
                                  </div>
                                  <div>
                                    <p className="text-xs font-semibold text-muted-foreground">Tool Calls</p>
                                    <pre className="mt-1 max-h-64 overflow-auto rounded-md border border-border bg-muted/30 p-3 text-[11px] font-mono leading-relaxed whitespace-pre">
                                      {formatJsonForDisplay(r.tool_calls)}
                                    </pre>
                                  </div>
                                </div>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}

                  <div className="flex items-center justify-between pt-2">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={chatPage <= 1}
                      onClick={() => setChatPage((p) => Math.max(1, p - 1))}
                    >
                      上一页
                    </Button>
                    <span className="text-xs text-muted-foreground">
                      第 {chatLogs?.page ?? chatPage} 页 / 共{" "}
                      {Math.max(1, Math.ceil((chatLogs?.total ?? 0) / pageSize))} 页
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={
                        (chatLogs?.page ?? chatPage) >= Math.ceil((chatLogs?.total ?? 0) / pageSize)
                      }
                      onClick={() => setChatPage((p) => p + 1)}
                    >
                      下一页
                    </Button>
                  </div>
                </div>
              )}
            </TabsContent>

            <TabsContent value="system">
              {sysLoading ? (
                <p className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  加载中…
                </p>
              ) : (
                <div className="space-y-2">
                  {filteredSystemItems.length === 0 ? (
                    <p className="text-sm text-muted-foreground">暂无运行日志</p>
                  ) : (
                    filteredSystemItems.map((log) => {
                      const isError = (log.level || "").toUpperCase() === "ERROR";
                      return (
                        <div
                          key={log.id}
                          role="button"
                          tabIndex={0}
                          onClick={() => setSelectedSystemLog(log)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") setSelectedSystemLog(log);
                          }}
                          className={cn(
                            "flex items-start justify-between gap-3 rounded-lg border border-border p-4 transition-colors hover:bg-muted/30",
                            isError &&
                              "border-red-200 bg-red-50/60 hover:bg-red-50 dark:border-red-900 dark:bg-red-950/30"
                          )}
                        >
                          <div className="min-w-0">
                            <p
                              className={cn(
                                "text-xs text-muted-foreground",
                                isError && "text-red-700 dark:text-red-400"
                              )}
                            >
                              {formatTs(log.timestamp)} · {log.module}
                            </p>
                            <p
                              className={cn(
                                "mt-1 text-sm break-words",
                                isError && "text-red-900 dark:text-red-200"
                              )}
                            >
                              {log.message}
                            </p>
                          </div>
                          <div className="flex items-center gap-2 shrink-0">
                            <span
                              className={cn(
                                "rounded px-2 py-0.5 text-xs font-medium",
                                isError
                                  ? "bg-red-100 text-red-800 dark:bg-red-950/40 dark:text-red-200"
                                  : "bg-muted text-muted-foreground"
                              )}
                            >
                              {log.level}
                            </span>
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              onClick={(e) => {
                                e.stopPropagation();
                                copyToClipboard(JSON.stringify(log, null, 2));
                              }}
                              title="复制"
                              aria-label="复制"
                            >
                              <Copy className="h-4 w-4" />
                            </Button>
                          </div>
                        </div>
                      );
                    })
                  )}

                  <div className="flex items-center justify-between pt-2">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={sysPage <= 1}
                      onClick={() => setSysPage((p) => Math.max(1, p - 1))}
                    >
                      上一页
                    </Button>
                    <span className="text-xs text-muted-foreground">
                      第 {systemLogs?.page ?? sysPage} 页 / 共{" "}
                      {Math.max(1, Math.ceil((systemLogs?.total ?? 0) / pageSize))} 页
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={
                        (systemLogs?.page ?? sysPage) >=
                        Math.ceil((systemLogs?.total ?? 0) / pageSize)
                      }
                      onClick={() => setSysPage((p) => p + 1)}
                    >
                      下一页
                    </Button>
                  </div>
                </div>
              )}
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>

      <Dialog open={!!selectedSystemLog} onOpenChange={(o) => !o && setSelectedSystemLog(null)}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>错误详情</DialogTitle>
            <DialogDescription>
              {selectedSystemLog
                ? `${selectedSystemLog.module} · ${formatTs(selectedSystemLog.timestamp)}`
                : ""}
            </DialogDescription>
          </DialogHeader>
          {selectedSystemLog && (
            <div className="space-y-3">
              <p className="text-sm font-medium break-words">{selectedSystemLog.message}</p>
              <pre className="max-h-[60vh] overflow-auto rounded-md border border-border bg-muted/30 p-3 text-xs whitespace-pre-wrap">
                {selectedSystemLog.stack_trace || "（无堆栈信息）"}
              </pre>
              <div className="flex justify-end">
                <Button
                  variant="outline"
                  onClick={() =>
                    copyToClipboard(selectedSystemLog.stack_trace || selectedSystemLog.message)
                  }
                >
                  <Copy className="mr-2 h-4 w-4" />
                  复制堆栈/信息
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={!!regenResult} onOpenChange={(o) => !o && setRegenResult(null)}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>重新执行结果</DialogTitle>
            <DialogDescription>
              {regenResult
                ? `原始时间：${formatTs(regenResult.record.timestamp)} · 记录 #${regenResult.record.id}`
                : ""}
            </DialogDescription>
          </DialogHeader>
          {regenResult && (
            <div className="space-y-4">
              <div className="space-y-2">
                <p className="text-xs font-semibold text-muted-foreground">User Message</p>
                <pre className="max-h-40 overflow-auto rounded-md border border-border bg-muted/30 p-3 text-[11px] font-mono leading-relaxed whitespace-pre-wrap">
                  {regenResult.record.user_message || "（空）"}
                </pre>
              </div>
              <div className="space-y-2">
                <p className="text-xs font-semibold text-muted-foreground">AI Response</p>
                <p className="text-sm whitespace-pre-wrap break-words">
                  {regenResult.response?.message?.content?.trim() || "（空）"}
                </p>
              </div>
              <div className="space-y-2">
                <p className="text-xs font-semibold text-muted-foreground">Tool Calls（本次）</p>
                <pre className="max-h-64 overflow-auto rounded-md border border-border bg-muted/30 p-3 text-[11px] font-mono leading-relaxed whitespace-pre">
                  {formatJsonForDisplay(regenResult.response?.message?.tool_calls)}
                </pre>
              </div>
              <div className="space-y-2">
                <p className="text-xs font-semibold text-muted-foreground">
                  Execution Results（本次）
                </p>
                <pre className="max-h-64 overflow-auto rounded-md border border-border bg-muted/30 p-3 text-[11px] font-mono leading-relaxed whitespace-pre">
                  {formatJsonForDisplay(regenResult.response?.execution_results)}
                </pre>
              </div>
              <div className="flex justify-end gap-2">
                <Button
                  variant="outline"
                  onClick={() =>
                    copyToClipboard(JSON.stringify(regenResult.response, null, 2))
                  }
                >
                  <Copy className="mr-2 h-4 w-4" />
                  复制本次结果
                </Button>
                <Button variant="outline" onClick={() => setRegenResult(null)}>
                  关闭
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
