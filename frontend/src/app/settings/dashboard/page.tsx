"use client";

import { useState, useEffect } from "react";
import { useAuth } from "@/contexts/AuthContext";
import Link from "next/link";
import { adminApi, getStoredToken } from "@/lib/apiClient";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Users, UserCheck, FileText, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { formatLocalDateTime } from "@/lib/time";

type Summary = {
  total_users: number;
  active_users: number;
  admin_users: number;
  normal_users: number;
  total_feishu_identities: number;
  bound_feishu_identities: number;
  unbound_feishu_identities: number;
  ignored_feishu_identities: number;
  recent_audit_logs: {
    id: number;
    actor_username: string | null;
    action: string;
    target_type: string | null;
    target_id: string | null;
    detail: string;
    created_at: string | null;
  }[];
  recent_login_success_count: number;
};

export default function DashboardPage() {
  const { user, token } = useAuth();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (user?.role !== "admin") return;
    const t = token || getStoredToken();
    if (!t) return;
    setLoading(true);
    adminApi
      .dashboardSummary(t)
      .then((res) => setSummary(res as Summary))
      .catch((e) => {
        toast.error(e instanceof Error ? e.message : String(e));
        setSummary(null);
      })
      .finally(() => setLoading(false));
  }, [user?.role, token]);

  if (user?.role !== "admin") return null;

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">总用户数</CardTitle>
            <Users className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{summary?.total_users ?? "—"}</div>
            <p className="text-xs text-muted-foreground">启用: {summary?.active_users ?? "—"}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">管理员 / 普通用户</CardTitle>
            <ShieldCheck className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{summary?.admin_users ?? "—"} / {summary?.normal_users ?? "—"}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">近 7 天登录成功</CardTitle>
            <UserCheck className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{summary?.recent_login_success_count ?? "—"}</div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5" />
            最近审计日志
          </CardTitle>
          <CardDescription>最近 10 条</CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <p className="text-muted-foreground text-sm">加载中…</p>
          ) : !summary?.recent_audit_logs?.length ? (
            <p className="text-muted-foreground text-sm">暂无记录</p>
          ) : (
            <ul className="space-y-2">
              {summary.recent_audit_logs.map((log) => (
                <li key={log.id} className="flex flex-wrap items-baseline gap-2 rounded border border-border px-3 py-2 text-sm">
                  <span className="text-muted-foreground shrink-0">
                    {formatLocalDateTime(log.created_at)}
                  </span>
                  <span className="font-medium">{log.actor_username ?? "—"}</span>
                  <span>{log.action}</span>
                  {log.target_type && <span className="text-muted-foreground">{log.target_type}</span>}
                  {log.detail && <span className="text-muted-foreground truncate max-w-[200px]" title={log.detail}>{log.detail}</span>}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <div className="flex flex-wrap gap-3">
        <Button asChild variant="outline">
          <Link href="/settings/accounts" className="flex items-center gap-2">
            <Users className="h-4 w-4" />
            账号管理
          </Link>
        </Button>
        <Button asChild variant="outline">
          <Link href="/settings/audit-logs" className="flex items-center gap-2">
            <FileText className="h-4 w-4" />
            审计日志
          </Link>
        </Button>
      </div>
    </div>
  );
}
