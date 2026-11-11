"use client";

import { useState, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Loader2,
  RefreshCw,
  Database,
  Trash2,
  FileText,
  AlertTriangle,
  Wrench,
} from "lucide-react";
import { toast } from "sonner";
import {
  adminApi,
  maintenanceApi,
  projectsApi,
  getStoredToken,
  type MaintenanceSummary,
} from "@/lib/apiClient";
import { queryKeys } from "@/lib/queryKeys";
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
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";

const LOG_SCOPES = [
  { value: "chat", label: "聊天日志", desc: "对话记录（chat_records）" },
  { value: "system", label: "系统日志", desc: "运行日志（system_logs）" },
  { value: "audit", label: "审计日志", desc: "系统审计（system_audit_logs）" },
  { value: "feishu", label: "飞书事件", desc: "飞书消息事件（feishu_message_events）" },
  { value: "all", label: "全部日志", desc: "上述全部（需输入 CLEAR_ALL_LOGS）" },
] as const;

const RESOURCE_OPTIONS = [
  { value: "projects", label: "项目" },
  { value: "customers", label: "客户" },
  { value: "calendar_events", label: "日程" },
  { value: "conversations", label: "会话" },
] as const;

export default function DataMaintenancePage() {
  const queryClient = useQueryClient();
  const token = getStoredToken();

  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ["maintenance", "summary"],
    queryFn: () => maintenanceApi.getSummary(token),
    enabled: !!token,
  });

  const { data: usersData } = useQuery({
    queryKey: queryKeys.projectSelectableUsers(),
    queryFn: () => projectsApi.listSelectableUsers(),
    enabled: !!token,
  });
  const users = usersData ?? [];

  const [logDialog, setLogDialog] = useState<{
    open: boolean;
    scope: string;
    scopeLabel: string;
    confirmText: string;
    expected: string;
    loading: boolean;
  }>({ open: false, scope: "", scopeLabel: "", confirmText: "", expected: "", loading: false });

  const [reassignDialog, setReassignDialog] = useState<{
    open: boolean;
    resourceType: string;
    targetUserId: number | null;
    onlyNullOwner: boolean;
    beforeDatetime: string;
    confirmText: string;
    loading: boolean;
  }>({
    open: false,
    resourceType: "projects",
    targetUserId: null,
    onlyNullOwner: true,
    beforeDatetime: "",
    confirmText: "",
    loading: false,
  });

  const [deleteDialog, setDeleteDialog] = useState<{
    open: boolean;
    resourceType: string;
    mode: "null_owner" | "by_user";
    targetUserId: number | null;
    beforeDatetime: string;
    confirmText: string;
    loading: boolean;
  }>({
    open: false,
    resourceType: "projects",
    mode: "null_owner",
    targetUserId: null,
    beforeDatetime: "",
    confirmText: "",
    loading: false,
  });

  const openLogClear = (scope: string) => {
    const item = LOG_SCOPES.find((s) => s.value === scope);
    setLogDialog({
      open: true,
      scope,
      scopeLabel: item?.label ?? scope,
      confirmText: "",
      expected: maintenanceApi.getConfirmTextForScope(scope),
      loading: false,
    });
  };

  const runClearLogs = async () => {
    if (logDialog.confirmText.trim() !== logDialog.expected) {
      toast.error(`请输入确认词：${logDialog.expected}`);
      return;
    }
    setLogDialog((d) => ({ ...d, loading: true }));
    try {
      const res = await maintenanceApi.clearLogs(token, logDialog.scope, logDialog.confirmText);
      toast.success(`已清理 ${logDialog.scopeLabel}，删除 ${res.deleted_count} 条`);
      setLogDialog((d) => ({ ...d, open: false }));
      await queryClient.invalidateQueries({ queryKey: ["maintenance", "summary"] });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(msg || "清理失败");
    } finally {
      setLogDialog((d) => ({ ...d, loading: false }));
    }
  };

  const openReassign = () => {
    setReassignDialog({
      open: true,
      resourceType: "projects",
      targetUserId: users[0]?.id ?? null,
      onlyNullOwner: true,
      beforeDatetime: "",
      confirmText: "",
      loading: false,
    });
  };

  const runReassign = async () => {
    if (reassignDialog.confirmText.trim() !== "REASSIGN_DATA") {
      toast.error("请输入确认词：REASSIGN_DATA");
      return;
    }
    if (!reassignDialog.targetUserId) {
      toast.error("请选择目标用户");
      return;
    }
    setReassignDialog((d) => ({ ...d, loading: true }));
    try {
      const res = await maintenanceApi.reassignData(token, {
        resource_type: reassignDialog.resourceType,
        target_user_id: reassignDialog.targetUserId,
        only_null_owner: reassignDialog.onlyNullOwner,
        before_datetime: reassignDialog.beforeDatetime || undefined,
        confirm_text: reassignDialog.confirmText,
      });
      toast.success(`已修复归属：${reassignDialog.resourceType}，更新 ${res.updated_count} 条`);
      setReassignDialog((d) => ({ ...d, open: false }));
      await queryClient.invalidateQueries({ queryKey: ["maintenance", "summary"] });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(msg || "修复失败");
    } finally {
      setReassignDialog((d) => ({ ...d, loading: false }));
    }
  };

  const openDelete = () => {
    setDeleteDialog({
      open: true,
      resourceType: "projects",
      mode: "null_owner",
      targetUserId: users[0]?.id ?? null,
      beforeDatetime: "",
      confirmText: "",
      loading: false,
    });
  };

  const runDelete = async () => {
    if (deleteDialog.confirmText.trim() !== "DELETE_SELECTED_DATA") {
      toast.error("请输入确认词：DELETE_SELECTED_DATA");
      return;
    }
    if (deleteDialog.mode === "by_user" && !deleteDialog.targetUserId) {
      toast.error("请选择目标用户");
      return;
    }
    setDeleteDialog((d) => ({ ...d, loading: true }));
    try {
      const res = await maintenanceApi.deleteData(token, {
        resource_type: deleteDialog.resourceType,
        mode: deleteDialog.mode,
        target_user_id: deleteDialog.mode === "by_user" ? deleteDialog.targetUserId ?? undefined : undefined,
        before_datetime: deleteDialog.beforeDatetime || undefined,
        confirm_text: deleteDialog.confirmText,
      });
      toast.success(`已删除 ${res.deleted_count} 条`);
      setDeleteDialog((d) => ({ ...d, open: false }));
      await queryClient.invalidateQueries({ queryKey: ["maintenance", "summary"] });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(msg || "删除失败");
    } finally {
      setDeleteDialog((d) => ({ ...d, loading: false }));
    }
  };

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Database className="h-5 w-5" />
            数据概况
          </CardTitle>
          <CardDescription>
            各表总数与无归属数量、日志条数。操作前请确认已备份重要数据。
          </CardDescription>
        </CardHeader>
        <CardContent>
          {summaryLoading ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              加载中…
            </p>
          ) : summary ? (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <div className="rounded-lg border p-3">
                <p className="text-xs text-muted-foreground">项目</p>
                <p className="text-xl font-semibold">{summary.project_count}</p>
                {summary.null_owner_project_count > 0 && (
                  <p className="text-xs text-amber-600">无归属：{summary.null_owner_project_count}</p>
                )}
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-xs text-muted-foreground">客户</p>
                <p className="text-xl font-semibold">{summary.customer_count}</p>
                {summary.null_owner_customer_count > 0 && (
                  <p className="text-xs text-amber-600">无归属：{summary.null_owner_customer_count}</p>
                )}
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-xs text-muted-foreground">日程</p>
                <p className="text-xl font-semibold">{summary.calendar_event_count}</p>
                {summary.null_owner_calendar_event_count > 0 && (
                  <p className="text-xs text-amber-600">无归属：{summary.null_owner_calendar_event_count}</p>
                )}
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-xs text-muted-foreground">会话</p>
                <p className="text-xl font-semibold">{summary.conversation_count}</p>
                {summary.null_owner_conversation_count > 0 && (
                  <p className="text-xs text-amber-600">无归属：{summary.null_owner_conversation_count}</p>
                )}
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-xs text-muted-foreground">聊天日志</p>
                <p className="text-xl font-semibold">{summary.chat_log_count}</p>
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-xs text-muted-foreground">系统日志</p>
                <p className="text-xl font-semibold">{summary.system_log_count}</p>
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-xs text-muted-foreground">审计日志</p>
                <p className="text-xl font-semibold">{summary.audit_log_count}</p>
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-xs text-muted-foreground">飞书事件</p>
                <p className="text-xl font-semibold">{summary.feishu_event_count}</p>
              </div>
            </div>
          ) : null}
          <div className="mt-3">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => queryClient.invalidateQueries({ queryKey: ["maintenance", "summary"] })}
            >
              <RefreshCw className="mr-2 h-4 w-4" />
              刷新
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5" />
            日志维护
          </CardTitle>
          <CardDescription>
            清理各类日志。此操作不可恢复，仅建议清理测试数据，请先确认已备份。
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {LOG_SCOPES.map((s) => (
            <Button
              key={s.value}
              type="button"
              variant="outline"
              onClick={() => openLogClear(s.value)}
            >
              {s.label}
            </Button>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Wrench className="h-5 w-5" />
            数据维护
          </CardTitle>
          <CardDescription>
            批量修复无归属数据归属、或批量删除无归属/指定用户数据。危险操作需输入确认词。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-3">
            <Button type="button" variant="outline" onClick={openReassign}>
              修复归属
            </Button>
            <Button type="button" variant="destructive" onClick={openDelete}>
              <Trash2 className="mr-2 h-4 w-4" />
              批量删除
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* 日志清理确认弹窗 */}
      <Dialog open={logDialog.open} onOpenChange={(o) => setLogDialog((d) => ({ ...d, open: o }))}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-amber-500" />
              确认清理：{logDialog.scopeLabel}
            </DialogTitle>
            <DialogDescription>
              此操作不可恢复。将清理对应范围的日志数据。仅建议在测试环境或确认已备份后执行。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-2">
            <Label>请输入确认词：<code className="rounded bg-muted px-1">{logDialog.expected}</code></Label>
            <Input
              value={logDialog.confirmText}
              onChange={(e) => setLogDialog((d) => ({ ...d, confirmText: e.target.value }))}
              placeholder={logDialog.expected}
              className="font-mono"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setLogDialog((d) => ({ ...d, open: false }))} disabled={logDialog.loading}>
              取消
            </Button>
            <Button
              variant="destructive"
              onClick={runClearLogs}
              disabled={logDialog.loading || logDialog.confirmText.trim() !== logDialog.expected}
            >
              {logDialog.loading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  处理中…
                </>
              ) : (
                "确认清理"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 修复归属确认弹窗 */}
      <Dialog open={reassignDialog.open} onOpenChange={(o) => setReassignDialog((d) => ({ ...d, open: o }))}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Wrench className="h-5 w-5" />
              批量修复归属
            </DialogTitle>
            <DialogDescription>
              将选定资源的 owner_user_id 更新为指定用户。默认仅处理无归属数据。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div>
              <Label>资源类型</Label>
              <select
                className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                value={reassignDialog.resourceType}
                onChange={(e) =>
                  setReassignDialog((d) => ({ ...d, resourceType: e.target.value }))
                }
              >
                {RESOURCE_OPTIONS.map((r) => (
                  <option key={r.value} value={r.value}>
                    {r.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <Label>目标用户</Label>
              <select
                className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                value={reassignDialog.targetUserId ?? ""}
                onChange={(e) =>
                  setReassignDialog((d) => ({
                    ...d,
                    targetUserId: e.target.value ? Number(e.target.value) : null,
                  }))
                }
              >
                {users.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.display_name || u.username} (id={u.id})
                  </option>
                ))}
              </select>
            </div>
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="reassign-only-null"
                checked={reassignDialog.onlyNullOwner}
                onChange={(e) =>
                  setReassignDialog((d) => ({ ...d, onlyNullOwner: e.target.checked }))
                }
              />
              <Label htmlFor="reassign-only-null">仅处理无归属（owner_user_id 为空）</Label>
            </div>
            <div>
              <Label>早于该时间（可选，ISO 格式）</Label>
              <Input
                type="text"
                placeholder="2025-01-01T00:00:00"
                value={reassignDialog.beforeDatetime}
                onChange={(e) =>
                  setReassignDialog((d) => ({ ...d, beforeDatetime: e.target.value }))
                }
              />
            </div>
            <div>
              <Label>确认词：<code className="rounded bg-muted px-1">REASSIGN_DATA</code></Label>
              <Input
                value={reassignDialog.confirmText}
                onChange={(e) =>
                  setReassignDialog((d) => ({ ...d, confirmText: e.target.value }))
                }
                placeholder="REASSIGN_DATA"
                className="mt-1 font-mono"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setReassignDialog((d) => ({ ...d, open: false }))} disabled={reassignDialog.loading}>
              取消
            </Button>
            <Button
              onClick={runReassign}
              disabled={
                reassignDialog.loading ||
                reassignDialog.confirmText.trim() !== "REASSIGN_DATA" ||
                !reassignDialog.targetUserId
              }
            >
              {reassignDialog.loading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  处理中…
                </>
              ) : (
                "执行修复"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 批量删除确认弹窗 */}
      <Dialog open={deleteDialog.open} onOpenChange={(o) => setDeleteDialog((d) => ({ ...d, open: o }))}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-destructive">
              <AlertTriangle className="h-5 w-5" />
              批量删除
            </DialogTitle>
            <DialogDescription>
              此操作不可恢复。仅建议删除测试或无归属数据，请先确认已备份。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div>
              <Label>资源类型</Label>
              <select
                className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                value={deleteDialog.resourceType}
                onChange={(e) =>
                  setDeleteDialog((d) => ({ ...d, resourceType: e.target.value }))
                }
              >
                {RESOURCE_OPTIONS.map((r) => (
                  <option key={r.value} value={r.value}>
                    {r.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <Label>删除模式</Label>
              <select
                className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                value={deleteDialog.mode}
                onChange={(e) =>
                  setDeleteDialog((d) => ({
                    ...d,
                    mode: e.target.value as "null_owner" | "by_user",
                  }))
                }
              >
                <option value="null_owner">仅无归属数据</option>
                <option value="by_user">指定用户下全部数据</option>
              </select>
            </div>
            {deleteDialog.mode === "by_user" && (
              <div>
                <Label>目标用户</Label>
                <select
                  className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={deleteDialog.targetUserId ?? ""}
                  onChange={(e) =>
                    setDeleteDialog((d) => ({
                      ...d,
                      targetUserId: e.target.value ? Number(e.target.value) : null,
                    }))
                  }
                >
                  {users.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.display_name || u.username} (id={u.id})
                    </option>
                  ))}
                </select>
              </div>
            )}
            <div>
              <Label>早于该时间（可选，ISO 格式）</Label>
              <Input
                type="text"
                placeholder="2025-01-01T00:00:00"
                value={deleteDialog.beforeDatetime}
                onChange={(e) =>
                  setDeleteDialog((d) => ({ ...d, beforeDatetime: e.target.value }))
                }
              />
            </div>
            <div>
              <Label>确认词：<code className="rounded bg-muted px-1">DELETE_SELECTED_DATA</code></Label>
              <Input
                value={deleteDialog.confirmText}
                onChange={(e) =>
                  setDeleteDialog((d) => ({ ...d, confirmText: e.target.value }))
                }
                placeholder="DELETE_SELECTED_DATA"
                className="mt-1 font-mono"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteDialog((d) => ({ ...d, open: false }))} disabled={deleteDialog.loading}>
              取消
            </Button>
            <Button
              variant="destructive"
              onClick={runDelete}
              disabled={
                deleteDialog.loading ||
                deleteDialog.confirmText.trim() !== "DELETE_SELECTED_DATA" ||
                (deleteDialog.mode === "by_user" && !deleteDialog.targetUserId)
              }
            >
              {deleteDialog.loading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  处理中…
                </>
              ) : (
                "确认删除"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
