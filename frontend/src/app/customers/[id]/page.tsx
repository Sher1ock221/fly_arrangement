"use client";

import { useState, useEffect, useMemo } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  User,
  Briefcase,
  MessageSquare,
  Plus,
  Pencil,
  Trash2,
  ArrowRightLeft,
  Link2,
} from "lucide-react";
import { toast } from "sonner";
import {
  customersApi,
  projectsApi,
  customerCollabApi,
  getStoredToken,
  ApiRequestError,
} from "@/lib/apiClient";
import { useAuth } from "@/contexts/AuthContext";
import { queryKeys } from "@/lib/queryKeys";
import type {
  Customer,
  CustomerInteraction,
  CustomerInteractionCreate,
} from "@/types/customer";
import type { ProjectCreate } from "@/types/project";

import DetailHeader from "@/components/detail/DetailHeader";
import DetailSkeleton from "@/components/detail/DetailSkeleton";
import DetailError from "@/components/detail/DetailError";
import InfoGrid from "@/components/detail/InfoGrid";
import RoleHint from "@/components/detail/RoleHint";
import CollaboratorPanel from "@/components/collaboration/CollaboratorPanel";
import ActivityFeed from "@/components/collaboration/ActivityFeed";
import TransferOwnerDialog from "@/components/collaboration/TransferOwnerDialog";

import { ImportanceStars } from "@/components/customer/ImportanceStars";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { formatLocalDateTime, parseDateTime } from "@/lib/time";

/* ── helpers ─────────────────────────────────────────────── */

function formatDateTime(s: string | null | undefined): string {
  return formatLocalDateTime(s);
}

function sourceLabel(source: string | null | undefined): string {
  const map: Record<string, string> = {
    manual: "手动录入",
    ai: "AI归档",
    feishu: "飞书归档",
    web: "Web录入",
  };
  return (source && map[source]) || (source ?? "—");
}

function toDatetimeLocal(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = parseDateTime(iso);
  if (!d) return "";
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  const h = String(d.getHours()).padStart(2, "0");
  const min = String(d.getMinutes()).padStart(2, "0");
  return `${y}-${m}-${day}T${h}:${min}`;
}

function fromDatetimeLocal(v: string): string | null {
  if (!v?.trim()) return null;
  try {
    return new Date(v).toISOString();
  } catch {
    return null;
  }
}

/* ── collaboration sub-component ─────────────────────────── */

function CustomerCollabSection({
  customerId,
  customer,
}: {
  customerId: number;
  customer: { access_role?: string; owner_user_id?: number | null };
}) {
  const qc = useQueryClient();
  const { user } = useAuth();
  const isOwner = customer.access_role === "owner" || !customer.access_role;

  const { data: collaborators = [], isLoading: collabLoading } = useQuery({
    queryKey: queryKeys.customerCollaborators(customerId),
    queryFn: () => customerCollabApi.listCollaborators(customerId),
  });
  const { data: followups = [], isLoading: followupsLoading } = useQuery({
    queryKey: queryKeys.customerFollowups(customerId),
    queryFn: () => customerCollabApi.listFollowups(customerId),
  });
  const { data: usersData } = useQuery({
    queryKey: queryKeys.projectSelectableUsers(),
    queryFn: () => projectsApi.listSelectableUsers(),
    enabled: isOwner,
  });

  return (
    <>
      <CollaboratorPanel
        collaborators={collaborators}
        isOwner={isOwner}
        ownerUserId={customer.owner_user_id ?? undefined}
        ownerDisplayName={(usersData || []).find((u) => u.id === customer.owner_user_id)?.display_name || undefined}
        allUsers={usersData || []}
        onAdd={async (userId) => {
          await customerCollabApi.addCollaborator(customerId, {
            user_id: userId,
          });
          qc.invalidateQueries({
            queryKey: queryKeys.customerCollaborators(customerId),
          });
        }}
        onRemove={async (userId) => {
          await customerCollabApi.removeCollaborator(customerId, userId);
          qc.invalidateQueries({
            queryKey: queryKeys.customerCollaborators(customerId),
          });
        }}
        loading={collabLoading}
      />
      <ActivityFeed
        title="跟进记录"
        subtitle="记录沟通与协作进展"
        items={followups}
        canAdd={true}
        placeholder="记录本次沟通内容、客户反馈或下一步计划…"
        onAdd={async (content) => {
          await customerCollabApi.addFollowup(customerId, { content });
          qc.invalidateQueries({
            queryKey: queryKeys.customerFollowups(customerId),
          });
        }}
        onDelete={async (followupId) => {
          await customerCollabApi.deleteFollowup(customerId, followupId);
          qc.invalidateQueries({
            queryKey: queryKeys.customerFollowups(customerId),
          });
        }}
        currentUserId={user?.id ?? null}
        isResourceOwner={isOwner}
        loading={followupsLoading}
      />
    </>
  );
}

