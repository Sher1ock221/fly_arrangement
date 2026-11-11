"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { remindersApi, type ReminderTaskRow } from "@/lib/apiClient";
import { queryKeys } from "@/lib/queryKeys";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Loader2, Bell, CalendarDays } from "lucide-react";
import { toast } from "sonner";
import { formatLocalDateTime } from "@/lib/time";

function formatDt(iso: string | null | undefined): string {
  return formatLocalDateTime(iso);
}

function channelLabel(c: string): string {
  if (c === "feishu_private") return "飞书私聊";
  return c;
}

function typeLabel(t: string): string {
  const m: Record<string, string> = {
    one_time: "单次",
    recurring: "周期",
    relative_to_event: "相对日程",
  };
  return m[t] ?? t;
}

function statusBadge(status: string) {
  const variant =
    status === "active"
      ? "default"
      : status === "completed"
        ? "secondary"
        : status === "cancelled" || status === "paused"
          ? "outline"
          : "destructive";
  const labels: Record<string, string> = {
    active: "进行中",
    paused: "已暂停",
    completed: "已完成",
    cancelled: "已取消",
    failed: "失败",
  };
  return <Badge variant={variant}>{labels[status] ?? status}</Badge>;
}

export default function RemindersSettingsPage() {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.reminders(),
    queryFn: () => remindersApi.list(),
  });

  const cancelMut = useMutation({
    mutationFn: (id: number) => remindersApi.cancel(id),
    onSuccess: () => {
      toast.success("已取消该提醒");
      queryClient.invalidateQueries({ queryKey: queryKeys.reminders() });
    },
    onError: (e: Error) => toast.error(e.message || "取消失败"),
  });

  const rows: ReminderTaskRow[] = Array.isArray(data) ? data : [];

  return (
    <div className="space-y-6 max-w-6xl">
      <Card>
        <CardHeader>
          <div className="flex items-start gap-3">
            <Bell className="h-8 w-8 text-primary shrink-0 mt-0.5" />
            <div>
              <CardTitle>我的提醒</CardTitle>
              <CardDescription>
                由 AI 或系统创建的本地提醒计划，在下方列表中查看与取消。桌面版通过本应用内「我的提醒」管理，不再依赖飞书推送。
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading && (
            <div className="flex items-center gap-2 text-muted-foreground py-8 justify-center">
              <Loader2 className="h-5 w-5 animate-spin" />
              加载中…
            </div>
          )}
          {error && (
            <p className="text-destructive text-sm py-4">
              {(error as Error).message || "加载失败"}
            </p>
          )}
          {!isLoading && !error && rows.length === 0 && (
            <p className="text-muted-foreground text-sm py-6 text-center">
              暂无提醒计划。可在 AI 助手中说明行程与提醒需求，成功创建后会出现在此列表。
            </p>
          )}
          {!isLoading && !error && rows.length > 0 && (
            <ul className="space-y-3">
              {rows.map((r) => (
                <li
                  key={r.id}
                  className="rounded-lg border border-border bg-card/50 p-4 flex flex-col gap-3 md:flex-row md:items-start md:justify-between"
                >
                  <div className="min-w-0 flex-1 space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{r.title}</span>
                      {statusBadge(r.status)}
                      <Badge variant="outline">{typeLabel(r.reminder_type)}</Badge>
                      <span className="text-xs text-muted-foreground">{channelLabel(r.channel)}</span>
                    </div>
                    {r.content && (
                      <p className="text-sm text-muted-foreground whitespace-pre-wrap">{r.content}</p>
                    )}
                    <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
                      <span>下次：{formatDt(r.next_trigger_at)}</span>
                      <span>截止：{formatDt(r.end_at)}</span>
                      {r.related_event_id != null ? (
                        <Link
                          href={`/calendar/${r.related_event_id}`}
                          className="inline-flex items-center gap-1 text-primary hover:underline"
                        >
                          <CalendarDays className="h-3.5 w-3.5" />
                          关联日程 #{r.related_event_id}
                        </Link>
                      ) : null}
                    </div>
                  </div>
                  <div className="shrink-0 md:pt-0.5">
                    {r.status === "active" || r.status === "paused" ? (
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={cancelMut.isPending}
                        onClick={() => {
                          if (confirm("确定取消该提醒？取消后不会再发送。")) {
                            cancelMut.mutate(r.id);
                          }
                        }}
                      >
                        取消提醒
                      </Button>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
