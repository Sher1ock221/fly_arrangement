"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { ArrowRightLeft, Briefcase, Calendar, Trash2, Users } from "lucide-react";
import { toast } from "sonner";
import {
  projectsApi,
  customersApi,
  projectCollabApi,
  calendarApi,
  ApiRequestError,
} from "@/lib/apiClient";
import { queryKeys } from "@/lib/queryKeys";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import DetailHeader from "@/components/detail/DetailHeader";
import DetailSkeleton from "@/components/detail/DetailSkeleton";
import DetailError from "@/components/detail/DetailError";
import InfoGrid from "@/components/detail/InfoGrid";
import RelatedResourceList from "@/components/detail/RelatedResourceList";
import RoleHint from "@/components/detail/RoleHint";
import CollaboratorPanel from "@/components/collaboration/CollaboratorPanel";
import ActivityFeed from "@/components/collaboration/ActivityFeed";
import TransferOwnerDialog from "@/components/collaboration/TransferOwnerDialog";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Label } from "@/components/ui/label";
import { ProjectForm } from "@/components/projects/ProjectForm";
import { formatLocalDate, formatLocalDateTime, parseDateTime } from "@/lib/time";

function formatDate(s: string | null | undefined): string {
  return formatLocalDate(s);
}

function formatDateTime(s: string | null | undefined): string {
  return formatLocalDateTime(s);
}