/* ── main page component ─────────────────────────────────── */

export default function CustomerDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = typeof params.id === "string" ? parseInt(params.id, 10) : NaN;
  const queryClient = useQueryClient();
  const { user, loading: authLoading } = useAuth();
  const scopeKey = user?.id ?? null;

  /* ── queries ── */

  const {
    data,
    isLoading,
    isFetching,
    error,
    refetch,
  } = useQuery({
    queryKey: queryKeys.customerDetail(id, scopeKey),
    queryFn: () => customersApi.get(id),
    enabled: Number.isInteger(id) && !authLoading,
    retry: (failureCount, err) => {
      if (err instanceof ApiRequestError && err.status === 403) return failureCount < 1;
      return failureCount < 2;
    },
  });

  const { data: customersList = [] } = useQuery({
    queryKey: queryKeys.customers(scopeKey),
    queryFn: customersApi.list,
  });
  const { data: projectsList = [] } = useQuery({
    queryKey: queryKeys.projects(scopeKey),
    queryFn: projectsApi.list,
  });

  const isOwnerForTransfer =
    data?.access_role === "owner" || !data?.access_role;

  const { data: transferUsers } = useQuery({
    queryKey: queryKeys.projectSelectableUsers(),
    queryFn: () => projectsApi.listSelectableUsers(),
    enabled: !!data && isOwnerForTransfer,
  });

  /* ── mutations ── */

  const invalidateDetail = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.customerDetail(id, scopeKey) });

  const createProjectMutation = useMutation({
    mutationFn: (body: ProjectCreate) => projectsApi.create(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.customerDetail(id, scopeKey) });
      queryClient.invalidateQueries({ queryKey: queryKeys.projects(scopeKey) });
      setProjectFormOpen(false);
      toast.success("项目已创建");
    },
    onError: (e) =>
      toast.error(e instanceof Error ? e.message : "创建项目失败"),
  });

  const createMutation = useMutation({
    mutationFn: (body: CustomerInteractionCreate) =>
      customersApi.createInteraction(id, body),
    onSuccess: () => {
      invalidateDetail();
      setFormOpen(false);
      toast.success("沟通记录已添加");
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "添加失败"),
  });

  const updateMutation = useMutation({
    mutationFn: ({
      interactionId,
      body,
    }: {
      interactionId: number;
      body: CustomerInteractionCreate;
    }) => customersApi.updateInteraction(id, interactionId, body),
    onSuccess: () => {
      invalidateDetail();
      setFormOpen(false);
      setEditingInteraction(null);
      toast.success("沟通记录已更新");
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "更新失败"),
  });

  const deleteMutation = useMutation({
    mutationFn: (interactionId: number) =>
      customersApi.deleteInteraction(id, interactionId),
    onSuccess: () => {
      invalidateDetail();
      toast.success("沟通记录已删除");
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "删除失败"),
  });

  const deleteCustomerMutation = useMutation({
    mutationFn: () => customersApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.customers(scopeKey) });
      toast.success("客户已删除");
      router.push("/customers");
    },
    onError: (e) =>
      toast.error(e instanceof Error ? e.message : "删除客户失败"),
  });

  /* ── local state ── */

  const [formOpen, setFormOpen] = useState(false);
  const [editingInteraction, setEditingInteraction] =
    useState<CustomerInteraction | null>(null);
  const [projectFormOpen, setProjectFormOpen] = useState(false);
  const [linkProjectOpen, setLinkProjectOpen] = useState(false);
  const [linkProjectKeyword, setLinkProjectKeyword] = useState("");
  const [selectedProjectIds, setSelectedProjectIds] = useState<number[]>([]);
  const [projectCustomerIds, setProjectCustomerIds] = useState<number[]>([]);
  const [transferOpen, setTransferOpen] = useState(false);
  const [expandedRawInputId, setExpandedRawInputId] = useState<number | null>(
    null,
  );

  const [formMeetingTime, setFormMeetingTime] = useState("");
  const [formTalkSummary, setFormTalkSummary] = useState("");
  const [formCooperationDirection, setFormCooperationDirection] = useState("");
  const [formCooperationIntent, setFormCooperationIntent] = useState("");
  const [formNextPlan, setFormNextPlan] = useState("");
  const [formSpecificNeeds, setFormSpecificNeeds] = useState("");
  const [formImportance, setFormImportance] = useState("");

  const linkProjectsMutation = useMutation({
    mutationFn: (projectIds: number[]) => customersApi.linkProjects(id, projectIds),
    onSuccess: (resp) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.customerDetail(id, scopeKey) });
      queryClient.invalidateQueries({ queryKey: queryKeys.projects(scopeKey) });
      queryClient.invalidateQueries({ queryKey: queryKeys.customers(scopeKey) });
      setLinkProjectOpen(false);
      setSelectedProjectIds([]);
      setLinkProjectKeyword("");
      toast.success(`关联完成：新增 ${resp.linked_count}，已存在 ${resp.skipped_existing_count}`);
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "关联失败"),
  });

  const unlinkProjectMutation = useMutation({
    mutationFn: (projectId: number) => customersApi.unlinkProject(id, projectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.customerDetail(id, scopeKey) });
      queryClient.invalidateQueries({ queryKey: queryKeys.projects(scopeKey) });
      queryClient.invalidateQueries({ queryKey: queryKeys.customers(scopeKey) });
      toast.success("已解除关联");
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "解除关联失败"),
  });

  /* ── effects ── */

  useEffect(() => {
    if (!formOpen) return;
    if (editingInteraction) {
      setFormMeetingTime(toDatetimeLocal(editingInteraction.meeting_time));
      setFormTalkSummary(editingInteraction.talk_summary ?? "");
      setFormCooperationDirection(
        editingInteraction.cooperation_direction ?? "",
      );
      setFormCooperationIntent(editingInteraction.cooperation_intent ?? "");
      setFormNextPlan(editingInteraction.next_cooperation_plan ?? "");
      setFormSpecificNeeds(editingInteraction.specific_needs ?? "");
      setFormImportance(
        editingInteraction.importance != null
          ? String(editingInteraction.importance)
          : "",
      );
    } else {
      setFormMeetingTime("");
      setFormTalkSummary("");
      setFormCooperationDirection("");
      setFormCooperationIntent("");
      setFormNextPlan("");
      setFormSpecificNeeds("");
      setFormImportance("");
    }
  }, [formOpen, editingInteraction]);

  /* ── derived ── */

  const isEdit = editingInteraction != null;
  const formTitle = isEdit ? "编辑沟通记录" : "新增沟通记录";

  const openCreate = () => {
    setEditingInteraction(null);
    setFormOpen(true);
  };
  const openEdit = (interaction: CustomerInteraction) => {
    setEditingInteraction(interaction);
    setFormOpen(true);
  };
  const closeForm = () => {
    setFormOpen(false);
    setEditingInteraction(null);
  };

  const handleSubmitInteraction = (e: React.FormEvent) => {
    e.preventDefault();
    const body: CustomerInteractionCreate = {
      meeting_time: fromDatetimeLocal(formMeetingTime),
      talk_summary: formTalkSummary.trim() || null,
      cooperation_direction: formCooperationDirection.trim() || null,
      cooperation_intent: formCooperationIntent.trim() || null,
      next_cooperation_plan: formNextPlan.trim() || null,
      specific_needs: formSpecificNeeds.trim() || null,
      importance: formImportance ? parseInt(formImportance, 10) : null,
      source: "manual",
    };
    if (isEdit && editingInteraction) {
      updateMutation.mutate({ interactionId: editingInteraction.id, body });
    } else {
      createMutation.mutate(body);
    }
  };

  const safeCustomer = data ?? null;
  const projects = useMemo(() => safeCustomer?.projects ?? [], [safeCustomer?.projects]);
  const interactions = safeCustomer?.interactions ?? [];
  const isOwner = safeCustomer ? (safeCustomer.access_role === "owner" || !safeCustomer.access_role) : false;
  const linkedProjectIds = useMemo(() => new Set(projects.map((p) => p.id)), [projects]);
  const linkableProjects = useMemo(
    () =>
      (projectsList ?? []).filter((p) => {
        if (linkedProjectIds.has(p.id)) return false;
        const k = linkProjectKeyword.trim().toLowerCase();
        if (!k) return true;
        return (
          (p.name || "").toLowerCase().includes(k) ||
          (p.project_no || "").toLowerCase().includes(k) ||
          (p.owner || "").toLowerCase().includes(k)
        );
      }),
    [projectsList, linkedProjectIds, linkProjectKeyword],
  );

  useEffect(() => {
    if (!error) return;
    const status = error instanceof ApiRequestError ? error.status : undefined;
    console.error("[customer-detail] query failed", {
      customerId: id,
      effectiveUserId: scopeKey,
      status,
      message: error instanceof Error ? error.message : String(error),
    });
  }, [error, id, scopeKey]);

  /* ── conditional returns (五态) ── */

  if (!Number.isInteger(id)) {
    return (
      <DetailError
        backHref="/customers"
        backLabel="返回客户列表"
        message="无效的客户 ID"
      />
    );
  }

  if (authLoading || isLoading || (isFetching && !data)) {
    return <DetailSkeleton backHref="/customers" backLabel="返回客户列表" />;
  }

  if (error) {
    const status = error instanceof ApiRequestError ? error.status : undefined;
    const forbidden = status === 403;
    const notFound = status === 404;
    return (
      <DetailError
        backHref="/customers"
        backLabel="返回客户列表"
        message={
          forbidden
            ? "无权查看该客户，或该客户不在你的账号可见范围内。"
            : notFound
              ? "客户不存在或已删除。"
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

  if (!safeCustomer) {
    return (
      <DetailError
        backHref="/customers"
        backLabel="返回客户列表"
        message="客户不存在或已删除。"
      />
    );
  }
  const customer = safeCustomer;

  /* ── render ── */

  return (
    <div className="flex flex-col h-full">
      {/* ── header ── */}
      <DetailHeader
        backHref="/customers"
        backLabel="返回客户列表"
        title={customer.name}
        subtitle={customer.company || customer.position || undefined}
        accessRole={
          customer.access_role as "owner" | "collaborator" | undefined
        }
        actions={
          isOwner ? (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setTransferOpen(true)}
                className="gap-1.5 text-xs"
              >
                <ArrowRightLeft className="h-3.5 w-3.5" />
                转移负责人
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="gap-1.5 text-xs text-destructive hover:text-destructive"
                onClick={() => {
                  if (confirm("确定删除该客户？此操作不可撤销。")) {
                    deleteCustomerMutation.mutate();
                  }
                }}
              >
                <Trash2 className="h-3.5 w-3.5" />
                删除
              </Button>
            </>
          ) : undefined
        }
      />

      {/* ── scrollable body ── */}
      <div className="flex-1 overflow-auto p-4 md:p-6 space-y-5">
        {/* role hint for collaborators */}
        {customer.access_role === "collaborator" && (
          <RoleHint accessRole="collaborator" />
        )}

        {/* 1. 客户信息 */}
        <InfoGrid
          title="客户信息"
          icon={<User className="h-4 w-4" />}
          fields={[
            { label: "客户名称", value: customer.name },
            { label: "公司", value: customer.company },
            { label: "职位", value: customer.position },
            { label: "联系方式", value: customer.contact },
            { label: "认识方式", value: customer.origin },
            { label: "如何认识", value: customer.acquaintance_source },
            { label: "业务方向", value: customer.business_direction },
            { label: "未来合作方向", value: customer.future_direction },
            { label: "公司简介", value: customer.profile, span: 2 },
            { label: "备注", value: customer.notes, span: 2 },
          ]}
        />

        {/* 2. 关联项目 */}
        <Card className="rounded-xl border border-border bg-card shadow-sm overflow-hidden">
          <CardHeader className="pb-3 border-b border-border/60 flex flex-row items-center justify-between">
            <CardTitle className="text-sm font-semibold flex items-center gap-2 text-foreground">
              <Briefcase className="h-4 w-4" />
              关联项目
            </CardTitle>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setProjectCustomerIds([id]);
                setProjectFormOpen(true);
              }}
            >
              <Plus className="h-4 w-4 mr-1.5" />
              新建项目
            </Button>
            {isOwner && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => setLinkProjectOpen(true)}
              >
                <Link2 className="h-4 w-4 mr-1.5" />
                关联已有项目
              </Button>
            )}
          </CardHeader>
          <CardContent className="p-4 md:p-6">
            {projects.length === 0 ? (
              <p className="text-sm text-muted-foreground py-6 text-center">
                该客户暂无关联项目
              </p>
            ) : (
              <ul className="divide-y divide-border/60">
                {projects.map((p) => (
                  <li key={p.id}>
                    <a
                      href={`/projects/${p.id}`}
                      className="flex items-center gap-3 py-2.5 px-1 rounded-md hover:bg-muted/50 transition-colors group"
                    >
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-foreground truncate group-hover:text-primary transition-colors">
                          {p.name}
                        </p>
                        <p className="text-xs text-muted-foreground truncate mt-0.5">
                          {[p.project_no, p.owner].filter(Boolean).join(" · ") ||
                            "—"}
                        </p>
                      </div>
                      {p.status && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground shrink-0">
                          {p.status}
                        </span>
                      )}
                      <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary shrink-0">
                        {p.access_role === "owner" ? "我负责" : "协作中"}
                      </span>
                      {isOwner && (
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          className="text-xs text-muted-foreground hover:text-destructive"
                          onClick={(e) => {
                            e.preventDefault();
                            if (confirm("确定解除该项目与当前客户的关联吗？")) {
                              unlinkProjectMutation.mutate(p.id);
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
          </CardContent>
        </Card>

        {/* 3. 沟通/拜访记录 */}
        <Card className="rounded-xl border border-border bg-card shadow-sm overflow-hidden">
          <CardHeader className="pb-3 border-b border-border/60 flex flex-row items-center justify-between">
            <CardTitle className="text-sm font-semibold flex items-center gap-2 text-foreground">
              <MessageSquare className="h-4 w-4" />
              沟通/拜访记录
            </CardTitle>
            <Button size="sm" onClick={openCreate}>
              <Plus className="h-4 w-4 mr-1.5" />
              新增记录
            </Button>
          </CardHeader>
          <CardContent className="p-4 md:p-6">
            {interactions.length === 0 ? (
              <p className="text-sm text-muted-foreground py-6 text-center">
                暂无沟通记录
              </p>
            ) : (
              <ul className="space-y-4">
                {interactions.map((i) => (
                  <li
                    key={i.id}
                    className="relative pl-4 border-l-2 border-border/60 border-dashed"
                  >
                    <Card className="rounded-lg border border-border bg-muted/20 overflow-hidden ml-2">
                      {/* card header row */}
                      <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 border-b border-border bg-muted/30">
                        <div className="flex flex-wrap items-center gap-2 gap-y-1">
                          <span className="text-sm font-semibold text-foreground">
                            {formatDateTime(i.meeting_time)}
                          </span>
                          <span className="text-xs px-2 py-0.5 rounded-md bg-muted text-muted-foreground">
                            {sourceLabel(i.source)}
                          </span>
                          {i.created_at && (
                            <span className="text-xs text-muted-foreground">
                              创建于 {formatDateTime(i.created_at)}
                            </span>
                          )}
                          {i.updated_at && i.updated_at !== i.created_at && (
                            <span className="text-xs text-muted-foreground">
                              更新于 {formatDateTime(i.updated_at)}
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-3">
                          <ImportanceStars
                            value={i.importance}
                            variant="prominent"
                          />
                          {isOwner && (
                            <div className="flex items-center gap-1">
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                className="h-8 w-8 text-muted-foreground hover:text-foreground"
                                onClick={() => openEdit(i)}
                                aria-label="编辑"
                              >
                                <Pencil className="h-4 w-4" />
                              </Button>
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                className="h-8 w-8 text-muted-foreground hover:text-destructive"
                                onClick={() => {
                                  if (confirm("确定删除该条沟通记录？")) {
                                    deleteMutation.mutate(i.id);
                                  }
                                }}
                                aria-label="删除"
                              >
                                <Trash2 className="h-4 w-4" />
                              </Button>
                            </div>
                          )}
                        </div>
                      </div>
                      {/* card body */}
                      <div className="p-4 space-y-4">
                        {i.talk_summary?.trim() && (
                          <div>
                            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground block mb-1">
                              谈话内容
                            </span>
                            <p className="text-sm text-foreground whitespace-pre-wrap break-words leading-relaxed">
                              {i.talk_summary}
                            </p>
                          </div>
                        )}
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                          {i.cooperation_direction?.trim() && (
                            <div>
                              <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground block mb-1">
                                业务合作方向
                              </span>
                              <p className="text-sm text-foreground whitespace-pre-wrap break-words">
                                {i.cooperation_direction}
                              </p>
                            </div>
                          )}
                          {i.cooperation_intent?.trim() && (
                            <div>
                              <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground block mb-1">
                                意向合作
                              </span>
                              <p className="text-sm text-foreground whitespace-pre-wrap break-words">
                                {i.cooperation_intent}
                              </p>
                            </div>
                          )}
                        </div>
                        {i.next_cooperation_plan?.trim() && (
                          <div>
                            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground block mb-1">
                              下次意向合作内容
                            </span>
                            <p className="text-sm text-foreground whitespace-pre-wrap break-words leading-relaxed">
                              {i.next_cooperation_plan}
                            </p>
                          </div>
                        )}
                        {i.specific_needs?.trim() && (
                          <div>
                            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground block mb-1">
                              具体需求
                            </span>
                            <p className="text-sm text-foreground whitespace-pre-wrap break-words leading-relaxed">
                              {i.specific_needs}
                            </p>
                          </div>
                        )}
                        {!i.talk_summary?.trim() &&
                          !i.cooperation_direction?.trim() &&
                          !i.cooperation_intent?.trim() &&
                          !i.next_cooperation_plan?.trim() &&
                          !i.specific_needs?.trim() && (
                            <p className="text-sm text-muted-foreground">
                              暂无详细内容
                            </p>
                          )}
                        {i.raw_input?.trim() && (
                          <div className="border-t border-border/60 pt-3 mt-3">
                            <button
                              type="button"
                              onClick={() =>
                                setExpandedRawInputId((prev) =>
                                  prev === i.id ? null : i.id,
                                )
                              }
                              className="text-xs text-muted-foreground hover:text-foreground"
                            >
                              {expandedRawInputId === i.id
                                ? "收起原始输入"
                                : "查看原始输入"}
                            </button>
                            {expandedRawInputId === i.id && (
                              <pre className="mt-2 p-3 rounded-md bg-muted/50 text-xs text-muted-foreground whitespace-pre-wrap break-words border border-border/50">
                                {i.raw_input}
                              </pre>
                            )}
                          </div>
                        )}
                      </div>
                    </Card>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        {/* 4. 协作 */}
        <CustomerCollabSection customerId={id} customer={customer} />
      </div>

      {/* ── dialogs (outside scrollable area) ── */}

      {/* 新建项目 dialog */}
      <Dialog
        open={projectFormOpen}
        onOpenChange={(open) => {
          if (!open) setProjectFormOpen(false);
        }}
      >
        <DialogContent className="max-h-[90vh] overflow-y-auto max-w-lg">
          <DialogHeader>
            <DialogTitle>新建项目</DialogTitle>
          </DialogHeader>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const form = e.currentTarget;
              const name = (
                form.elements.namedItem("proj_name") as HTMLInputElement
              ).value?.trim();
              if (!name) return;
              const projectNo =
                (
                  form.elements.namedItem(
                    "proj_project_no",
                  ) as HTMLInputElement
                ).value?.trim() || undefined;
              createProjectMutation.mutate({
                project_no: projectNo || null,
                name,
                deadline:
                  (
                    form.elements.namedItem(
                      "proj_deadline",
                    ) as HTMLInputElement
                  ).value || null,
                goal:
                  (
                    form.elements.namedItem("proj_goal") as HTMLInputElement
                  ).value || null,
                owner:
                  (
                    form.elements.namedItem("proj_owner") as HTMLInputElement
                  ).value || null,
                requirements:
                  (
                    form.elements.namedItem(
                      "proj_requirements",
                    ) as HTMLInputElement
                  ).value || null,
                customer_name:
                  (
                    form.elements.namedItem(
                      "proj_customer_name",
                    ) as HTMLInputElement
                  ).value || null,
                customer_ids:
                  projectCustomerIds.length > 0 ? projectCustomerIds : [id],
              });
            }}
            className="space-y-4"
          >
            <div className="space-y-2">
              <Label htmlFor="proj_project_no">项目编号</Label>
              <Input
                id="proj_project_no"
                name="proj_project_no"
                placeholder="如 P001，不填则自动生成"
                className="max-w-[200px]"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="proj_name">项目名称 *</Label>
              <Input
                id="proj_name"
                name="proj_name"
                required
                placeholder="请输入项目名称"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="proj_deadline">截止日期</Label>
              <Input id="proj_deadline" name="proj_deadline" type="date" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="proj_goal">项目目标</Label>
              <Input id="proj_goal" name="proj_goal" placeholder="项目目标" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="proj_owner">负责人</Label>
              <Input
                id="proj_owner"
                name="proj_owner"
                placeholder="负责人"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="proj_requirements">项目内需</Label>
              <Input
                id="proj_requirements"
                name="proj_requirements"
                placeholder="项目内需"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="proj_customer_name">客户名称（文本）</Label>
              <Input
                id="proj_customer_name"
                name="proj_customer_name"
                placeholder="客户名称"
              />
            </div>
            <div className="space-y-2">
              <Label>关联客户（当前客户已默认关联）</Label>
              <ScrollArea className="max-h-48 rounded border border-border bg-muted/30 p-2">
                <div className="space-y-1.5">
                  {customersList.length === 0 ? (
                    <p className="text-muted-foreground text-sm">暂无客户</p>
                  ) : (
                    (customersList as Customer[]).map((c) => {
                      const isCurrent = c.id === id;
                      const checked = projectCustomerIds.includes(c.id);
                      return (
                        <label
                          key={c.id}
                          className={
                            "flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 hover:bg-muted/50" +
                            (isCurrent ? " bg-primary/5" : "")
                          }
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            disabled={isCurrent}
                            onChange={(e) => {
                              if (isCurrent) return;
                              if (e.target.checked) {
                                setProjectCustomerIds((prev) => [
                                  ...prev,
                                  c.id,
                                ]);
                              } else {
                                setProjectCustomerIds((prev) =>
                                  prev.filter((cid) => cid !== c.id),
                                );
                              }
                            }}
                            className="h-4 w-4 rounded border-border"
                          />
                          <span className="text-sm">
                            {c.company
                              ? `${c.name} / ${c.company}`
                              : c.name}
                            {isCurrent && " （当前客户，必选）"}
                          </span>
                        </label>
                      );
                    })
                  )}
                </div>
              </ScrollArea>
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setProjectFormOpen(false)}
              >
                取消
              </Button>
              <Button type="submit" disabled={createProjectMutation.isPending}>
                {createProjectMutation.isPending ? "创建中…" : "确定"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* 新增/编辑沟通记录 dialog */}
      <Dialog open={formOpen} onOpenChange={(open) => !open && closeForm()}>
        <DialogContent className="max-h-[90vh] overflow-y-auto max-w-lg">
          <DialogHeader>
            <DialogTitle>{formTitle}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleSubmitInteraction} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="form-meeting_time">见面时间</Label>
              <Input
                id="form-meeting_time"
                type="datetime-local"
                value={formMeetingTime}
                onChange={(e) => setFormMeetingTime(e.target.value)}
                className="w-full"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="form-talk_summary">谈话内容</Label>
              <textarea
                id="form-talk_summary"
                className="flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                value={formTalkSummary}
                onChange={(e) => setFormTalkSummary(e.target.value)}
                placeholder="谈话内容"
                rows={3}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="form-cooperation_direction">业务合作方向</Label>
              <Input
                id="form-cooperation_direction"
                value={formCooperationDirection}
                onChange={(e) => setFormCooperationDirection(e.target.value)}
                placeholder="业务合作方向"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="form-cooperation_intent">意向合作</Label>
              <Input
                id="form-cooperation_intent"
                value={formCooperationIntent}
                onChange={(e) => setFormCooperationIntent(e.target.value)}
                placeholder="意向合作"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="form-next_cooperation_plan">
                下次意向合作内容
              </Label>
              <Input
                id="form-next_cooperation_plan"
                value={formNextPlan}
                onChange={(e) => setFormNextPlan(e.target.value)}
                placeholder="下次意向合作内容"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="form-specific_needs">具体需求</Label>
              <textarea
                id="form-specific_needs"
                className="flex min-h-[60px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                value={formSpecificNeeds}
                onChange={(e) => setFormSpecificNeeds(e.target.value)}
                placeholder="具体需求"
                rows={2}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="form-importance">重要性（1~5 星）</Label>
              <select
                id="form-importance"
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                value={formImportance}
                onChange={(e) => setFormImportance(e.target.value)}
              >
                <option value="">未设置</option>
                <option value="1">1 星</option>
                <option value="2">2 星</option>
                <option value="3">3 星</option>
                <option value="4">4 星</option>
                <option value="5">5 星</option>
              </select>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={closeForm}>
                取消
              </Button>
              <Button
                type="submit"
                disabled={createMutation.isPending || updateMutation.isPending}
              >
                {createMutation.isPending || updateMutation.isPending
                  ? "提交中…"
                  : "确定"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* 关联已有项目 dialog */}
      <Dialog
        open={linkProjectOpen}
        onOpenChange={(open) => {
          if (!open) {
            setLinkProjectOpen(false);
            setSelectedProjectIds([]);
            setLinkProjectKeyword("");
          }
        }}
      >
        <DialogContent className="max-h-[90vh] overflow-y-auto max-w-xl">
          <DialogHeader>
            <DialogTitle>关联已有项目</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <Input
              placeholder="搜索项目名称 / 编号 / 负责人"
              value={linkProjectKeyword}
              onChange={(e) => setLinkProjectKeyword(e.target.value)}
            />
            <ScrollArea className="h-72 rounded border border-border">
              <div className="p-2 space-y-1.5">
                {linkableProjects.length === 0 ? (
                  <p className="text-sm text-muted-foreground p-2">没有可关联的项目</p>
                ) : (
                  linkableProjects.map((p) => (
                    <label key={p.id} className="flex items-center gap-2 rounded px-2 py-2 hover:bg-muted/50">
                      <input
                        type="checkbox"
                        checked={selectedProjectIds.includes(p.id)}
                        onChange={(e) => {
                          if (e.target.checked) {
                            setSelectedProjectIds((prev) => [...prev, p.id]);
                          } else {
                            setSelectedProjectIds((prev) => prev.filter((x) => x !== p.id));
                          }
                        }}
                        className="h-4 w-4"
                      />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium truncate">{p.name}</p>
                        <p className="text-xs text-muted-foreground truncate">
                          {[p.project_no, p.owner].filter(Boolean).join(" · ") || "—"}
                        </p>
                      </div>
                      <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                        {p.access_role === "owner" ? "我负责" : "协作中"}
                      </span>
                    </label>
                  ))
                )}
              </div>
            </ScrollArea>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setLinkProjectOpen(false)}>
              取消
            </Button>
            <Button
              disabled={selectedProjectIds.length === 0 || linkProjectsMutation.isPending}
              onClick={() => linkProjectsMutation.mutate(selectedProjectIds)}
            >
              {linkProjectsMutation.isPending ? "关联中…" : "确认关联"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 转移负责人 dialog */}
      <TransferOwnerDialog
        open={transferOpen}
        onClose={() => setTransferOpen(false)}
        onConfirm={async (targetUserId) => {
          await customerCollabApi.transferOwner(id, {
            target_user_id: targetUserId,
          });
          toast.success("客户负责人已转移");
          invalidateDetail();
        }}
        allUsers={transferUsers || []}
        currentOwnerUserId={customer?.owner_user_id ?? undefined}
        resourceLabel="客户"
      />
    </div>
  );
}
