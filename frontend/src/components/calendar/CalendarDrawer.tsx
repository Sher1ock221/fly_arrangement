"use client";

import { useState } from "react";
import { X, Plus, Calendar, Briefcase, Pencil, Trash2, ArrowRightLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import type {
  CalendarEvent,
  CalendarEventCreate,
  CalendarEventUpdate,
} from "@/types/calendar";
import { calendarApi, projectsApi, calendarCollabApi } from "@/lib/apiClient";
import { useAuth } from "@/contexts/AuthContext";
import { EventForm } from "@/components/calendar/EventForm";
import { cn } from "@/lib/utils";
import CollaboratorPanel from "@/components/collaboration/CollaboratorPanel";
import ActivityFeed from "@/components/collaboration/ActivityFeed";
import TransferOwnerDialog from "@/components/collaboration/TransferOwnerDialog";
import { useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/lib/queryKeys";

const TYPE_LABEL: Record<string, string> = {
  event: "日程",
  project: "项目",
  meeting: "会议",
  task: "任务",
};

function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

export interface CalendarDrawerProps {
  open: boolean;
  date: string | null;
  onClose: () => void;
  onRefresh: () => void;
}

function EventCollabSection({ eventId, isOwner, ownerUserId, onRefresh }: { eventId: number; isOwner: boolean; ownerUserId?: number; onRefresh?: () => void }) {
  const qc = useQueryClient();
  const { user } = useAuth();
  const [expanded, setExpanded] = useState(false);
  const [transferOpen, setTransferOpen] = useState(false);

  const { data: collaborators = [], isLoading: collabLoading } = useQuery({
    queryKey: queryKeys.eventCollaborators(eventId),
    queryFn: () => calendarCollabApi.listCollaborators(eventId),
    enabled: expanded,
  });
  const { data: comments = [], isLoading: commentsLoading } = useQuery({
    queryKey: queryKeys.eventComments(eventId),
    queryFn: () => calendarCollabApi.listComments(eventId),
    enabled: expanded,
  });
  const { data: usersData } = useQuery({
    queryKey: queryKeys.projectSelectableUsers(),
    queryFn: () => projectsApi.listSelectableUsers(),
    enabled: expanded && isOwner,
  });

  if (!expanded) {
    return (
      <div className="flex items-center gap-2">
        <button onClick={() => setExpanded(true)} className="text-xs text-blue-600 hover:underline">
          展开协作详情
        </button>
        {isOwner && (
          <button onClick={() => { setExpanded(true); setTransferOpen(true); }} className="text-xs text-orange-600 hover:underline">
            转移负责人
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-2 pt-2 border-t">
      {isOwner && (
        <button onClick={() => setTransferOpen(true)} className="text-xs text-orange-600 hover:underline flex items-center gap-1">
          <ArrowRightLeft className="h-3 w-3" />
          转移负责人
        </button>
      )}
      <CollaboratorPanel
        collaborators={collaborators}
        isOwner={isOwner}
        ownerUserId={ownerUserId}
        ownerDisplayName={(usersData || []).find((u) => u.id === ownerUserId)?.display_name || undefined}
        allUsers={usersData || []}
        onAdd={async (userId) => { await calendarCollabApi.addCollaborator(eventId, { user_id: userId }); qc.invalidateQueries({ queryKey: queryKeys.eventCollaborators(eventId) }); }}
        onRemove={async (userId) => { await calendarCollabApi.removeCollaborator(eventId, userId); qc.invalidateQueries({ queryKey: queryKeys.eventCollaborators(eventId) }); }}
        loading={collabLoading}
      />
      <ActivityFeed
        title="日程评论"
        items={comments}
        canAdd={true}
        placeholder="添加评论或补充说明…"
        onAdd={async (content) => { await calendarCollabApi.addComment(eventId, { content }); qc.invalidateQueries({ queryKey: queryKeys.eventComments(eventId) }); }}
        onDelete={async (commentId) => { await calendarCollabApi.deleteComment(eventId, commentId); qc.invalidateQueries({ queryKey: queryKeys.eventComments(eventId) }); }}
        currentUserId={user?.id ?? null}
        isResourceOwner={isOwner}
        loading={commentsLoading}
      />
      <TransferOwnerDialog
        open={transferOpen}
        onClose={() => setTransferOpen(false)}
        onConfirm={async (targetUserId) => {
          await calendarCollabApi.transferOwner(eventId, { target_user_id: targetUserId });
          toast.success("日程负责人已转移");
          onRefresh?.();
        }}
        allUsers={usersData || []}
        currentOwnerUserId={ownerUserId}
        resourceLabel="日程"
      />
    </div>
  );
}

export function CalendarDrawer({ open, date, onClose, onRefresh }: CalendarDrawerProps) {
  const [formMode, setFormMode] = useState<"add" | "add_project" | "edit" | null>(null);
  const [editingEvent, setEditingEvent] = useState<CalendarEvent | null>(null);
  const qc = useQueryClient();

  const startParam = date ? `${date}T00:00:00` : undefined;
  const endParam = date ? `${date}T23:59:59` : undefined;

  const { data: events = [], refetch } = useQuery({
    queryKey: [...queryKeys.calendarEvents(), date, startParam, endParam],
    queryFn: () =>
      calendarApi.listEvents({
        start: startParam,
        end: endParam,
      }),
    enabled: open && !!date,
  });

  const { data: projects = [] } = useQuery({
    queryKey: queryKeys.projects(),
    queryFn: () => projectsApi.list(),
    enabled: open && (formMode === "add" || formMode === "add_project" || formMode === "edit"),
  });

  const handleCreatedOrUpdated = () => {
    setFormMode(null);
    setEditingEvent(null);
    qc.invalidateQueries({ queryKey: queryKeys.calendarEvents() });
    if (editingEvent?.id) {
      qc.invalidateQueries({ queryKey: queryKeys.calendarEventDetail(editingEvent.id) });
    }
    refetch();
    onRefresh();
  };

  const handleDelete = async (id: number) => {
    if (!confirm("确定删除该日程？")) return;
    await calendarApi.deleteEvent(id);
    qc.invalidateQueries({ queryKey: queryKeys.calendarEvents() });
    qc.removeQueries({ queryKey: queryKeys.calendarEventDetail(id) });
    refetch();
    onRefresh();
  };

  if (!open) return null;

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/40"
        onClick={onClose}
        aria-hidden
      />
      <div className="fixed top-0 right-0 z-50 h-full w-full max-w-md bg-background border-l border-border shadow-xl flex flex-col">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="text-lg font-semibold">
            {date ? `${date} 的日程` : "日程"}
          </h2>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="关闭">
            <X className="h-5 w-5" />
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {formMode ? (
            <div className="mb-4">
              <EventForm
                initial={formMode === "edit" ? editingEvent ?? undefined : undefined}
                defaultDate={date ?? undefined}
                defaultType={formMode === "add_project" ? "project" : "event"}
                projects={projects}
                onSubmit={async (payload) => {
                  if (formMode === "edit" && editingEvent) {
                    const updatePayload: CalendarEventUpdate = {
                      title: payload.title ?? undefined,
                      description: payload.description ?? undefined,
                      start_time: payload.start_time ?? undefined,
                      end_time: payload.end_time ?? undefined,
                      type: payload.type ?? undefined,
                      project_id: payload.project_id ?? undefined,
                    };
                    await calendarApi.updateEvent(editingEvent.id, updatePayload);
                  } else {
                    const createPayload: CalendarEventCreate = {
                      title: payload.title ?? "",
                      description: payload.description ?? undefined,
                      start_time:
                        "start_time" in payload && typeof payload.start_time === "string"
                          ? payload.start_time
                          : "",
                      end_time:
                        "end_time" in payload && typeof payload.end_time === "string"
                          ? payload.end_time
                          : "",
                      type: payload.type ?? "event",
                      project_id: payload.project_id ?? undefined,
                    };
                    await calendarApi.createEvent(createPayload);
                  }
                  handleCreatedOrUpdated();
                }}
                onCancel={() => {
                  setFormMode(null);
                  setEditingEvent(null);
                }}
              />
            </div>
          ) : (
            <>
              <div className="flex gap-2 mb-4">
                <Button
                  type="button"
                  size="sm"
                  className="gap-1"
                  onClick={() => setFormMode("add")}
                >
                  <Plus className="h-4 w-4" />
                  新增日程
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="gap-1"
                  onClick={() => setFormMode("add_project")}
                >
                  <Briefcase className="h-4 w-4" />
                  新增项目
                </Button>
              </div>

              {events.length === 0 ? (
                <p className="text-sm text-muted-foreground py-4">当日暂无日程</p>
              ) : (
                <ul className="space-y-2">
                  {events.map((ev) => {
                    const isOwner = ev.access_role === "owner" || !ev.access_role;
                    return (
                      <li key={ev.id} className="rounded-lg border border-border p-3 space-y-2">
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-1.5">
                              <p className="font-medium truncate">{ev.title}</p>
                              {ev.access_role && (
                                <span className={`text-[10px] px-1.5 py-0.5 rounded-full shrink-0 ${isOwner ? "bg-blue-100 text-blue-700" : "bg-green-100 text-green-700"}`}>
                                  {isOwner ? "我负责" : "协作"}
                                </span>
                              )}
                            </div>
                            <p className="text-xs text-muted-foreground mt-0.5">
                              {formatTime(ev.start_time)} - {formatTime(ev.end_time)}
                              {TYPE_LABEL[ev.type] && ` · ${TYPE_LABEL[ev.type]}`}
                            </p>
                            {ev.description && (
                              <p className="text-sm text-muted-foreground mt-1 line-clamp-2">
                                {ev.description}
                              </p>
                            )}
                          </div>
                          <div className="flex gap-1 shrink-0">
                            {isOwner && (
                              <>
                                <Button variant="ghost" size="icon" onClick={() => { setEditingEvent(ev); setFormMode("edit"); }} aria-label="编辑">
                                  <Pencil className="h-4 w-4" />
                                </Button>
                                <Button variant="ghost" size="icon" onClick={() => handleDelete(ev.id)} aria-label="删除" className="text-destructive">
                                  <Trash2 className="h-4 w-4" />
                                </Button>
                              </>
                            )}
                          </div>
                        </div>
                        <EventCollabSection eventId={ev.id} isOwner={isOwner} ownerUserId={ev.owner_user_id ?? undefined} onRefresh={() => { refetch(); onRefresh(); }} />
                      </li>
                    );
                  })}
                </ul>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}
