"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { CalendarEvent, CalendarEventCreate, CalendarEventUpdate } from "@/types/calendar";
import type { Project } from "@/types/project";
import { cn } from "@/lib/utils";

type EventType = "event" | "project" | "meeting" | "task";

function toLocalISO(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:00`;
}

export interface EventFormProps {
  initial?: CalendarEvent | null;
  defaultDate?: string;
  defaultType?: EventType;
  projects?: Project[];
  onSubmit: (data: CalendarEventCreate | CalendarEventUpdate) => void;
  onCancel: () => void;
}

export function EventForm({
  initial,
  defaultDate,
  defaultType = "event",
  projects = [],
  onSubmit,
  onCancel,
}: EventFormProps) {
  const [title, setTitle] = useState(initial?.title ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [startTime, setStartTime] = useState(
    initial?.start_time
      ? toLocalISO(new Date(initial.start_time))
      : defaultDate
        ? `${defaultDate}T09:00:00`
        : toLocalISO(new Date())
  );
  const [endTime, setEndTime] = useState(
    initial?.end_time
      ? toLocalISO(new Date(initial.end_time))
      : defaultDate
        ? `${defaultDate}T10:00:00`
        : (() => {
            const d = new Date();
            d.setHours(d.getHours() + 1);
            return toLocalISO(d);
          })()
  );
  const [type, setType] = useState<EventType>((initial?.type as EventType) ?? defaultType);
  const [projectId, setProjectId] = useState<string>(initial?.project_id != null ? String(initial.project_id) : "");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    if (initial) {
      onSubmit({
        title: title.trim(),
        description: description.trim() || null,
        start_time: startTime,
        end_time: endTime,
        type,
        project_id: projectId ? parseInt(projectId, 10) : null,
      });
    } else {
      onSubmit({
        title: title.trim(),
        description: description.trim() || null,
        start_time: startTime,
        end_time: endTime,
        type,
        project_id: projectId ? parseInt(projectId, 10) : null,
      });
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <Label htmlFor="title">标题</Label>
        <Input
          id="title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="日程标题"
          required
          className="mt-1"
        />
      </div>
      <div>
        <Label htmlFor="desc">描述</Label>
        <textarea
          id="desc"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="可选"
          className={cn(
            "mt-1 flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          )}
        />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <Label>开始时间</Label>
          <Input
            type="datetime-local"
            value={startTime.slice(0, 16)}
            onChange={(e) => setStartTime(e.target.value + ":00")}
            className="mt-1"
          />
        </div>
        <div>
          <Label>结束时间</Label>
          <Input
            type="datetime-local"
            value={endTime.slice(0, 16)}
            onChange={(e) => setEndTime(e.target.value + ":00")}
            className="mt-1"
          />
        </div>
      </div>
      <div>
        <Label>类型</Label>
        <select
          value={type}
          onChange={(e) => setType(e.target.value as EventType)}
          className="mt-1 flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
        >
          <option value="event">日程</option>
          <option value="project">项目</option>
          <option value="meeting">会议</option>
          <option value="task">任务</option>
        </select>
      </div>
      {projects.length > 0 && (
        <div>
          <Label>关联项目</Label>
          <select
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            className="mt-1 flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
          >
            <option value="">不关联</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} {p.project_no ? `(${p.project_no})` : ""}
              </option>
            ))}
          </select>
        </div>
      )}
      <div className="flex gap-2 pt-2">
        <Button type="submit">{initial ? "保存" : "创建"}</Button>
        <Button type="button" variant="outline" onClick={onCancel}>
          取消
        </Button>
      </div>
    </form>
  );
}
