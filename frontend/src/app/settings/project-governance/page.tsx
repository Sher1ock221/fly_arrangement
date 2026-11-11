"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Clock, RefreshCw, ScanSearch } from "lucide-react";
import { toast } from "sonner";

import { adminApi, getStoredToken } from "@/lib/apiClient";
import { queryKeys } from "@/lib/queryKeys";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

const METRICS: Array<{ key: string; label: string; desc: string }> = [
  { key: "legacy_owner_count", label: "Legacy 负责人数量", desc: "旧负责人文本待治理数量" },
  { key: "legacy_member_count", label: "Legacy 共享成员数量", desc: "待清理旧成员总量" },
  { key: "missing_initiator_count", label: "发起人缺失项目数", desc: "initiator_user_id 为空项目" },
  { key: "missing_owner_count", label: "负责人缺失项目数", desc: "owner_user_id 为空项目" },
  { key: "initiator_owner_conflict_count", label: "发起/负责人异常数", desc: "发起人与负责人关系异常项目" },
  { key: "dirty_collaborator_relation_count", label: "协作者脏关系数", desc: "重复/失效/冲突协作者关系" },
  {
    key: "visibility_mismatch_count",
    label: "可见性异常数",
    desc: "repair queue 中 pending/running 的 visibility_mismatch（与下方队列一致）",
  },
  {
    key: "manual_repair_queue_count",
    label: "队列活跃项总数",
    desc: "repair queue 中 pending + running（全部 issue_type）",
  },
  {
    key: "overdue_repair_queue_count",
    label: "超时处理中数量",
    desc: "running 且已开始超过 24h（与列表 SLA 字段一致）",
  },
];

const ISSUE_TYPES = [
  { value: "", label: "全部类型" },
  { value: "visibility_mismatch", label: "visibility_mismatch" },
  { value: "missing_initiator", label: "missing_initiator" },
  { value: "missing_owner", label: "missing_owner" },
  { value: "legacy_owner_text", label: "legacy_owner_text" },
  { value: "dirty_collaborator_relation", label: "dirty_collaborator_relation" },
];

const STATUSES = [
  { value: "", label: "全部状态" },
  { value: "pending", label: "pending" },
  { value: "running", label: "running" },
  { value: "resolved", label: "resolved" },
  { value: "ignored", label: "ignored" },
  { value: "false_positive", label: "false_positive" },
  { value: "failed", label: "failed" },
];

const SEVERITIES = [
  { value: "", label: "全部严重度" },
  { value: "high", label: "high" },
  { value: "medium", label: "medium" },
  { value: "low", label: "low" },
];

const CAUSE_LABELS: Record<string, string> = {
  permission_logic_diverged: "权限链路分叉（偏逻辑/代码）",
  stale_relation_data: "关系数据陈旧或不一致（偏数据）",
  legacy_visibility_pollution: "历史可见性污染（待结合数据核对）",
  list_filter_diverged: "列表过滤与详情不一致（偏列表 SQL）",
  historical_data_gap: "历史数据缺口",
  incomplete_create_flow: "创建流不完整（如缺负责人）",
  legacy_data_not_migrated: "遗留数据未迁移",
  invalid_reference: "外键/引用失效",
};

const selectCls =
  "border-input bg-background flex h-9 min-w-[9rem] rounded-md border px-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

function statusBadgeVariant(s: string): "default" | "secondary" | "destructive" | "outline" {
  if (s === "pending" || s === "running") return "destructive";
  if (s === "resolved") return "secondary";
  return "outline";
}

type CloseAction = "resolved" | "ignored" | "false_positive";

