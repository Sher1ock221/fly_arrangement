"use client";

import { useState } from "react";
import Link from "next/link";
import {
  useQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { ChevronRight, Plus, Undo2, Trash2, RefreshCw, Pencil } from "lucide-react";
import { customersApi, type Customer, type CustomerCreate } from "@/lib/apiClient";
import type { CustomerUpdate } from "@/types/customer";
import { queryKeys } from "@/lib/queryKeys";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardFooter,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

function truncate(s: string | null | undefined, maxLen: number): string {
  if (s == null || s === "") return "—";
  if (s.length <= maxLen) return s;
  return s.slice(0, maxLen) + "…";
}

export default function CustomersPage() {
  const queryClient = useQueryClient();
  const [lastEditedId, setLastEditedId] = useState<number | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editingCustomer, setEditingCustomer] = useState<Customer | null>(null);

  const { data: list = [], isLoading, error, refetch, isRefetching } = useQuery({
    queryKey: queryKeys.customers(),
    queryFn: customersApi.list,
  });

  const deleteMutation = useMutation({
    mutationFn: customersApi.delete,
    onSuccess: (_, id) => {
      setLastEditedId(id);
      void queryClient.invalidateQueries({ queryKey: queryKeys.customers() });
    },
  });

  const undoMutation = useMutation({
    mutationFn: customersApi.undo,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.customers() });
      setLastEditedId(null);
    },
  });

  const createMutation = useMutation({
    mutationFn: customersApi.create,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.customers() });
      setCreateOpen(false);
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: CustomerUpdate }) =>
      customersApi.update(id, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.customers() });
      setEditOpen(false);
      setEditingCustomer(null);
      toast.success("客户已更新");
    },
    onError: (e) => {
      toast.error(e instanceof Error ? e.message : "更新失败");
    },
  });

  const handleRefresh = async () => {
    try {
      await refetch();
      toast.success("客户列表已刷新");
    } catch (e) {
      toast.error("客户列表刷新失败");
    }
  };

  const handleCreate = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    const name = (form.elements.namedItem("name") as HTMLInputElement).value?.trim();
    if (!name) return;
    createMutation.mutate({
      name,
      origin: (form.elements.namedItem("origin") as HTMLInputElement).value || null,
      company: (form.elements.namedItem("company") as HTMLInputElement).value || null,
      profile: (form.elements.namedItem("profile") as HTMLInputElement).value || null,
      contact: (form.elements.namedItem("contact") as HTMLInputElement).value || null,
      future_direction: (form.elements.namedItem("future_direction") as HTMLInputElement).value || null,
      position: (form.elements.namedItem("position") as HTMLInputElement).value || null,
      business_direction: (form.elements.namedItem("business_direction") as HTMLInputElement).value || null,
      notes: (form.elements.namedItem("notes") as HTMLInputElement).value || null,
      acquaintance_source: (form.elements.namedItem("acquaintance_source") as HTMLInputElement).value || null,
    });
  };

  const openEdit = (customer: Customer) => {
    setEditingCustomer(customer);
    setEditOpen(true);
  };

  const handleEdit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!editingCustomer) return;
    const form = e.currentTarget;
    const body: CustomerUpdate = {
      name: (form.elements.namedItem("edit_name") as HTMLInputElement).value?.trim() || undefined,
      origin: (form.elements.namedItem("edit_origin") as HTMLInputElement).value || null,
      company: (form.elements.namedItem("edit_company") as HTMLInputElement).value || null,
      profile: (form.elements.namedItem("edit_profile") as HTMLInputElement).value || null,
      contact: (form.elements.namedItem("edit_contact") as HTMLInputElement).value || null,
      future_direction: (form.elements.namedItem("edit_future_direction") as HTMLInputElement).value || null,
      position: (form.elements.namedItem("edit_position") as HTMLInputElement).value || null,
      business_direction: (form.elements.namedItem("edit_business_direction") as HTMLInputElement).value || null,
      notes: (form.elements.namedItem("edit_notes") as HTMLInputElement).value || null,
      acquaintance_source: (form.elements.namedItem("edit_acquaintance_source") as HTMLInputElement).value || null,
    };
    updateMutation.mutate({ id: editingCustomer.id, body });
  };

  return (
    <div className="flex flex-col h-full">
      <div className="border-b border-border bg-card px-4 md:px-6 py-3 md:py-4">
        <div className="flex items-start md:items-center justify-between gap-2">
          <h1 className="text-lg md:text-xl font-semibold">客户管理</h1>
          <div className="flex items-center gap-2 flex-wrap justify-end">
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
                <Button size="sm">
                  <Plus className="mr-1.5 h-4 w-4" />
                  新增
                </Button>
              </DialogTrigger>
              <DialogContent className="max-h-[90vh] overflow-y-auto">
                <DialogHeader>
                  <DialogTitle>新增客户</DialogTitle>
                </DialogHeader>
                <form onSubmit={handleCreate} className="space-y-4">
                  <div className="space-y-2">
                    <Label htmlFor="name">客户名称 *</Label>
                    <Input id="name" name="name" required placeholder="请输入客户名称" />
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="company">公司名称</Label>
                      <Input id="company" name="company" placeholder="公司名称" />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="position">担任职位</Label>
                      <Input id="position" name="position" placeholder="担任职位" />
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="contact">联系方式</Label>
                    <Input id="contact" name="contact" placeholder="联系方式" />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="business_direction">业务方向</Label>
                    <Input id="business_direction" name="business_direction" placeholder="业务方向" />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="acquaintance_source">如何认识</Label>
                    <Input id="acquaintance_source" name="acquaintance_source" placeholder="如何认识/认识渠道" />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="origin">认识方式</Label>
                    <Input id="origin" name="origin" placeholder="认识方式" />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="profile">公司简介</Label>
                    <Input id="profile" name="profile" placeholder="公司简介" />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="future_direction">未来合作方向</Label>
                    <Input id="future_direction" name="future_direction" placeholder="未来合作方向" />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="notes">备注</Label>
                    <Input id="notes" name="notes" placeholder="备注" />
                  </div>
                  <DialogFooter>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => setCreateOpen(false)}
                    >
                      取消
                    </Button>
                    <Button type="submit" disabled={createMutation.isPending}>
                      确定
                    </Button>
                  </DialogFooter>
                </form>
              </DialogContent>
            </Dialog>
            <Dialog open={editOpen} onOpenChange={(open) => { setEditOpen(open); if (!open) setEditingCustomer(null); }}>
              <DialogContent className="max-h-[90vh] overflow-y-auto">
                <DialogHeader>
                  <DialogTitle>编辑客户</DialogTitle>
                </DialogHeader>
                {editingCustomer && (
                  <form onSubmit={handleEdit} className="space-y-4">
                    <div className="space-y-2">
                      <Label htmlFor="edit_name">客户名称 *</Label>
                      <Input
                        id="edit_name"
                        name="edit_name"
                        required
                        defaultValue={editingCustomer.name}
                        placeholder="请输入客户名称"
                      />
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                      <div className="space-y-2">
                        <Label htmlFor="edit_company">公司名称</Label>
                        <Input
                          id="edit_company"
                          name="edit_company"
                          defaultValue={editingCustomer.company ?? ""}
                          placeholder="公司名称"
                        />
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="edit_position">担任职位</Label>
                        <Input
                          id="edit_position"
                          name="edit_position"
                          defaultValue={editingCustomer.position ?? ""}
                          placeholder="担任职位"
                        />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="edit_contact">联系方式</Label>
                      <Input
                        id="edit_contact"
                        name="edit_contact"
                        defaultValue={editingCustomer.contact ?? ""}
                        placeholder="联系方式"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="edit_business_direction">业务方向</Label>
                      <Input
                        id="edit_business_direction"
                        name="edit_business_direction"
                        defaultValue={editingCustomer.business_direction ?? ""}
                        placeholder="业务方向"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="edit_acquaintance_source">如何认识</Label>
                      <Input
                        id="edit_acquaintance_source"
                        name="edit_acquaintance_source"
                        defaultValue={editingCustomer.acquaintance_source ?? ""}
                        placeholder="如何认识/认识渠道"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="edit_origin">认识方式</Label>
                      <Input
                        id="edit_origin"
                        name="edit_origin"
                        defaultValue={editingCustomer.origin ?? ""}
                        placeholder="认识方式"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="edit_profile">公司简介</Label>
                      <Input
                        id="edit_profile"
                        name="edit_profile"
                        defaultValue={editingCustomer.profile ?? ""}
                        placeholder="公司简介"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="edit_future_direction">未来合作方向</Label>
                      <Input
                        id="edit_future_direction"
                        name="edit_future_direction"
                        defaultValue={editingCustomer.future_direction ?? ""}
                        placeholder="未来合作方向"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="edit_notes">备注</Label>
                      <Input
                        id="edit_notes"
                        name="edit_notes"
                        defaultValue={editingCustomer.notes ?? ""}
                        placeholder="备注"
                      />
                    </div>
                    <DialogFooter>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => { setEditOpen(false); setEditingCustomer(null); }}
                      >
                        取消
                      </Button>
                      <Button type="submit" disabled={updateMutation.isPending}>
                        {updateMutation.isPending ? "保存中…" : "保存"}
                      </Button>
                    </DialogFooter>
                  </form>
                )}
              </DialogContent>
            </Dialog>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-auto p-3 md:p-6">
        {error && (
          <p className="text-destructive text-sm mb-4">
            加载失败：{error instanceof Error ? error.message : String(error)}
          </p>
        )}
        {isLoading ? (
          <p className="text-muted-foreground">加载中…</p>
        ) : list.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border bg-muted/30 flex items-center justify-center min-h-[200px] text-muted-foreground text-sm">
            暂无客户，点击「新增」创建
          </div>
        ) : (
          <div
            className={cn(
              "grid gap-4",
              "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3"
            )}
          >
            {list.map((customer: Customer) => (
              <Link
                key={customer.id}
                href={`/customers/${customer.id}`}
                className="flex flex-col h-full outline-none focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2 rounded-lg"
              >
                <Card className="flex flex-col h-full transition-colors hover:border-primary/50 hover:shadow-md">
                  <CardContent className="p-4 flex-1 flex flex-col gap-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-1.5">
                        <h2 className="text-base font-semibold leading-tight line-clamp-2">
                          {customer.name}
                        </h2>
                        {customer.access_role && (
                          <span className={`text-[10px] px-1.5 py-0.5 rounded-full shrink-0 ${customer.access_role === "owner" ? "bg-blue-100 text-blue-700" : "bg-green-100 text-green-700"}`}>
                            {customer.access_role === "owner" ? "我负责" : "协作中"}
                          </span>
                        )}
                      </div>
                      <span className="shrink-0 text-muted-foreground" aria-hidden>
                        <ChevronRight className="h-5 w-5" />
                      </span>
                    </div>
                    {(customer.company || customer.position) && (
                      <p className="text-sm text-muted-foreground">
                        {[customer.company, customer.position].filter(Boolean).join(" · ")}
                      </p>
                    )}
                    {customer.contact && (
                      <p className="text-sm">{truncate(customer.contact, 40)}</p>
                    )}
                    {customer.business_direction && (
                      <p className="text-sm text-muted-foreground line-clamp-2">
                        {truncate(customer.business_direction, 60)}
                      </p>
                    )}
                    {(customer.notes || customer.acquaintance_source) && (
                      <p className="text-xs text-muted-foreground line-clamp-2">
                        {truncate(customer.notes || customer.acquaintance_source, 50)}
                      </p>
                    )}
                  </CardContent>
                  <CardFooter className="p-4 pt-0 flex items-center justify-between border-t border-border/50">
                    <span className="text-xs text-muted-foreground">
                      {customer.project_count != null && customer.project_count > 0
                        ? `关联项目 ${customer.project_count} 个`
                        : "暂无项目"}
                    </span>
                    <div className="flex items-center gap-1 shrink-0">
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-muted-foreground hover:text-foreground"
                        onClick={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          openEdit(customer);
                        }}
                        aria-label="编辑"
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-muted-foreground hover:text-destructive shrink-0"
                        onClick={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          if (confirm("确定删除该客户？")) {
                            deleteMutation.mutate(customer.id);
                          }
                        }}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </CardFooter>
                </Card>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
