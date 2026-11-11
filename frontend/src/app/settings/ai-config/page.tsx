"use client";

import { useState, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, CheckCircle2, XCircle, RefreshCw } from "lucide-react";
import { aiConfigApi } from "@/lib/apiClient";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

type TestStatus = "idle" | "loading" | "success" | "error";

function ConfigFormSkeleton() {
  return (
    <Card className="w-full rounded-2xl border border-border bg-card shadow-sm">
      <CardHeader>
        <Skeleton className="h-7 w-32" />
        <Skeleton className="mt-2 h-4 w-full max-w-md" />
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="space-y-2">
          <Skeleton className="h-4 w-20" />
          <Skeleton className="h-10 w-full max-w-3xl" />
        </div>
        <div className="space-y-2">
          <Skeleton className="h-4 w-20" />
          <Skeleton className="h-10 w-full max-w-3xl" />
        </div>
      </CardContent>
      <CardFooter className="gap-3">
        <Skeleton className="h-10 w-24" />
        <Skeleton className="h-10 w-24" />
      </CardFooter>
    </Card>
  );
}

function ConfigLoadError({ onRetry }: { onRetry: () => void }) {
  return (
    <Card className="w-full rounded-2xl border border-border bg-card shadow-sm">
      <CardHeader>
        <CardTitle>模型配置</CardTitle>
        <CardDescription>
          加载配置时出现问题，请检查网络或后端服务后重试。
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Button onClick={onRetry} variant="outline" className="gap-2">
          <RefreshCw className="h-4 w-4" />
          重新加载
        </Button>
      </CardContent>
    </Card>
  );
}

