"use client";

import Link from "next/link";
import type { ExecutionResult } from "@/types/ai";
import { cn } from "@/lib/utils";
import { Check, X, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";

export interface ExecutionStepsProps {
  steps: ExecutionResult[];
  className?: string;
}

/** 候选客户项：姓名、公司、职位 */
function CandidateList({
  candidates,
}: {
  candidates: Array<{ name?: string; company?: string | null; position?: string | null }>;
}) {
  if (!candidates?.length) return null;
  return (
    <ul className="mt-2 space-y-1.5 rounded border border-border/60 bg-background/50 px-2.5 py-2">
      <p className="text-xs font-medium text-muted-foreground">可能匹配的客户：</p>
      {candidates.map((c, i) => (
        <li key={i} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-[13px]">
          <span className="font-medium text-foreground">{c.name ?? "—"}</span>
          {(c.company || c.position) && (
            <span className="text-muted-foreground">
              {[c.company, c.position].filter(Boolean).join(" · ")}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

/**
 * 展示 AI 工具执行步骤：灰色卡片、步骤列表，成功绿色 ✓、失败红色 ✕。
 * 支持成功后的跳转：detail_url 为 /projects/{id} 时显示「查看项目」，为 /customers/{id} 时显示「查看客户详情」；歧义时展示候选客户列表。
 */
export function ExecutionSteps({ steps, className }: ExecutionStepsProps) {
  if (!steps?.length) return null;

  return (
    <div
      className={cn(
        "mt-2.5 rounded-lg border border-border/60 bg-muted/50 px-3 py-2.5",
        className
      )}
    >
      <p className="mb-2 text-xs font-medium text-muted-foreground">AI 执行步骤</p>
      <ul className="space-y-1.5">
        {steps.map((step, i) => {
          const name = step.tool ?? step.tool_name ?? "未知工具";
          const success = step.success;
          const summary = step.execution_summary ?? step.error ?? "";
          const result = step.result as ExecutionResult["result"] | undefined;
          const candidates = step.candidates ?? result?.candidates;

          return (
            <li key={i} className="flex gap-2 text-[13px]">
              <span
                className={cn(
                  "shrink-0 mt-0.5",
                  success ? "text-green-600 dark:text-green-500" : "text-red-600 dark:text-red-500"
                )}
                aria-hidden
              >
                {success ? <Check className="h-4 w-4" /> : <X className="h-4 w-4" />}
              </span>
              <span className="min-w-0 flex-1">
                <span className={cn("font-medium", success ? "text-foreground" : "text-destructive")}>
                  {name}
                </span>
                {summary && (
                  <span className="block mt-0.5 text-muted-foreground">{summary}</span>
                )}
                {success && result && (result.detail_url ?? (step.tool_name === "create_customer_interaction" && result.customer_id)) && (
                  <span className="block mt-2">
                    <Button variant="outline" size="sm" className="h-8 gap-1.5 text-xs" asChild>
                      <Link href={result.detail_url ?? `/customers/${result.customer_id}`}>
                        <ExternalLink className="h-3.5 w-3.5" />
                        {result.detail_url?.includes("/projects/") ? "查看项目" : "查看客户详情"}
                      </Link>
                    </Button>
                  </span>
                )}
                {!success && candidates && candidates.length > 0 && (
                  <CandidateList candidates={candidates} />
                )}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
