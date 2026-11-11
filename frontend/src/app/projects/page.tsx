"use client";

import { useState, useRef, useEffect } from "react";
import {
  useQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import Link from "next/link";
import { MoreHorizontal, Plus, Undo2, Trash2, RefreshCw, Pencil, ExternalLink } from "lucide-react";
import { projectsApi, customersApi, type Project, type ProjectCreate } from "@/lib/apiClient";
import { queryKeys } from "@/lib/queryKeys";
import { getApiBase } from "@/lib/apiBase";
import type { Customer } from "@/types/customer";
import type { CustomerBrief } from "@/types/project";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  TableRoot,
  TableHead,
  TableBody,
  TableRow,
  TableHeadCell,
  TableCell,
  TableCellEmpty,
} from "@/components/data-table/Table";
import { cn } from "@/lib/utils";
import { useMobile } from "@/hooks/use-mobile";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";
import { ProjectForm } from "@/components/projects/ProjectForm";
import { formatLocalDate, formatLocalDateTime } from "@/lib/time";

const MAX_CUSTOMER_BADGES = 3;

function RelatedCustomersCell({ customers }: { customers?: CustomerBrief[] }) {
  if (!customers?.length) {
    return (
      <span className="text-muted-foreground/80 text-xs italic">— 暂无关联客户</span>
    );
  }
  const show = customers.slice(0, MAX_CUSTOMER_BADGES);
  const rest = customers.length - MAX_CUSTOMER_BADGES;
  const fullList = customers.map((c) => (c.company ? `${c.name} / ${c.company}` : c.name)).join("、");
  return (
    <div
      className="flex flex-wrap items-center gap-1.5"
      title={fullList}
    >
      {show.map((c, i) => (
        <span
          key={c.id}
          className={cn(
            "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium text-foreground",
            i === 0 ? "bg-primary/15 font-semibold" : "bg-muted"
          )}
          title={[c.name, c.company].filter(Boolean).join(" · ") || c.name}
        >
          {c.company ? `${c.name} / ${c.company}` : c.name}
        </span>
      ))}
      {rest > 0 && (
        <span className="text-muted-foreground text-xs" title={fullList}>+{rest}</span>
      )}
    </div>
  );
}

const columnHelper = createColumnHelper<Project>();

function formatDate(s: string | null | undefined) {
  if (!s) return "";
  return formatLocalDate(s);
}

function formatDateTime(s: string | null | undefined) {
  if (!s) return "";
  return formatLocalDateTime(s);
}

