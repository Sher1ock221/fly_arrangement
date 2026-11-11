"use client";

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { UserSelect, type SelectableUser } from "@/components/users/UserSelect";
import type { Customer } from "@/types/customer";
import type { ProjectCreate, ProjectUpdate } from "@/types/project";

export type ProjectFormPayload = ProjectCreate & ProjectUpdate;

type ProjectFormInitial = {
  project_no?: string | null;
  name?: string | null;
  owner_user_id?: number | null;
  start_time?: string | null;
  deadline_at?: string | null;
  goal?: string | null;
  requirements?: string | null;
  progress_text?: string | null;
  customer_ids?: number[];
};

function toDatetimeLocalValue(s?: string | null) {
  if (!s) return "";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return "";
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${y}-${m}-${day}T${hh}:${mm}`;
}

type Props = {
  initial?: ProjectFormInitial;
  users: SelectableUser[];
  customers: Customer[];
  submitText: string;
  pending?: boolean;
  showProjectNo?: boolean;
  onCancel: () => void;
  onSubmit: (payload: ProjectFormPayload) => void;
};

export function ProjectForm({
  initial,
  users,
  customers,
  submitText,
  pending,
  showProjectNo = true,
  onCancel,
  onSubmit,
}: Props) {
  const [ownerUserId, setOwnerUserId] = useState<number | null>(initial?.owner_user_id ?? null);
  const [customerIds, setCustomerIds] = useState<number[]>(initial?.customer_ids ?? []);
  const owner = useMemo(() => users.find((u) => u.id === ownerUserId) ?? null, [users, ownerUserId]);

  return (
    <form
      className="flex max-h-[78vh] flex-col"
      onSubmit={(e) => {
        e.preventDefault();
        const form = e.currentTarget;
        const name = (form.elements.namedItem("name") as HTMLInputElement).value?.trim();
        if (!name || ownerUserId == null) return;
        onSubmit({
          project_no: showProjectNo
            ? ((form.elements.namedItem("project_no") as HTMLInputElement | null)?.value?.trim() || null)
            : undefined,
          name,
          owner_user_id: ownerUserId,
          owner: owner ? (owner.display_name || owner.username) : null,
          start_time: (form.elements.namedItem("start_time") as HTMLInputElement).value
            ? new Date((form.elements.namedItem("start_time") as HTMLInputElement).value).toISOString()
            : null,
          deadline_at: (form.elements.namedItem("deadline_at") as HTMLInputElement).value
            ? new Date((form.elements.namedItem("deadline_at") as HTMLInputElement).value).toISOString()
            : null,
          goal: (form.elements.namedItem("goal") as HTMLTextAreaElement).value || null,
          requirements: (form.elements.namedItem("requirements") as HTMLTextAreaElement).value || null,
          progress_text: (form.elements.namedItem("progress_text") as HTMLTextAreaElement).value || null,
          customer_ids: customerIds,
        });
      }}
    >
      <div className="flex-1 space-y-5 overflow-y-auto pr-1">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {showProjectNo ? (
            <div className="space-y-2">
              <Label htmlFor="project_no">项目编号</Label>
              <Input
                id="project_no"
                name="project_no"
                defaultValue={initial?.project_no ?? ""}
                placeholder="如 P001，不填则自动生成"
              />
            </div>
          ) : null}
          <div className="space-y-2">
            <Label htmlFor="name">项目名称 *</Label>
            <Input id="name" name="name" defaultValue={initial?.name ?? ""} required placeholder="请输入项目名称" />
          </div>
          <div className="space-y-2 lg:col-span-2">
            <Label>负责人 *</Label>
            <UserSelect users={users} value={ownerUserId} onChange={setOwnerUserId} />
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="start_time">开始时间</Label>
            <Input id="start_time" name="start_time" type="datetime-local" defaultValue={toDatetimeLocalValue(initial?.start_time)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="deadline_at">截止时间</Label>
            <Input id="deadline_at" name="deadline_at" type="datetime-local" defaultValue={toDatetimeLocalValue(initial?.deadline_at)} />
          </div>
        </div>

        <div className="space-y-2">
          <Label htmlFor="goal">项目目标</Label>
          <textarea id="goal" name="goal" defaultValue={initial?.goal ?? ""} className="w-full min-h-[120px] rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring" />
        </div>
        <div className="space-y-2">
          <Label htmlFor="requirements">项目内需</Label>
          <textarea id="requirements" name="requirements" defaultValue={initial?.requirements ?? ""} className="w-full min-h-[120px] rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring" />
        </div>
        <div className="space-y-2">
          <Label htmlFor="progress_text">项目进展</Label>
          <textarea id="progress_text" name="progress_text" defaultValue={initial?.progress_text ?? ""} className="w-full min-h-[120px] rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring" />
        </div>

        <div className="space-y-2">
          <Label>关联客户</Label>
          <ScrollArea className="max-h-48 rounded border border-border bg-muted/30 p-2">
            <div className="space-y-1.5">
              {customers.length === 0 ? (
                <p className="text-muted-foreground text-sm">暂无客户，请先在客户管理中添加</p>
              ) : (
                customers.map((c) => (
                  <label key={c.id} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 hover:bg-muted/50">
                    <input
                      type="checkbox"
                      checked={customerIds.includes(c.id)}
                      onChange={(ev) => {
                        if (ev.target.checked) setCustomerIds((prev) => [...prev, c.id]);
                        else setCustomerIds((prev) => prev.filter((id) => id !== c.id));
                      }}
                      className="h-4 w-4 rounded border-border"
                    />
                    <span className="text-sm">{c.company ? `${c.name} / ${c.company}` : c.name}</span>
                  </label>
                ))
              )}
            </div>
          </ScrollArea>
        </div>
      </div>
      <div className="mt-4 flex justify-end gap-2 border-t pt-4">
        <Button type="button" variant="outline" onClick={onCancel}>取消</Button>
        <Button type="submit" disabled={pending || ownerUserId == null}>{submitText}</Button>
      </div>
    </form>
  );
}

