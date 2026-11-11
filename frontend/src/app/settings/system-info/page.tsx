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
import { Loader2, Info } from "lucide-react";
import { toast } from "sonner";

export default function SystemInfoPage() {
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
    adminApi.systemInfo(t)
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

  const features = (data.features as string[]) || [];
  const modules = (data.enabled_modules as string[]) || [];
  const notes = (data.notes as string[]) || [];

  return (
    <div className="space-y-6 max-w-2xl">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Info className="h-5 w-5" />
            系统信息
          </CardTitle>
          <CardDescription>版本与功能说明，仅管理员可查看</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-2 text-sm">
            <div><span className="text-muted-foreground">应用名称</span>：{String(data.app_name ?? "—")}</div>
            <div><span className="text-muted-foreground">版本</span>：{String(data.app_version ?? "—")}</div>
            <div><span className="text-muted-foreground">环境</span>：{String(data.environment ?? "—")}</div>
          </div>
          <div>
            <h3 className="font-medium text-sm mb-2">功能模块</h3>
            <ul className="list-disc pl-4 text-sm text-muted-foreground space-y-1">
              {features.map((f, i) => (
                <li key={i}>{f}</li>
              ))}
            </ul>
          </div>
          <div>
            <h3 className="font-medium text-sm mb-2">已启用模块</h3>
            <p className="text-sm text-muted-foreground">{modules.join("、")}</p>
          </div>
          <div>
            <h3 className="font-medium text-sm mb-2">说明</h3>
            <ul className="list-disc pl-4 text-sm text-muted-foreground space-y-1">
              {notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