export default function ProjectsPage() {
  const { user } = useAuth();
  const scopeKey = user?.id ?? null;
  const isMobile = useMobile();
  const queryClient = useQueryClient();
  const [lastEditedId, setLastEditedId] = useState<number | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editingProject, setEditingProject] = useState<Project | null>(null);
  const [highlightedRowIds, setHighlightedRowIds] = useState<Set<number>>(new Set());
  const tableWrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.projects(scopeKey) });
      setTimeout(() => {
        tableWrapperRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
      }, 400);
    };
    window.addEventListener("ai:projects-invalidated", handler);
    return () => window.removeEventListener("ai:projects-invalidated", handler);
  }, [queryClient, scopeKey]);

  useEffect(() => {
    const timeouts: ReturnType<typeof setTimeout>[] = [];
    const handler = (e: CustomEvent<{ projectIds: number[] }>) => {
      const ids = e.detail?.projectIds ?? [];
      if (ids.length === 0) return;
      setHighlightedRowIds((prev) => new Set([...Array.from(prev), ...ids]));
      const t = setTimeout(() => {
        setHighlightedRowIds((prev) => {
          const next = new Set(prev);
          ids.forEach((id) => next.delete(id));
          return next;
        });
      }, 2200);
      timeouts.push(t);
    };
    window.addEventListener("ai:highlight-projects", handler as EventListener);
    return () => {
      window.removeEventListener("ai:highlight-projects", handler as EventListener);
      timeouts.forEach(clearTimeout);
    };
  }, []);

  const { data: list = [], isLoading, error, refetch, isRefetching } = useQuery({
    queryKey: queryKeys.projects(scopeKey),
    queryFn: async () => {
      try {
        return await projectsApi.list();
      } catch (e) {
        const url = typeof window !== "undefined" ? `${getApiBase()}/api/v1/projects` : "/api/v1/projects";
        console.error("[项目列表] 请求失败", {
          request_url: url,
          error_message: e instanceof Error ? e.message : String(e),
          response_status: (e as { status?: number })?.status ?? "(network error or no response)",
        });
        throw e;
      }
    },
  });

  const { data: customersList = [] } = useQuery({
    queryKey: queryKeys.customers(scopeKey),
    queryFn: customersApi.list,
  });
  const { data: usersList = [] } = useQuery({
    queryKey: queryKeys.projectSelectableUsers(),
    queryFn: projectsApi.listSelectableUsers,
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Parameters<typeof projectsApi.update>[1] }) =>
      projectsApi.update(id, body),
    onSuccess: (_, { id }) => {
      setLastEditedId(id);
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects(scopeKey) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.projectDetail(id, scopeKey) });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: projectsApi.delete,
    onSuccess: (_, id) => {
      setLastEditedId(id);
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects(scopeKey) });
    },
  });

  const undoMutation = useMutation({
    mutationFn: projectsApi.undo,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects(scopeKey) });
      setLastEditedId(null);
    },
  });

  const createMutation = useMutation({
    mutationFn: projectsApi.create,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects(scopeKey) });
      setCreateOpen(false);
    },
  });

  const handleRefresh = async () => {
    try {
      await refetch();
      toast.success("项目列表已刷新");
    } catch (e) {
      toast.error("项目列表刷新失败");
    }
  };

  const { data: ownerRepairQueue = [] } = useQuery({
    queryKey: queryKeys.projectOwnerRepairQueue(),
    queryFn: projectsApi.listOwnerRepairQueue,
    enabled: user?.role === "admin",
  });
  const resolveOwnerRepairMutation = useMutation({
    mutationFn: ({ projectId, ownerUserId }: { projectId: number; ownerUserId: number }) =>
      projectsApi.resolveOwnerRepairQueue(projectId, { owner_user_id: ownerUserId }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.projectOwnerRepairQueue() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects(scopeKey) });
    },
  });

  const columns = [
    columnHelper.accessor("project_no", {
      header: "项目编号",
      cell: ({ row }) => (
        <span className="text-sm">{row.original.project_no || "—"}</span>
      ),
      meta: { widthClass: "w-[100px] min-w-[100px]" },
    }),
    columnHelper.display({
      id: "access_role",
      header: "角色",
      cell: ({ row }) => {
        const uid = scopeKey;
        const isInitiator = uid != null && row.original.initiator_user_id === uid;
        const isOwner = uid != null && row.original.owner_user_id === uid;
        if (isInitiator && isOwner) return <span className="text-xs text-blue-600 font-medium">发起并负责</span>;
        if (isInitiator) return <span className="text-xs text-indigo-600 font-medium">我发起</span>;
        if (isOwner) return <span className="text-xs text-blue-600 font-medium">我负责</span>;
        if (row.original.access_role === "collaborator") return <span className="text-xs text-green-600 font-medium">协作中</span>;
        return <span className="text-xs text-muted-foreground font-medium">已共享</span>;
      },
      meta: { widthClass: "w-[70px] min-w-[70px]" },
    }),
    columnHelper.accessor("name", {
      header: "项目名称",
      cell: ({ row }) => (
        <div className="flex items-center gap-1.5 min-w-0">
          <Link
            href={`/projects/${row.original.id}`}
            className="text-primary font-semibold hover:underline decoration-primary/50 underline-offset-2 whitespace-normal break-words line-clamp-2"
            title="查看项目详情"
          >
            {row.original.name || "—"}
          </Link>
        </div>
      ),
      meta: { widthClass: "min-w-[260px] pl-2" },
    }),
    columnHelper.accessor("start_time", {
      header: "开始时间",
      cell: ({ row }) => (
        <span className="text-sm whitespace-normal break-words line-clamp-2">
          {formatDateTime(row.original.start_time ?? row.original.start_date ?? null) || "未设置"}
        </span>
      ),
      meta: { widthClass: "min-w-[170px]" },
    }),
    columnHelper.accessor("deadline_at", {
      header: "截止时间",
      cell: ({ row }) => (
        <span className="text-sm whitespace-normal break-words line-clamp-2">
          {formatDateTime(row.original.deadline_at ?? row.original.deadline ?? null) || "未设置"}
        </span>
      ),
      meta: { widthClass: "min-w-[170px]" },
    }),
    columnHelper.accessor("goal", {
      header: "项目目标",
      cell: ({ row }) => (
        <span className="text-sm whitespace-normal break-words line-clamp-2">{row.original.goal || "—"}</span>
      ),
      meta: { widthClass: "min-w-[280px]" },
    }),
    columnHelper.accessor("owner", {
      header: "负责人",
      cell: ({ row }) => (
        <div className="flex items-center gap-2">
          <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
            {(row.original.owner || "未").slice(0, 1)}
          </span>
          <span className="text-sm">{row.original.owner || "—"}</span>
        </div>
      ),
      meta: { widthClass: "min-w-[150px]" },
    }),
    columnHelper.accessor("update_date", {
      header: "更新日期",
      cell: ({ row }) => {
        const val = row.original.update_date;
        const formatted = val ? formatDate(val) : "—";
        const isEmpty = !val;
        return (
          <span
            className={cn(
              "text-muted-foreground truncate block",
              isEmpty && "text-center"
            )}
            title={val || undefined}
          >
            {formatted}
          </span>
        );
      },
      meta: { widthClass: "min-w-[110px]" },
    }),
    columnHelper.accessor("progress_text", {
      header: "项目进展",
      cell: ({ row }) => (
        <span className="text-sm whitespace-normal break-words line-clamp-2">{row.original.progress_text || "—"}</span>
      ),
      meta: { widthClass: "min-w-[300px]" },
    }),
    columnHelper.accessor("requirements", {
      header: "项目内需",
      cell: ({ row }) => (
        <span className="text-sm whitespace-normal break-words line-clamp-2">{row.original.requirements || "—"}</span>
      ),
      meta: { widthClass: "min-w-[300px]" },
    }),
    columnHelper.accessor("customer_name", {
      header: "客户名称",
      cell: ({ row }) => (
        <span className="text-sm">{row.original.customer_name || "—"}</span>
      ),
      meta: { widthClass: "min-w-[120px]" },
    }),
    columnHelper.display({
      id: "related_customers",
      header: "关联客户",
      cell: ({ row }) => <RelatedCustomersCell customers={row.original.related_customers} />,
      meta: { widthClass: "min-w-[140px]" },
    }),
    columnHelper.display({
      id: "actions",
      header: "",
      cell: ({ row }) => {
        const isOwner = row.original.access_role !== "collaborator";
        return (
          <div className="flex items-center justify-end gap-1 pr-2 whitespace-nowrap sticky right-0 bg-background">
            {isMobile ? (
              <details className="relative">
                <summary className="list-none cursor-pointer rounded p-1 hover:bg-muted">
                  <MoreHorizontal className="h-4 w-4 text-muted-foreground" />
                </summary>
                <div className="absolute right-0 z-20 mt-1 min-w-24 rounded border border-border bg-popover p-1 shadow">
                  <Link
                    href={`/projects/${row.original.id}`}
                    className="block w-full rounded px-2 py-1.5 text-left text-xs hover:bg-muted"
                  >
                    详情
                  </Link>
                  {isOwner && (
                    <>
                      <button
                        type="button"
                        className="w-full rounded px-2 py-1.5 text-left text-xs hover:bg-muted"
                        onClick={() => openEdit(row.original)}
                      >
                        编辑
                      </button>
                      <button
                        type="button"
                        className="w-full rounded px-2 py-1.5 text-left text-xs text-destructive hover:bg-muted"
                        onClick={() => {
                          if (confirm("确定删除该项目？")) {
                            deleteMutation.mutate(row.original.id);
                          }
                        }}
                      >
                        删除
                      </button>
                    </>
                  )}
                </div>
              </details>
            ) : (
              <>
                <Link href={`/projects/${row.original.id}`}>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="text-primary hover:text-primary/80 shrink-0"
                    title="查看项目详情"
                  >
                    <ExternalLink className="h-4 w-4" />
                  </Button>
                </Link>
                {isOwner && (
                  <>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="text-muted-foreground hover:text-foreground shrink-0"
                      onClick={() => openEdit(row.original)}
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="text-muted-foreground hover:text-destructive shrink-0"
                      onClick={() => {
                        if (confirm("确定删除该项目？")) {
                          deleteMutation.mutate(row.original.id);
                        }
                      }}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </>
                )}
              </>
            )}
          </div>
        );
      },
      meta: { widthClass: "w-[140px] min-w-[140px]" },
    }),
  ];

  const table = useReactTable({
    data: list,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  const openEdit = (project: Project) => {
    setEditingProject(project);
    setEditOpen(true);
  };

  return (
    <div className="flex flex-col h-full">
      <div className="border-b border-border bg-card/95 backdrop-blur px-4 md:px-8 py-4 md:py-5">
        <div className="flex items-start md:items-center justify-between gap-3">
          <div className="space-y-1">
            <h1 className="text-xl md:text-2xl font-semibold tracking-tight">项目管理</h1>
            <p className="text-xs md:text-sm text-muted-foreground">聚焦项目名称、目标、进展与关键时间，支持高密度可读管理</p>
          </div>
          <div className="flex items-center gap-2.5 flex-wrap justify-end">
            <Button
              variant="outline"
              size="sm"
              onClick={() => void handleRefresh()}
              disabled={isRefetching}
            >
              <RefreshCw className={cn("mr-1.5 h-4 w-4", isRefetching && "animate-spin")} />
              {isRefetching ? "刷新中…" : "刷新"}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => undoMutation.mutate(lastEditedId!)}
              disabled={lastEditedId == null || undoMutation.isPending}
            >
              <Undo2 className="mr-1.5 h-4 w-4" />
              撤销上次修改
            </Button>
            <Dialog open={createOpen} onOpenChange={setCreateOpen}>
              <DialogTrigger asChild>
                <Button size="sm" className="shadow-sm">
                  <Plus className="mr-1.5 h-4 w-4" />
                  新增
                </Button>
              </DialogTrigger>
              <DialogContent className="w-[min(96vw,1100px)] max-w-none max-h-[92vh]">
                <DialogHeader>
                  <DialogTitle>新增项目</DialogTitle>
                </DialogHeader>
                <ProjectForm
                  users={usersList}
                  customers={customersList}
                  submitText="确定"
                  pending={createMutation.isPending}
                  onCancel={() => setCreateOpen(false)}
                  onSubmit={(payload) => createMutation.mutate(payload as ProjectCreate)}
                />
              </DialogContent>
            </Dialog>
            <Dialog open={editOpen} onOpenChange={(open) => { setEditOpen(open); if (!open) setEditingProject(null); }}>
              <DialogContent className="w-[min(96vw,1100px)] max-w-none max-h-[92vh]">
                <DialogHeader>
                  <DialogTitle>编辑项目</DialogTitle>
                </DialogHeader>
                {editingProject && (
                  <ProjectForm
                    users={usersList}
                    customers={customersList}
                    initial={{
                      project_no: editingProject.project_no,
                      name: editingProject.name,
                      owner_user_id: editingProject.owner_user_id ?? null,
                      start_time: editingProject.start_time ?? editingProject.start_date,
                      deadline_at: editingProject.deadline_at ?? editingProject.deadline,
                      goal: editingProject.goal,
                      requirements: editingProject.requirements,
                      progress_text: editingProject.progress_text,
                      customer_ids: editingProject.related_customers?.map((c) => c.id) ?? [],
                    }}
                    submitText="保存"
                    pending={updateMutation.isPending}
                    onCancel={() => { setEditOpen(false); setEditingProject(null); }}
                    onSubmit={(payload) =>
                      updateMutation.mutate(
                        { id: editingProject.id, body: payload },
                        {
                          onSuccess: async () => {
                            if (
                              user?.role === "admin" &&
                              ownerRepairQueue.some((x) => x.project_id === editingProject.id) &&
                              typeof payload.owner_user_id === "number"
                            ) {
                              await resolveOwnerRepairMutation.mutateAsync({
                                projectId: editingProject.id,
                                ownerUserId: payload.owner_user_id,
                              });
                            }
                            setEditOpen(false);
                            setEditingProject(null);
                          },
                        }
                      )
                    }
                  />
                )}
              </DialogContent>
            </Dialog>
          </div>
        </div>
      </div>

      {user?.role === "admin" && ownerRepairQueue.length > 0 && (
        <div className="mx-4 md:mx-8 mt-4 rounded-lg border border-amber-300/50 bg-amber-50/40 p-3">
          <div className="mb-2 text-sm font-medium">负责人待修复队列（{ownerRepairQueue.length}）</div>
          <div className="space-y-2">
            {ownerRepairQueue.slice(0, 8).map((item) => (
              <div key={item.project_id} className="flex items-center justify-between gap-3 rounded border bg-background px-3 py-2">
                <div className="text-xs text-muted-foreground">
                  项目ID: {item.project_id} / 旧负责人: {item.owner_text || "空"} / 原因: {item.reason}
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    const p = list.find((x) => x.id === item.project_id);
                    if (p) openEdit(p);
                    else toast.error("当前页未加载该项目，请刷新页面或返回列表后再处理");
                  }}
                >
                  打开编辑
                </Button>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="flex-1 overflow-auto p-4 md:p-8">
        {error && (
          <p className="text-destructive text-sm mb-5">
            加载失败：{error instanceof Error ? error.message : String(error)}
          </p>
        )}
        {isLoading ? (
          <p className="text-muted-foreground">加载中…</p>
        ) : (
          <div
            ref={tableWrapperRef}
            className="rounded-xl border border-border bg-card shadow-sm overflow-x-auto"
          >
            <TableRoot className="w-full min-w-[1400px] table-fixed">
              <TableHead>
                {table.getHeaderGroups().map((hg) => (
                  <TableRow key={hg.id}>
                    {hg.headers.map((h) => (
                      <TableHeadCell
                        key={h.id}
                        className={cn(
                          (h.column.columnDef.meta as { widthClass?: string })?.widthClass,
                          h.id === "actions" &&
                            "pr-4 text-right sticky right-0 bg-card z-10"
                        )}
                      >
                        {flexRender(h.column.columnDef.header, h.getContext())}
                      </TableHeadCell>
                    ))}
                  </TableRow>
                ))}
              </TableHead>
              <TableBody>
                {table.getRowModel().rows.length === 0 ? (
                  <TableRow>
                    <TableCellEmpty colSpan={columns.length}>
                      暂无项目，点击「新增」创建
                    </TableCellEmpty>
                  </TableRow>
                ) : (
                  table.getRowModel().rows.map((row) => {
                    const isHighlighted = highlightedRowIds.has(row.original.id);
                    return (
                      <TableRow
                        key={row.id}
                        className={cn(isHighlighted && "animate-row-flash")}
                      >
                        {row.getVisibleCells().map((cell) => (
                          <TableCell
                            key={cell.id}
                            className={cn(
                              (cell.column.columnDef.meta as { widthClass?: string })?.widthClass,
                              cell.column.id === "project_no" && "w-[100px] min-w-[100px] pr-4",
                              cell.column.id === "name" && "pl-2",
                              cell.column.id === "actions" &&
                                "sticky right-0 bg-background z-10 overflow-visible pr-2"
                            )}
                          >
                            {flexRender(
                              cell.column.columnDef.cell,
                              cell.getContext()
                            )}
                          </TableCell>
                        ))}
                      </TableRow>
                    );
                  })
                )}
              </TableBody>
            </TableRoot>
          </div>
        )}
      </div>
    </div>
  );
}