export default function ProjectGovernancePage() {
  const token = getStoredToken();
  const qc = useQueryClient();
  const repairQueueSectionRef = useRef<HTMLDivElement | null>(null);
  const overdueEnterToastFiredRef = useRef(false);
  const [issueType, setIssueType] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [severityFilter, setSeverityFilter] = useState("");
  const [activeOnlyFilter, setActiveOnlyFilter] = useState(false);
  const [overdueOnlyFilter, setOverdueOnlyFilter] = useState(false);
  const [closeDialog, setCloseDialog] = useState<{ id: number; action: CloseAction } | null>(null);
  const [resolutionNote, setResolutionNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [startingId, setStartingId] = useState<number | null>(null);

  const queueQueryKey = useMemo(
    () =>
      queryKeys.projectGovernanceRepairQueue(
        issueType || undefined,
        statusFilter || undefined,
        severityFilter || undefined,
        activeOnlyFilter ? true : undefined,
        overdueOnlyFilter ? true : undefined
      ),
    [issueType, statusFilter, severityFilter, activeOnlyFilter, overdueOnlyFilter]
  );

  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: queryKeys.projectGovernanceSummary(),
    queryFn: () => adminApi.projectGovernanceSummary(token),
    enabled: !!token,
    refetchInterval: 30000,
  });

  const overdueCount = Number((data as { overdue_repair_queue_count?: number } | undefined)?.overdue_repair_queue_count ?? 0);
  const hasOverdue = overdueCount > 0;

  useEffect(() => {
    if (!token || isLoading || data == null) return;
    if (hasOverdue && !overdueEnterToastFiredRef.current) {
      overdueEnterToastFiredRef.current = true;
      toast.info(`当前有 ${overdueCount} 条超时处理中问题，请优先查看超时项`, { duration: 4800 });
    }
  }, [token, isLoading, data, hasOverdue, overdueCount]);

  const focusOverdueQueue = () => {
    setOverdueOnlyFilter(true);
    setActiveOnlyFilter(false);
    setStatusFilter("");
    window.requestAnimationFrame(() => {
      repairQueueSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  };

  const { data: queueData, isLoading: queueLoading } = useQuery({
    queryKey: queueQueryKey,
    queryFn: () =>
      adminApi.projectGovernanceRepairQueue(token, {
        issue_type: issueType || undefined,
        status: overdueOnlyFilter || activeOnlyFilter ? undefined : statusFilter || undefined,
        severity: severityFilter || undefined,
        active_only: overdueOnlyFilter ? undefined : activeOnlyFilter ? true : undefined,
        overdue_only: overdueOnlyFilter ? true : undefined,
      }),
    enabled: !!token,
  });

  const runScan = async () => {
    try {
      const r = await adminApi.runProjectGovernanceScan(token);
      const visNew = r.visibility_mismatch_new;
      const pairs = r.visibility_pairs_scanned;
      const extra =
        visNew != null && pairs != null
          ? `（可见性：扫描 ${pairs} 对用户-项目，新入队 ${visNew}）`
          : "";
      toast.success(`repair scanner 已完成识别并入队${extra}`);
      await qc.invalidateQueries({ queryKey: queryKeys.projectGovernanceSummary() });
      await qc.invalidateQueries({ queryKey: ["admin", "project-governance", "repair-queue"] });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "扫描失败");
    }
  };

  const resetFilters = () => {
    setIssueType("");
    setStatusFilter("");
    setSeverityFilter("");
    setActiveOnlyFilter(false);
    setOverdueOnlyFilter(false);
  };

  const submitStart = async (id: number) => {
    if (!token) return;
    setStartingId(id);
    try {
      await adminApi.startProjectRepairQueue(token, id);
      toast.success("已开始处理，状态已设为 running");
      await qc.invalidateQueries({ queryKey: queryKeys.projectGovernanceSummary() });
      await qc.invalidateQueries({ queryKey: ["admin", "project-governance", "repair-queue"] });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "操作失败");
    } finally {
      setStartingId(null);
    }
  };

  const openCloseDialog = (id: number, action: CloseAction) => {
    setResolutionNote("");
    setCloseDialog({ id, action });
  };

  const submitClose = async () => {
    if (!closeDialog || !token) return;
    setSubmitting(true);
    try {
      await adminApi.updateProjectRepairQueueStatus(token, closeDialog.id, {
        status: closeDialog.action,
        resolution_note: resolutionNote.trim() || undefined,
      });
      toast.success("状态已更新");
      setCloseDialog(null);
      await qc.invalidateQueries({ queryKey: queryKeys.projectGovernanceSummary() });
      await qc.invalidateQueries({ queryKey: ["admin", "project-governance", "repair-queue"] });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "更新失败");
    } finally {
      setSubmitting(false);
    }
  };

  const items = queueData?.items ?? [];
  const filterActive = !!(issueType || statusFilter || severityFilter || activeOnlyFilter || overdueOnlyFilter);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold">项目治理驾驶舱</h2>
          <p className="text-sm text-muted-foreground">健康度视图与 repair queue 运营（30s 自动刷新摘要）</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={() => void refetch()} disabled={isFetching}>
            <RefreshCw className="mr-1 h-4 w-4" />
            刷新
          </Button>
          <Button onClick={runScan}>
            <ScanSearch className="mr-1 h-4 w-4" />
            运行识别扫描
          </Button>
        </div>
      </div>

      {hasOverdue ? (
        <Alert
          className={cn(
            "border-orange-500/35 bg-orange-500/[0.07] dark:bg-orange-950/25",
            "text-foreground [&>svg]:text-orange-600 dark:[&>svg]:text-orange-400"
          )}
        >
          <Clock className="h-4 w-4" />
          <AlertDescription className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
            <p className="text-sm leading-snug">
              当前有 <span className="font-semibold tabular-nums">{overdueCount}</span> 条 repair queue
              处于超时处理中（running 已超过默认 24h SLA），建议优先处理。
            </p>
            <Button
              type="button"
              size="sm"
              variant={overdueOnlyFilter ? "secondary" : "default"}
              className="shrink-0 border-orange-500/40 bg-background hover:bg-orange-500/10"
              disabled={overdueOnlyFilter}
              onClick={focusOverdueQueue}
            >
              {overdueOnlyFilter ? "已定位到超时问题" : "查看超时问题"}
            </Button>
          </AlertDescription>
        </Alert>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {METRICS.map((m) => {
          const isOverdueCard = m.key === "overdue_repair_queue_count";
          const urgent = isOverdueCard && hasOverdue;
          return (
            <Card
              key={m.key}
              className={cn(
                urgent &&
                  "border-orange-500/45 bg-orange-500/[0.06] shadow-sm ring-1 ring-orange-500/20 dark:bg-orange-950/20"
              )}
            >
              <CardHeader className="pb-2">
                <div className="flex items-start justify-between gap-2">
                  <CardTitle className="text-sm">{m.label}</CardTitle>
                  {urgent ? (
                    <Badge
                      variant="outline"
                      className="shrink-0 border-orange-500/50 text-[10px] text-orange-800 dark:text-orange-300"
                    >
                      需优先处理
                    </Badge>
                  ) : null}
                </div>
                <CardDescription className="text-xs">{m.desc}</CardDescription>
              </CardHeader>
              <CardContent>
                <div
                  className={cn(
                    "text-2xl font-semibold tabular-nums",
                    urgent && "text-orange-800 dark:text-orange-200"
                  )}
                >
                  {isLoading ? "…" : String((data as Record<string, number> | undefined)?.[m.key] ?? 0)}
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <Card ref={repairQueueSectionRef}>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <AlertTriangle className="h-4 w-4" />
            Repair Queue
          </CardTitle>
          <CardDescription>
            running 超过 24h 视为 SLA 超时（列表高亮）；pending 可「开始处理」。关闭操作写审计日志。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">issue_type</Label>
              <select className={selectCls} value={issueType} onChange={(e) => setIssueType(e.target.value)}>
                {ISSUE_TYPES.map((o) => (
                  <option key={o.value || "all"} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">status</Label>
              <select
                className={selectCls}
                value={statusFilter}
                disabled={activeOnlyFilter || overdueOnlyFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
              >
                {STATUSES.map((o) => (
                  <option key={o.value || "all-s"} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">severity</Label>
              <select
                className={selectCls}
                value={severityFilter}
                onChange={(e) => setSeverityFilter(e.target.value)}
              >
                {SEVERITIES.map((o) => (
                  <option key={o.value || "all-sev"} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
            <label className="flex cursor-pointer items-center gap-2 text-sm text-muted-foreground">
              <input
                type="checkbox"
                className="rounded border-input"
                checked={activeOnlyFilter}
                disabled={overdueOnlyFilter}
                onChange={(e) => {
                  const v = e.target.checked;
                  setActiveOnlyFilter(v);
                  if (v) {
                    setStatusFilter("");
                    setOverdueOnlyFilter(false);
                  }
                }}
              />
              只看未结项（pending+running）
            </label>
            <label className="flex cursor-pointer items-center gap-2 text-sm text-muted-foreground">
              <input
                type="checkbox"
                className="rounded border-input"
                checked={overdueOnlyFilter}
                onChange={(e) => {
                  const v = e.target.checked;
                  setOverdueOnlyFilter(v);
                  if (v) {
                    setActiveOnlyFilter(false);
                    setStatusFilter("");
                  }
                }}
              />
              只看超时项（running 且 &gt;24h）
            </label>
            <Button type="button" variant="outline" size="sm" onClick={resetFilters}>
              重置筛选
            </Button>
          </div>

          {queueLoading ? (
            <p className="text-sm text-muted-foreground">加载中…</p>
          ) : !items.length ? (
            <p className="text-sm text-muted-foreground">
              {filterActive ? "当前筛选条件下无记录" : "暂无队列记录"}
            </p>
          ) : (
            <div className="max-h-[480px] overflow-auto rounded-md border">
              <table className="w-full text-left text-xs">
                <thead className="sticky top-0 bg-muted/80 backdrop-blur">
                  <tr className="border-b">
                    <th className="p-2 font-medium">issue</th>
                    <th className="p-2 font-medium">status</th>
                    <th className="p-2 font-medium">处理人</th>
                    <th className="p-2 font-medium">开始处理</th>
                    <th className="p-2 font-medium">处理时长</th>
                    <th className="p-2 font-medium">超时</th>
                    <th className="p-2 font-medium">超时时长</th>
                    <th className="p-2 font-medium">sev</th>
                    <th className="p-2 font-medium">target</th>
                    <th className="p-2 font-medium">suspected_cause</th>
                    <th className="p-2 font-medium">detected</th>
                    <th className="p-2 font-medium">摘要</th>
                    <th className="p-2 font-medium">备注</th>
                    <th className="p-2 font-medium">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {items.slice(0, 200).map((row) => {
                    const id = Number(row.id);
                    const st = String(row.status ?? "");
                    const active = st === "pending" || st === "running";
                    const isPending = st === "pending";
                    const isRunning = st === "running";
                    const isOverdue = row.is_overdue === true;
                    const runHours = row.running_duration_hours;
                    const overdueHours = row.overdue_hours;
                    const assigneeName = row.assigned_to_user_display_name;
                    const assigneeLabel =
                      assigneeName != null && String(assigneeName).length > 0
                        ? String(assigneeName)
                        : "未指派";
                    const cause = String(row.suspected_cause ?? "");
                    const causeZh = CAUSE_LABELS[cause] ?? cause;
                    const note = row.resolution_note != null ? String(row.resolution_note) : "";
                    return (
                      <tr
                        key={id}
                        className={cn(
                          "border-b border-border/60 align-top",
                          isRunning && isOverdue && "bg-orange-500/[0.12] dark:bg-orange-950/40"
                        )}
                      >
                        <td className="p-2 font-mono">{String(row.issue_type)}</td>
                        <td className="p-2">
                          <div className="flex flex-col gap-0.5">
                            <div className="flex flex-wrap items-center gap-1">
                              <Badge variant={statusBadgeVariant(st)} className="text-[10px] w-fit">
                                {st}
                              </Badge>
                              {isRunning && isOverdue ? (
                                <Badge
                                  variant="outline"
                                  className="border-orange-500/60 text-orange-700 dark:text-orange-400 text-[10px] px-1.5"
                                >
                                  处理中（超时）
                                </Badge>
                              ) : null}
                            </div>
                            {isRunning && !isOverdue ? (
                              <span className="text-[10px] text-muted-foreground">处理中</span>
                            ) : null}
                          </div>
                        </td>
                        <td className="p-2 max-w-[7rem] break-words text-muted-foreground">
                          <div className="flex flex-col gap-0.5">
                            <span>{assigneeLabel}</span>
                            {isRunning && isOverdue ? (
                              <span className="text-[10px] font-medium text-orange-700 dark:text-orange-400">
                                优先处理 · 已超时
                              </span>
                            ) : null}
                          </div>
                        </td>
                        <td className="p-2 whitespace-nowrap text-muted-foreground">
                          {row.started_at ? String(row.started_at).slice(0, 16) : "—"}
                        </td>
                        <td className="p-2 whitespace-nowrap text-muted-foreground">
                          {typeof runHours === "number" ? `${runHours} h` : "—"}
                        </td>
                        <td className="p-2">
                          {!isRunning ? (
                            "—"
                          ) : isOverdue ? (
                            <span className="text-orange-700 dark:text-orange-400 font-medium">是</span>
                          ) : (
                            <span className="text-muted-foreground">否</span>
                          )}
                        </td>
                        <td className="p-2 whitespace-nowrap text-muted-foreground">
                          {isRunning && isOverdue && typeof overdueHours === "number" ? (
                            <span className="text-orange-800 dark:text-orange-200 font-medium">
                              已超时 {overdueHours} h
                            </span>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td className="p-2">{String(row.severity)}</td>
                        <td className="p-2 font-mono break-all">
                          {String(row.target_type)}:{String(row.target_id)}
                        </td>
                        <td className="p-2 max-w-[14rem]" title={cause}>
                          <span className="line-clamp-2">{causeZh}</span>
                        </td>
                        <td className="p-2 whitespace-nowrap text-muted-foreground">
                          {row.detected_at ? String(row.detected_at).slice(0, 16) : "—"}
                        </td>
                        <td className="p-2 max-w-[12rem] text-muted-foreground break-all">
                          {String(row.payload_brief ?? "—")}
                        </td>
                        <td className="p-2 max-w-[8rem] break-words text-muted-foreground">
                          {note || "—"}
                        </td>
                        <td className="p-2">
                          {active ? (
                            <div className="flex flex-col gap-1">
                              {isPending ? (
                                <Button
                                  size="sm"
                                  className="h-7 text-[10px] px-2"
                                  disabled={startingId === id}
                                  onClick={() => void submitStart(id)}
                                >
                                  {startingId === id ? "…" : "开始处理"}
                                </Button>
                              ) : null}
                              <Button
                                size="sm"
                                variant="secondary"
                                className="h-7 text-[10px] px-2"
                                onClick={() => openCloseDialog(id, "resolved")}
                              >
                                已处理
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                className="h-7 text-[10px] px-2"
                                onClick={() => openCloseDialog(id, "ignored")}
                              >
                                忽略
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                className="h-7 text-[10px] px-2"
                                onClick={() => openCloseDialog(id, "false_positive")}
                              >
                                误报
                              </Button>
                            </div>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={!!closeDialog} onOpenChange={(o) => !o && setCloseDialog(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {closeDialog?.action === "resolved" && "标记为已处理"}
              {closeDialog?.action === "ignored" && "标记为忽略"}
              {closeDialog?.action === "false_positive" && "标记为误报"}
            </DialogTitle>
            <DialogDescription>
              队列项 #{closeDialog?.id}。将写入审计日志（含备注摘要与操作者）。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="res-note">处理备注（可选）</Label>
            <textarea
              id="res-note"
              className="border-input bg-background min-h-[80px] w-full rounded-md border px-3 py-2 text-sm"
              value={resolutionNote}
              onChange={(e) => setResolutionNote(e.target.value)}
              placeholder="简短说明处理方式或结论…"
              maxLength={4000}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCloseDialog(null)} disabled={submitting}>
              取消
            </Button>
            <Button onClick={() => void submitClose()} disabled={submitting}>
              {submitting ? "提交中…" : "确认"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
