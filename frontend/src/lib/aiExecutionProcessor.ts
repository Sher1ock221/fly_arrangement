import type { QueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import type { ExecutionResult } from "@/types/ai";
import { queryKeys } from "@/lib/queryKeys";

export interface ProcessExecutionResultsReturn {
  executionSummary: string[];
  executionErrors: string[];
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function normalizeCandidates(v: unknown): ExecutionResult["candidates"] {
  if (!Array.isArray(v)) return undefined;
  return v
    .filter((c): c is Record<string, unknown> => isPlainObject(c))
    .map((c) => ({
      name: typeof c.name === "string" ? c.name : undefined,
      company: c.company != null ? String(c.company) : null,
      position: c.position != null ? String(c.position) : null,
    }));
}

/** 模型可能对 create_reminder_task 失败后再试，步骤区只展示最终一条 */
function dedupeCreateReminderTaskSteps(steps: ExecutionResult[]): ExecutionResult[] {
  const hits = steps
    .map((s, i) => ({ i, s }))
    .filter(({ s }) => s.tool_name === "create_reminder_task");
  if (hits.length <= 1) return steps;
  const ok = hits.filter(({ s }) => s.success);
  const keepIdx = ok.length > 0 ? ok[ok.length - 1]!.i : hits[hits.length - 1]!.i;
  return steps.filter((s, i) => s.tool_name !== "create_reminder_task" || i === keepIdx);
}

/**
 * 将接口返回的 execution_results（unknown[]）规范为 ExecutionResult[]，
 * 供 ChatMessage 与 ExecutionSteps 使用。非数组返回 []，非对象项被过滤。
 */
export function normalizeExecutionResults(input: unknown): ExecutionResult[] {
  if (!Array.isArray(input)) return [];
  const mapped = input
    .filter((item): item is Record<string, unknown> => isPlainObject(item))
    .map((item) => {
      const result = item.result;
      const resultObj =
        isPlainObject(result) ? (result as ExecutionResult["result"]) : undefined;
      const candidates =
        normalizeCandidates(item.candidates) ?? resultObj?.candidates ?? undefined;
      return {
        tool: typeof item.tool === "string" ? item.tool : undefined,
        tool_name: typeof item.tool_name === "string" ? item.tool_name : undefined,
        success: Boolean(item.success),
        execution_summary:
          typeof item.execution_summary === "string" ? item.execution_summary : undefined,
        error: typeof item.error === "string" ? item.error : undefined,
        result: resultObj,
        candidates,
      } satisfies ExecutionResult;
    });
  return dedupeCreateReminderTaskSteps(mapped);
}

/**
 * 遍历 execution_results：按 tool_name 触发 invalidate/refetch，
 * 收集 execution_summary 与 error，返回 executionSummary[] 和 executionErrors[]。
 */
export function processExecutionResults(
  executionResults: ExecutionResult[] | undefined,
  queryClient: QueryClient
): ProcessExecutionResultsReturn {
  const executionSummary: string[] = [];
  const executionErrors: string[] = [];

  if (!executionResults?.length) {
    return { executionSummary, executionErrors };
  }

  const projectToolNames = [
    "create_project",
    "upsert_project",
    "update_project",
    "update_project_fields",
  ];
  const projectIds: number[] = [];

  for (const r of executionResults) {
    if (r.success === false && r.error) {
      executionErrors.push(r.error);
    }
    if (r.execution_summary) {
      executionSummary.push(r.execution_summary);
    }

    switch (r.tool_name) {
      case "update_project":
      case "update_project_fields":
        queryClient.invalidateQueries({ queryKey: ["projects"] });
        break;
      case "create_project":
      case "upsert_project":
        queryClient.refetchQueries({ queryKey: ["projects"] });
        break;
      case "update_customer":
        queryClient.invalidateQueries({ queryKey: ["customers"] });
        break;
      case "create_customer":
        queryClient.refetchQueries({ queryKey: ["customers"] });
        break;
      case "create_customer_interaction":
        queryClient.invalidateQueries({ queryKey: ["customers"] });
        break;
      case "create_calendar_event":
      case "update_calendar_event":
      case "delete_calendar_event":
      case "confirm_or_cancel_schedule":
      case "execute_candidate_schedule_strategy":
        queryClient.invalidateQueries({ queryKey: queryKeys.calendarEvents() });
        if (
          (r.tool_name === "update_calendar_event" || r.tool_name === "create_calendar_event") &&
          r.result &&
          typeof r.result === "object" &&
          "id" in r.result &&
          typeof (r.result as { id: number }).id === "number"
        ) {
          queryClient.invalidateQueries({
            queryKey: queryKeys.calendarEventDetail((r.result as { id: number }).id),
          });
        }
        break;
      case "suggest_schedule":
        // 新逻辑下 suggest_schedule 可能直接创建日程（明确时间且无冲突）
        if (r.success && r.result && typeof r.result === "object" && "event_id" in r.result) {
          queryClient.invalidateQueries({ queryKey: queryKeys.calendarEvents() });
        }
        break;
      case "auto_schedule_event":
        if (r.success && r.result && typeof r.result === "object" && "event_id" in r.result) {
          queryClient.invalidateQueries({ queryKey: queryKeys.calendarEvents() });
        }
        break;
      case "execute_compound_schedule":
        queryClient.invalidateQueries({ queryKey: queryKeys.calendarEvents() });
        queryClient.invalidateQueries({ queryKey: queryKeys.reminders() });
        break;
      case "create_reminder_task":
      case "update_reminder_task":
      case "cancel_reminder_task":
        queryClient.invalidateQueries({ queryKey: queryKeys.reminders() });
        break;
      default:
        break;
    }

    if (
      r.success &&
      r.result &&
      typeof r.result === "object" &&
      "id" in r.result &&
      typeof (r.result as { id: number }).id === "number" &&
      r.tool_name &&
      projectToolNames.includes(r.tool_name)
    ) {
      projectIds.push((r.result as { id: number }).id);
    }
  }

  if (projectIds.length > 0) {
    try {
      window.dispatchEvent(
        new CustomEvent("ai:highlight-projects", { detail: { projectIds } })
      );
    } catch {
      // ignore
    }
  }

  const hadScheduleConfirm = executionResults.some(
    (r) =>
      r.success &&
      r.tool_name === "confirm_or_cancel_schedule" &&
      r.result &&
      typeof r.result === "object" &&
      "event_id" in r.result,
  );
  if (hadScheduleConfirm) {
    toast.success("日程已安排成功！可在日历中查看。");
    queryClient.invalidateQueries({ queryKey: queryKeys.calendarEvents() });
  }

  const hadAutoSchedule = executionResults.some(
    (r) =>
      r.success &&
      r.tool_name === "auto_schedule_event" &&
      r.result &&
      typeof r.result === "object" &&
      "event_id" in r.result,
  );
  if (hadAutoSchedule) {
    toast.success("日程已自动安排");
    const adjusted = executionResults.some(
      (r) =>
        r.success &&
        r.tool_name === "auto_schedule_event" &&
        r.result &&
        typeof r.result === "object" &&
        "was_adjusted" in r.result &&
        Boolean((r.result as { was_adjusted?: boolean }).was_adjusted),
    );
    if (adjusted) {
      toast.info("已自动避让冲突并完成安排");
    }
  }

  const hadCreate = executionResults.some(
    (r) =>
      r.success &&
      (r.tool_name === "create_project" || r.tool_name === "upsert_project")
  );
  if (hadCreate) {
    toast.success("AI 已成功为您新建项目！");
    try {
      window.dispatchEvent(
        new CustomEvent("ai:projects-invalidated", { detail: { scrollTo: "bottom" } })
      );
    } catch {
      // ignore
    }
  }

  return { executionSummary, executionErrors };
}
