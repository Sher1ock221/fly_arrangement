"use client";

import { useState, useEffect, useCallback } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { useRouter } from "next/navigation";
import { adminApi, getStoredToken } from "@/lib/apiClient";
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
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Loader2, RefreshCw, Download } from "lucide-react";
import { toast } from "sonner";
import { formatLocalDateTime } from "@/lib/time";

interface AuditLogItem {
  id: number;
  actor_user_id: number | null;
  actor_username: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  detail: string | null;
  ip_address: string | null;
  user_agent: string | null;
  metadata_json: unknown;
  created_at: string | null;
}

export default function AuditLogsPage() {
  const router = useRouter();
  const { user, token } = useAuth();
  const [items, setItems] = useState<AuditLogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [loading, setLoading] = useState(true);
  const [actionFilter, setActionFilter] = useState("");
  const [targetTypeFilter, setTargetTypeFilter] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [q, setQ] = useState("");
  const [detailLogId, setDetailLogId] = useState<number | null>(null);
  const [detailData, setDetailData] = useState<Record<string, unknown> | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [exporting, setExporting] = useState(false);

  const fetchList = useCallback(async () => {
    const t = token || getStoredToken();
    if (!t) return;
    setLoading(true);
    try {
      const res = await adminApi.listAuditLogs(t, {
        page,
        page_size: pageSize,
        action: actionFilter || undefined,
        target_type: targetTypeFilter || undefined,
        start_date: startDate.trim() || undefined,
        end_date: endDate.trim() || undefined,
        q: q.trim() || undefined,
      });
      setItems((res.items as AuditLogItem[]) || []);
      setTotal(res.total ?? 0);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(msg || "加载失败");
      if (msg.includes("403")) router.replace("/");
    } finally {
      setLoading(false);
    }
  }, [token, page, pageSize, actionFilter, targetTypeFilter, startDate, endDate, q, router]);

  useEffect(() => {
    if (user?.role === "admin") fetchList();
  }, [user?.role, fetchList]);

  useEffect(() => {
    if (user && user.role !== "admin") router.replace("/");
  }, [user, router]);

  const openDetail = async (logId: number) => {
    const t = token || getStoredToken();
    if (!t) return;
    setDetailLogId(logId);
    setDetailLoading(true);
    setDetailData(null);
    try {
      const res = await adminApi.getAuditLogDetail(t, logId);
      setDetailData(res.item as Record<string, unknown>);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
      setDetailLogId(null);
    } finally {
      setDetailLoading(false);
    }
  };

  const handleExport = async () => {
    const t = token || getStoredToken();
    if (!t) return;
    setExporting(true);
    try {
      await adminApi.exportAuditLogs(t, {
        action: actionFilter || undefined,
        target_type: targetTypeFilter || undefined,
        start_date: startDate.trim() || undefined,
        end_date: endDate.trim() || undefined,
        q: q.trim() || undefined,
      });
      toast.success("导出成功");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setExporting(false);
    }
  };

  if (user && user.role !== "admin") return null;

  return (
    <div className="mx-auto max-w-6xl">
      <Card>
        <CardHeader>
          <CardTitle>审计日志</CardTitle>
          <CardDescription>系统操作审计记录，仅管理员可查看。支持按动作、资源类型、日期筛选。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <Input
              placeholder="搜索操作人 / 详情"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              className="max-w-xs"
            />
            <select
              className="h-10 rounded-md border border-input bg-background px-3 text-sm"
              value={actionFilter}
              onChange={(e) => setActionFilter(e.target.value)}
            >
              <option value="">全部动作</option>
              <option value="user_update_profile">修改资料</option>
              <option value="user_change_password">修改密码</option>
              <option value="admin_view_dashboard_summary">查看概览</option>
              <option value="admin_view_user_detail">查看用户详情</option>
              <option value="admin_view_audit_log_detail">查看审计详情</option>
              <option value="admin_create_user">创建用户</option>
              <option value="admin_update_user">编辑用户</option>
              <option value="admin_reset_user_password">重置密码</option>
              <option value="admin_set_user_active">启用/禁用用户</option>
              <option value="admin_bind_feishu_identity">绑定飞书身份</option>
              <option value="admin_unbind_feishu_identity">解绑飞书身份</option>
              <option value="admin_ignore_feishu_identity">忽略飞书身份</option>
              <option value="admin_view_users">查看用户列表</option>
              <option value="admin_view_feishu_identities">查看飞书身份池</option>
              <option value="login_success">登录成功</option>
              <option value="login_failed">登录失败</option>
              <option value="admin_access_denied">管理员接口拒绝</option>
              <option value="data_access_denied">数据越权拒绝</option>
            </select>
            <select
              className="h-10 rounded-md border border-input bg-background px-3 text-sm"
              value={targetTypeFilter}
              onChange={(e) => setTargetTypeFilter(e.target.value)}
            >
              <option value="">全部资源类型</option>
              <option value="user">user</option>
              <option value="feishu_identity">feishu_identity</option>
              <option value="system">system</option>
              <option value="system_audit_log">system_audit_log</option>
            </select>
            <Input
              type="date"
              className="h-10 w-36"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              placeholder="开始日期"
            />
            <Input
              type="date"
              className="h-10 w-36"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              placeholder="结束日期"
            />
            <Button variant="outline" onClick={fetchList} disabled={loading}>
              <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
              刷新
            </Button>
            <Button variant="outline" onClick={handleExport} disabled={exporting}>
              {exporting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Download className="mr-2 h-4 w-4" />}
              导出 CSV
            </Button>
          </div>
          {loading ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              加载中…
            </p>
          ) : (
            <div className="space-y-2">
              {items.length === 0 ? (
                <p className="text-sm text-muted-foreground">暂无记录</p>
              ) : (
                items.map((row) => (
                  <div
                    key={row.id}
                    role="button"
                    tabIndex={0}
                    onClick={() => openDetail(row.id)}
                    onKeyDown={(e) => e.key === "Enter" && openDetail(row.id)}
                    className="rounded-lg border border-border bg-background p-3 text-sm cursor-pointer hover:bg-muted/50 transition-colors"
                  >
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                      <span className="text-muted-foreground">
                        {formatLocalDateTime(row.created_at)}
                      </span>
                      <span className="font-medium">{row.action}</span>
                      {row.actor_username && (
                        <span className="text-muted-foreground">操作人: {row.actor_username}</span>
                      )}
                      {row.target_type && (
                        <span className="text-muted-foreground">
                          {row.target_type}{row.target_id ? ` #${row.target_id}` : ""}
                        </span>
                      )}
                    </div>
                    {row.detail && (
                      <p className="mt-1 text-muted-foreground break-words">{row.detail}</p>
                    )}
                  </div>
                ))
              )}
              <div className="flex items-center justify-between pt-2">
                <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
                  上一页
                </Button>
                <span className="text-xs text-muted-foreground">
                  第 {page} 页 / 共 {Math.max(1, Math.ceil(total / pageSize))} 页（共 {total} 条）
                </span>
                <Button variant="outline" size="sm" disabled={page >= Math.ceil(total / pageSize)} onClick={() => setPage((p) => p + 1)}>
                  下一页
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={detailLogId != null} onOpenChange={(open) => !open && setDetailLogId(null)}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>审计日志详情</DialogTitle>
          </DialogHeader>
          {detailLoading ? (
            <div className="flex items-center gap-2 py-8 text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              加载中…
            </div>
          ) : detailData ? (
            <div className="space-y-3 py-4 text-sm">
              <div className="grid grid-cols-[100px_1fr] gap-2">
                <span className="text-muted-foreground">操作人</span>
                <span>{String(detailData.actor_username ?? "—")}</span>
                <span className="text-muted-foreground">动作</span>
                <span>{String(detailData.action ?? "—")}</span>
                <span className="text-muted-foreground">资源类型</span>
                <span>{String(detailData.target_type ?? "—")}</span>
                <span className="text-muted-foreground">资源 ID</span>
                <span>{String(detailData.target_id ?? "—")}</span>
                <span className="text-muted-foreground">详情</span>
                <span className="break-words">{String(detailData.detail ?? "—")}</span>
                <span className="text-muted-foreground">IP</span>
                <span>{String(detailData.ip_address ?? "—")}</span>
                <span className="text-muted-foreground">User-Agent</span>
                <span className="break-all text-xs">{String(detailData.user_agent ?? "—")}</span>
                <span className="text-muted-foreground">时间</span>
                <span>{formatLocalDateTime(detailData.created_at ? String(detailData.created_at) : null)}</span>
              </div>
              {detailData.metadata_json != null && (
                <div>
                  <p className="text-muted-foreground mb-1">metadata_json</p>
                  <pre className="rounded bg-muted p-3 text-xs overflow-x-auto max-h-48 overflow-y-auto">
                    {JSON.stringify(detailData.metadata_json, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}
