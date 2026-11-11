"use client";

import { useState, useEffect } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { useRouter } from "next/navigation";
import { adminApi, getStoredToken } from "@/lib/apiClient";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Loader2, AlertCircle, CheckCircle, XCircle } from "lucide-react";
import { toast } from "sonner";

export default function SystemStatusPage() {
  const router = useRouter();
  const { user, token } = useAuth();
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (user?.role !== "admin") {
      router.replace("/");
      return;
    }
    const t = token || getStoredToken();
    if (!t) return;
    adminApi.systemStatus(t)
      .then((res) => setData(res as Record<string, unknown>))
      .catch((e) => {
        toast.error(e instanceof Error ? e.message : String(e));
        if (String(e).includes("403")) router.replace("/");
      })
      .finally(() => setLoading(false));
  }, [user?.role, token, router]);

  if (user && user.role !== "admin") return null;
  if (loading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" />
        加载中…
      </div>
    );
  }
  if (!data) return <p className="text-muted-foreground">暂无数据</p>;

  const warnings = (data.warnings as string[]) || [];
  const StatusBadge = ({ ok, label }: { ok: boolean; label: string }) =>
    ok ? (
      <span className="inline-flex items-center gap-1 rounded-full bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400 px-2 py-0.5 text-xs">
        <CheckCircle className="h-3.5 w-3.5" />
        {label}
      </span>
    ) : (
      <span className="inline-flex items-center gap-1 rounded-full bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400 px-2 py-0.5 text-xs">
        <XCircle className="h-3.5 w-3.5" />
        {label}
      </span>
    );

  return (
    <div className="space-y-6 max-w-2xl">
      <Card>
        <CardHeader>
          <CardTitle>系统状态</CardTitle>
          <CardDescription>部署与运行环境检查，仅管理员可查看</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-2 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-muted-foreground w-36">应用</span>
              <span>{String(data.app_name ?? "—")} {String(data.app_version ?? "")}</span>
              <StatusBadge ok={true} label={String(data.environment ?? "dev")} />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-muted-foreground w-36">数据库</span>
              <StatusBadge ok={Boolean(data.database_connected)} label={data.database_connected ? "已连接" : "未连接"} />
              {data.database_url_masked != null && String(data.database_url_masked).trim() !== "" && (
                <span className="text-muted-foreground text-xs">{String(data.database_url_masked)}</span>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-muted-foreground w-36">默认管理员</span>
              <StatusBadge ok={Boolean(data.default_admin_exists)} label={data.default_admin_exists ? "存在" : "不存在"} />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-muted-foreground w-36">用户统计</span>
              <span>总 {Number(data.total_users ?? 0)}，启用 {Number(data.total_active_users ?? 0)}</span>
            </div>
            {!data.feishu_desktop_disabled && (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-muted-foreground w-36">飞书身份</span>
                  <span>总 {Number(data.total_feishu_identities ?? 0)}，已绑定 {Number(data.total_bound_feishu_identities ?? 0)}</span>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-muted-foreground w-36">飞书配置</span>
                  <StatusBadge ok={Boolean(data.feishu_config_present)} label={data.feishu_config_present ? "已配置" : "未配置"} />
                </div>
              </>
            )}
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-muted-foreground w-36">模型配置</span>
              <StatusBadge ok={Boolean(data.model_config_present)} label={data.model_config_present ? "已配置" : "未配置"} />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-muted-foreground w-36">服务器时间</span>
              <span>{data.current_server_time ? new Date(String(data.current_server_time)).toLocaleString("zh-CN") : "—"}</span>
            </div>
            {data.uptime_seconds != null && (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-muted-foreground w-36">运行时长</span>
                <span>{Number(data.uptime_seconds)} 秒</span>
              </div>
            )}
          </div>
          {warnings.length > 0 && (
            <Alert variant="destructive" className="mt-4">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>
                <ul className="list-disc pl-4 space-y-1">
                  {warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