export default function AIConfigPage() {
  const queryClient = useQueryClient();
  const [modelName, setModelName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [testStatus, setTestStatus] = useState<TestStatus>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [testPassed, setTestPassed] = useState(false);
  const [saveLoading, setSaveLoading] = useState(false);
  const [lastProbe, setLastProbe] = useState<{
    elapsed_ms: number;
    available_models_count: number;
    model_found: boolean;
  } | null>(null);

  const {
    data: config,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ["ai-config"],
    queryFn: async () => {
      const res = await aiConfigApi.getConfig();
      return res ?? undefined;
    },
    retry: false,
  });

  useEffect(() => {
    if (config) {
      setModelName(config.model_name ?? "");
      setBaseUrl(config.base_url ?? "");
    }
  }, [config]);

  const handleTestConnection = async () => {
    const name = modelName.trim();
    const url = baseUrl.trim();
    if (!name || !url) {
      setErrorMessage("请填写模型名称和模型地址");
      setTestStatus("error");
      return;
    }
    setErrorMessage(null);
    setTestStatus("loading");
    setTestPassed(false);
    try {
      const res = await aiConfigApi.testConnection({ base_url: url, model_name: name });
      if (res.base_url && res.base_url !== url) {
        setBaseUrl(res.base_url);
      }
      const raw = res as unknown as Record<string, unknown>;
      const elapsed = typeof raw.elapsed_ms === "number" ? raw.elapsed_ms : 0;
      const amc =
        typeof raw.available_models_count === "number"
          ? raw.available_models_count
          : Array.isArray(raw.available_models)
            ? raw.available_models.length
            : 0;
      const mf = Boolean(raw.model_found);
      setLastProbe({ elapsed_ms: elapsed, available_models_count: amc, model_found: mf });
      if (res.ok) {
        setTestStatus("success");
        setTestPassed(true);
      } else {
        setTestStatus("error");
        setTestPassed(false);
        setErrorMessage(res.detail || "连接失败");
      }
    } catch (e) {
      setTestStatus("error");
      setTestPassed(false);
      const raw = e instanceof Error ? e.message : String(e);
      try {
        const parsed = JSON.parse(raw) as { detail?: string };
        setErrorMessage(parsed.detail ?? raw);
      } catch {
        setErrorMessage(raw);
      }
    }
  };

  const handleSaveConfig = async () => {
    const name = modelName.trim();
    const url = baseUrl.trim();
    if (!name || !url) return;
    setSaveLoading(true);
    try {
      await aiConfigApi.saveConfig({
        model_name: name,
        base_url: url,
        is_active: true,
      });
      await queryClient.invalidateQueries({ queryKey: ["ai-config"] });
      const { toast } = await import("sonner");
      toast.success("配置已保存");
    } catch (e) {
      const raw = e instanceof Error ? e.message : String(e);
      const { toast } = await import("sonner");
      toast.error(raw);
    } finally {
      setSaveLoading(false);
    }
  };

  const canSave = testPassed && modelName.trim() && baseUrl.trim();

  if (isLoading) {
    return (
      <div className="w-full max-w-6xl px-4 py-4 md:px-6 md:py-6">
        <ConfigFormSkeleton />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="w-full max-w-6xl px-4 py-4 md:px-6 md:py-6">
        <ConfigLoadError onRetry={() => refetch()} />
      </div>
    );
  }

  return (
    <div className="w-full max-w-6xl px-4 py-4 md:px-6 md:py-6">
      <div className="space-y-6 md:space-y-8">
        <Card className="w-full rounded-2xl border border-border bg-card shadow-sm">
          <CardHeader>
            <CardTitle className="text-lg md:text-xl">模型配置</CardTitle>
            <CardDescription className="text-sm leading-6">
              配置 Ollama 模型名称与地址，测试通过后可保存为当前生效配置。
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6 md:space-y-7">
            <div className="w-full max-w-3xl space-y-5 md:space-y-6">
              <div className="space-y-2.5">
                <Label htmlFor="model_name">模型名称</Label>
                <Input
                  id="model_name"
                  className="w-full"
                  placeholder="如 qwen2.5:7b"
                  value={modelName}
                  onChange={(e) => {
                    setModelName(e.target.value);
                    setErrorMessage(null);
                    setTestPassed(false);
                    setTestStatus("idle");
                  }}
                />
              </div>
              <div className="space-y-2.5">
                <Label htmlFor="base_url">模型地址</Label>
                <Input
                  id="base_url"
                  className="w-full"
                  placeholder="如 http://127.0.0.1:11434"
                  value={baseUrl}
                  onChange={(e) => {
                    setBaseUrl(e.target.value);
                    setErrorMessage(null);
                    setTestPassed(false);
                    setTestStatus("idle");
                  }}
                />
              </div>
            </div>
            <p className="text-sm text-muted-foreground leading-6">
              请确保已在本地启动 Ollama 且配置了{" "}
              <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">
                OLLAMA_ORIGINS=&quot;*&quot;
              </code>
            </p>
            {testStatus === "loading" && (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                连接中…
              </p>
            )}
            {testStatus === "success" && (
              <div
                className="space-y-1 text-sm text-green-600 dark:text-green-500"
                role="status"
              >
                <p className="flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 shrink-0" />
                  已连接：模型存在，Ollama 响应正常
                </p>
                {lastProbe && (
                  <ul className="text-xs text-muted-foreground list-disc pl-5 space-y-0.5">
                    <li>规范化地址：{baseUrl.trim() || "—"}</li>
                    <li>模型名称：{modelName.trim() || "—"}</li>
                    <li>模型已找到：{lastProbe.model_found ? "是" : "否"}</li>
                    <li>测试耗时：{lastProbe.elapsed_ms} ms</li>
                    <li>可用模型数（服务端计数）：{lastProbe.available_models_count}</li>
                  </ul>
                )}
              </div>
            )}
            {testStatus === "error" && errorMessage && (
              <p
                className="flex items-center gap-2 text-sm text-destructive"
                role="alert"
              >
                <XCircle className="h-4 w-4 shrink-0" />
                连接失败：{errorMessage}
              </p>
            )}
          </CardContent>
          <CardFooter className="flex flex-wrap gap-3">
            <Button
              variant="outline"
              onClick={handleTestConnection}
              disabled={testStatus === "loading"}
              className="h-10 w-full sm:w-auto"
            >
              {testStatus === "loading" ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  测试连接
                </>
              ) : (
                "测试连接"
              )}
            </Button>
            <Button
              onClick={handleSaveConfig}
              disabled={!canSave || saveLoading}
              className="h-10 w-full sm:w-auto"
            >
              {saveLoading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  保存中…
                </>
              ) : (
                "保存配置"
              )}
            </Button>
          </CardFooter>
        </Card>
      </div>
    </div>
  );
}