function toDatetimeLocalValue(s?: string | null) {
  if (!s) return "";
  const d = parseDateTime(s);
  if (!d) return "";
  if (Number.isNaN(d.getTime())) return "";
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${y}-${m}-${day}T${hh}:${mm}`;
}

function formatTimeRange(start: string, end: string): string {
  const fmt = (iso: string) => {
    return formatLocalDateTime(iso);
  };
  return `${fmt(start)} ~ ${fmt(end)}`;
}

const EVENT_TYPE_LABELS: Record<string, string> = {
  meeting: "会议",
  deadline: "截止",
  followup: "跟进",
  other: "其他",
};

export default function ProjectDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = typeof params.id === "string" ? parseInt(params.id, 10) : NaN;
  const qc = useQueryClient();
  const { user, loading: authLoading } = useAuth();
  const scopeKey = user?.id ?? null;
  const [transferOpen, setTransferOpen] = useState(false);
  const [transferInitiatorOpen, setTransferInitiatorOpen] = useState(false);
  const [linkCustomerOpen, setLinkCustomerOpen] = useState(false);
  const [linkCustomerKeyword, setLinkCustomerKeyword] = useState("");
  const [selectedCustomerIds, setSelectedCustomerIds] = useState<number[]>([]);
  const [editOpen, setEditOpen] = useState(false);

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: queryKeys.projectDetail(id, scopeKey),
    queryFn: () => projectsApi.get(id),
    enabled: Number.isInteger(id) && !authLoading,
    retry: (failureCount, err) => {
      if (err instanceof ApiRequestError && err.status === 403) return failureCount < 1;
      return failureCount < 2;
    },
  });
  const isOwner = data ? data.access_role === "owner" || !data.access_role : false;

  const { data: shareMembers, isLoading: collabLoading } = useQuery({
    queryKey: queryKeys.projectShareMembers(id),
    queryFn: () => projectCollabApi.getShareMembers(id),
    enabled: Number.isInteger(id),
  });
  const collaborators = shareMembers?.collaborators ?? [];

  const { data: updates = [], isLoading: updatesLoading } = useQuery({
    queryKey: queryKeys.projectUpdates(id),
    queryFn: () => projectCollabApi.listUpdates(id),
    enabled: Number.isInteger(id),
  });

  const { data: usersData } = useQuery({
    queryKey: queryKeys.projectSelectableUsers(),
    queryFn: projectsApi.listSelectableUsers,
    enabled: Number.isInteger(id),
  });
  const { data: customersList = [] } = useQuery({
    queryKey: queryKeys.customers(scopeKey),
    queryFn: customersApi.list,
  });

  const { data: calendarEvents = [] } = useQuery({
    queryKey: [...queryKeys.calendarEvents(), "project", id],
    queryFn: () => calendarApi.listEvents({ project_id: id }),
    enabled: Number.isInteger(id),
  });

  const deleteMutation = useMutation({
    mutationFn: () => projectsApi.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.projects(scopeKey) });
      toast.success("项目已删除");
      router.push("/projects");
    },
    onError: (e) => {
      toast.error(e instanceof Error ? e.message : "删除失败");
    },
  });
  const updateProjectMutation = useMutation({
    mutationFn: (body: Parameters<typeof projectsApi.update>[1]) => projectsApi.update(id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.projectDetail(id, scopeKey) });
      qc.invalidateQueries({ queryKey: queryKeys.projects(scopeKey) });
      setEditOpen(false);
      toast.success("项目信息已更新");
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "更新失败"),
  });
  const linkCustomersMutation = useMutation({
    mutationFn: (customerIds: number[]) => projectsApi.linkCustomers(id, customerIds),
    onSuccess: (resp) => {
      qc.invalidateQueries({ queryKey: queryKeys.projectDetail(id, scopeKey) });
      qc.invalidateQueries({ queryKey: queryKeys.projects(scopeKey) });
      qc.invalidateQueries({ queryKey: queryKeys.customers(scopeKey) });
      setLinkCustomerOpen(false);
      setSelectedCustomerIds([]);
      setLinkCustomerKeyword("");
      toast.success(`关联完成：新增 ${resp.linked_count}，已存在 ${resp.skipped_existing_count}`);
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "关联失败"),
  });
  const unlinkCustomerMutation = useMutation({
    mutationFn: (customerId: number) => projectsApi.unlinkCustomer(id, customerId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.projectDetail(id, scopeKey) });
      qc.invalidateQueries({ queryKey: queryKeys.projects(scopeKey) });
      qc.invalidateQueries({ queryKey: queryKeys.customers(scopeKey) });
      toast.success("已解除关联");
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "解除关联失败"),
  });

  const project = data ?? null;
  const linkedCustomerIds = useMemo(
    () => new Set((project?.related_customers ?? []).map((c) => c.id)),
    [project?.related_customers],
  );
  const linkableCustomers = useMemo(
    () =>
      (customersList ?? []).filter((c) => {
        if (linkedCustomerIds.has(c.id)) return false;
        const k = linkCustomerKeyword.trim().toLowerCase();
        if (!k) return true;
        return (
          (c.name || "").toLowerCase().includes(k) ||
          (c.company || "").toLowerCase().includes(k)
        );
      }),
    [customersList, linkedCustomerIds, linkCustomerKeyword],
  );

  useEffect(() => {
    if (!error) return;
    const status = error instanceof ApiRequestError ? error.status : undefined;
    console.error("[project-detail] query failed", {
      projectId: id,
      effectiveUserId: scopeKey,
      status,
      message: error instanceof Error ? error.message : String(error),
    });
  }, [error, id, scopeKey]);

  if (!Number.isInteger(id)) {
    return <DetailError backHref="/projects" backLabel="返回项目列表" message="无效的项目 ID" />;
  }

  if (authLoading || isLoading || (isFetching && !data)) {
    return <DetailSkeleton backHref="/projects" backLabel="返回项目列表" />;
  }

  if (error) {
    const status = error instanceof ApiRequestError ? error.status : undefined;
    const forbidden = status === 403;
    const notFound = status === 404;
    return (
      <DetailError
        backHref="/projects"
        backLabel="返回项目列表"
        message={
          forbidden
            ? "无权查看该项目，或该项目不在你的账号可见范围内。"
            : notFound
              ? "项目不存在或已删除。"
              : (error instanceof Error ? error.message : "加载失败")
        }
        action={
          <Button size="sm" variant="outline" onClick={() => void refetch()}>
            重试
          </Button>
        }
      />
    );
  }

  if (!project) {
    return (
      <DetailError
        backHref="/projects"
        backLabel="返回项目列表"
        message="项目不存在或已删除。"
      />
    );
  }

  return (
    <div className="flex flex-col h-full bg-muted/20">
      <DetailHeader
        backHref="/projects"
        backLabel="返回项目列表"
        title={project.name}
        subtitle={project.project_no ?? undefined}
        accessRole={project.access_role}
        actions={
          isOwner ? (
            <>
              <Button
                variant="outline"
                size="sm"
                className="text-xs"
                onClick={() => setEditOpen(true)}
              >
                编辑项目信息
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setTransferOpen(true)}
                className="gap-1.5 text-xs"
              >
                <ArrowRightLeft className="h-3.5 w-3.5" />
                更换负责人
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setTransferInitiatorOpen(true)}
                className="gap-1.5 text-xs"
              >
                <ArrowRightLeft className="h-3.5 w-3.5" />
                转移发起人
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="text-muted-foreground hover:text-destructive"
                title="删除项目"
                disabled={deleteMutation.isPending}
                onClick={() => {
                  if (confirm("确定删除该项目？删除后不可恢复。")) {
                    deleteMutation.mutate();
                  }
                }}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </>
          ) : undefined
        }
      />

      <div className="flex-1 overflow-auto p-4 md:p-8 space-y-6">
        {project.access_role === "collaborator" && (
          <RoleHint accessRole="collaborator" />
        )}

        <InfoGrid
          title="项目信息"
          icon={<Briefcase className="h-4 w-4" />}
          fields={[
            { label: "项目编号", value: project.project_no },
            { label: "发起人", value: project.initiator_display_name || "未设置" },
            { label: "开始时间", value: formatDateTime(project.start_time ?? project.start_date) },
            { label: "截止时间", value: formatDateTime(project.deadline_at ?? project.deadline) },
            { label: "负责人", value: project.owner },
            { label: "更新时间", value: formatDate(project.update_date) },
          ]}
        />

        <div className="rounded-xl border border-border bg-card shadow-sm p-4 md:p-6 space-y-4">
          <h3 className="text-sm font-semibold text-foreground">项目内容</h3>
          <div className="grid grid-cols-1 gap-4">
            <div className="rounded-lg border border-border/70 bg-muted/20 p-3">
              <p className="text-xs font-medium text-muted-foreground mb-1">项目目标</p>
              <p className="text-sm leading-6 whitespace-pre-wrap break-words text-foreground">{project.goal || "未填写"}</p>
            </div>
            <div className="rounded-lg border border-border/70 bg-muted/20 p-3">
              <p className="text-xs font-medium text-muted-foreground mb-1">项目内需</p>
              <p className="text-sm leading-6 whitespace-pre-wrap break-words text-foreground">{project.requirements || "未填写"}</p>
            </div>
            <div className="rounded-lg border border-border/70 bg-primary/[0.04] p-3">
              <p className="text-xs font-medium text-muted-foreground mb-1">项目进展</p>
              <p className="text-sm leading-6 whitespace-pre-wrap break-words text-foreground">{project.progress_text || "未填写"}</p>
            </div>
          </div>
        </div>

        <div className="rounded-xl border border-border bg-card shadow-sm overflow-hidden">
          <div className="pb-3 border-b border-border/60 flex flex-row items-center justify-between p-4">
            <div className="text-sm font-semibold flex items-center gap-2 text-foreground">
              <Users className="h-4 w-4" />
              关联客户
            </div>
            {isOwner && (
              <Button size="sm" variant="outline" onClick={() => setLinkCustomerOpen(true)}>
                关联已有客户
              </Button>
            )}
          </div>
          <div className="p-4 md:p-6">
            {(project.related_customers ?? []).length === 0 ? (
              <p className="text-sm text-muted-foreground py-6 text-center">暂无关联客户</p>
            ) : (
              <ul className="divide-y divide-border/60">
                {(project.related_customers ?? []).map((c) => (
                  <li key={c.id}>
                    <a
                      href={`/customers/${c.id}`}
                      className="flex items-center gap-3 py-2.5 px-1 rounded-md hover:bg-muted/50 transition-colors group"
                    >
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-foreground truncate group-hover:text-primary transition-colors">
                          {c.name}
                        </p>
                        <p className="text-xs text-muted-foreground truncate mt-0.5">
                          {c.company || "—"}
                        </p>
                      </div>
                      <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary shrink-0">
                        {c.access_role === "owner" ? "我负责" : "协作中"}
                      </span>
                      {isOwner && (
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          className="text-xs text-muted-foreground hover:text-destructive"
                          onClick={(e) => {
                            e.preventDefault();
                            if (confirm("确定解除该客户与当前项目的关联吗？")) {
                              unlinkCustomerMutation.mutate(c.id);
                            }
                          }}
                        >
                          解除关联
                        </Button>
                      )}
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        <RelatedResourceList
          title="关联日程"
          icon={<Calendar className="h-4 w-4" />}
          items={calendarEvents.map((ev) => ({
            id: ev.id,
            href: "#",
            title: ev.title,
            subtitle: formatTimeRange(ev.start_time, ev.end_time),
            badge: EVENT_TYPE_LABELS[ev.type] ?? ev.type,
          }))}
          emptyText="暂无关联日程"
        />

        <CollaboratorPanel
          collaborators={collaborators}
          initiator={shareMembers?.initiator}
          legacyMembers={shareMembers?.legacy_members ?? []}
          isOwner={isOwner}
          ownerUserId={project.owner_user_id ?? undefined}
          ownerDisplayName={project.owner ?? undefined}
          allUsers={usersData || []}
          onAdd={async (userId) => {
            await projectCollabApi.addCollaborator(id, { user_id: userId });
            qc.invalidateQueries({ queryKey: queryKeys.projectShareMembers(id) });
            qc.invalidateQueries({ queryKey: queryKeys.projectDetail(id, scopeKey) });
            qc.invalidateQueries({ queryKey: queryKeys.projects(scopeKey) });
          }}
          onRemove={async (userId) => {
            await projectCollabApi.removeCollaborator(id, userId);
            qc.invalidateQueries({ queryKey: queryKeys.projectShareMembers(id) });
            qc.invalidateQueries({ queryKey: queryKeys.projectDetail(id, scopeKey) });
            qc.invalidateQueries({ queryKey: queryKeys.projects(scopeKey) });
          }}
          onCleanupLegacy={async (legacyKey) => {
            await projectCollabApi.cleanupLegacyMember(id, legacyKey);
            qc.invalidateQueries({ queryKey: queryKeys.projectShareMembers(id) });
            qc.invalidateQueries({ queryKey: queryKeys.projectDetail(id, scopeKey) });
          }}
          loading={collabLoading}
        />

        <ActivityFeed
          title="项目动态"
          subtitle="项目进度、备注与需求记录"
          items={updates}
          canAdd={true}
          showTypeSelect={true}
          placeholder="添加进度更新、备注或需求补充…"
          onAdd={async (content, updateType) => {
            await projectCollabApi.addUpdate(id, {
              content,
              update_type: updateType || "note",
            });
            qc.invalidateQueries({ queryKey: queryKeys.projectUpdates(id) });
          }}
          onDelete={async (updateId) => {
            await projectCollabApi.deleteUpdate(id, updateId);
            qc.invalidateQueries({ queryKey: queryKeys.projectUpdates(id) });
          }}
          currentUserId={user?.id ?? null}
          isResourceOwner={isOwner}
          loading={updatesLoading}
        />
      </div>

      <TransferOwnerDialog
        open={transferOpen}
        onClose={() => setTransferOpen(false)}
        onConfirm={async (targetUserId) => {
          await projectCollabApi.transferOwner(id, {
            target_user_id: targetUserId,
          });
          toast.success("负责人已更新");
          qc.invalidateQueries({ queryKey: queryKeys.projectDetail(id, scopeKey) });
          qc.invalidateQueries({ queryKey: queryKeys.projectShareMembers(id) });
          qc.invalidateQueries({ queryKey: queryKeys.projects(scopeKey) });
        }}
        allUsers={usersData || []}
        currentOwnerUserId={project.owner_user_id ?? undefined}
        resourceLabel="项目"
      />
      <TransferOwnerDialog
        open={transferInitiatorOpen}
        onClose={() => setTransferInitiatorOpen(false)}
        onConfirm={async (targetUserId) => {
          await projectCollabApi.transferInitiator(id, {
            target_user_id: targetUserId,
          });
          toast.success("发起人已转移");
          qc.invalidateQueries({ queryKey: queryKeys.projectDetail(id, scopeKey) });
          qc.invalidateQueries({ queryKey: queryKeys.projectShareMembers(id) });
          qc.invalidateQueries({ queryKey: queryKeys.projects(scopeKey) });
        }}
        allUsers={usersData || []}
        currentOwnerUserId={project.initiator_user_id ?? undefined}
        resourceLabel="项目发起人"
      />

      <Dialog
        open={editOpen}
        onOpenChange={setEditOpen}
      >
        <DialogContent className="w-[min(96vw,1100px)] max-w-none max-h-[92vh]">
          <DialogHeader>
            <DialogTitle>编辑项目信息</DialogTitle>
          </DialogHeader>
          <ProjectForm
            users={usersData || []}
            customers={customersList}
            initial={{
              project_no: project.project_no,
              name: project.name,
              owner_user_id: project.owner_user_id ?? null,
              start_time: project.start_time ?? project.start_date,
              deadline_at: project.deadline_at ?? project.deadline,
              goal: project.goal,
              requirements: project.requirements,
              progress_text: project.progress_text,
              customer_ids: project.related_customers?.map((c) => c.id) ?? [],
            }}
            submitText="保存"
            pending={updateProjectMutation.isPending}
            onCancel={() => setEditOpen(false)}
            onSubmit={(payload) => updateProjectMutation.mutate(payload)}
          />
        </DialogContent>
      </Dialog>

      <Dialog
        open={linkCustomerOpen}
        onOpenChange={(open) => {
          if (!open) {
            setLinkCustomerOpen(false);
            setSelectedCustomerIds([]);
            setLinkCustomerKeyword("");
          }
        }}
      >
        <DialogContent className="max-h-[90vh] overflow-y-auto max-w-xl">
          <DialogHeader>
            <DialogTitle>关联已有客户</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <Input
              placeholder="搜索客户名称 / 公司"
              value={linkCustomerKeyword}
              onChange={(e) => setLinkCustomerKeyword(e.target.value)}
            />
            <ScrollArea className="h-72 rounded border border-border">
              <div className="p-2 space-y-1.5">
                {linkableCustomers.length === 0 ? (
                  <p className="text-sm text-muted-foreground p-2">没有可关联的客户</p>
                ) : (
                  linkableCustomers.map((c) => (
                    <label key={c.id} className="flex items-center gap-2 rounded px-2 py-2 hover:bg-muted/50">
                      <input
                        type="checkbox"
                        checked={selectedCustomerIds.includes(c.id)}
                        onChange={(e) => {
                          if (e.target.checked) setSelectedCustomerIds((prev) => [...prev, c.id]);
                          else setSelectedCustomerIds((prev) => prev.filter((x) => x !== c.id));
                        }}
                        className="h-4 w-4"
                      />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium truncate">{c.name}</p>
                        <p className="text-xs text-muted-foreground truncate">{c.company || "—"}</p>
                      </div>
                      <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                        {c.access_role === "owner" ? "我负责" : "协作中"}
                      </span>
                    </label>
                  ))
                )}
              </div>
            </ScrollArea>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setLinkCustomerOpen(false)}>
              取消
            </Button>
            <Button
              disabled={selectedCustomerIds.length === 0 || linkCustomersMutation.isPending}
              onClick={() => linkCustomersMutation.mutate(selectedCustomerIds)}
            >
              {linkCustomersMutation.isPending ? "关联中…" : "确认关联"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
