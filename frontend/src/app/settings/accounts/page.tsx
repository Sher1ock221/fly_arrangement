"use client";

import { useState, useEffect, useCallback } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { useRouter, useSearchParams } from "next/navigation";
import { adminApi, getStoredToken } from "@/lib/apiClient";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Loader2, Plus, Pencil, Key, UserCheck, UserX, RefreshCw, FileText, Download, Trash2 } from "lucide-react";
import { toast } from "sonner";

interface UserItem {
  id: number;
  username: string;
  display_name: string | null;
  role: string;
  is_active: boolean;
  must_change_password: boolean;
  last_login_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  bound_feishu_count?: number;
}

export default function AccountsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user: currentUser, token } = useAuth();
  const [items, setItems] = useState<UserItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [roleFilter, setRoleFilter] = useState<string>("");
  const [activeFilter, setActiveFilter] = useState<string>("");
  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<UserItem | null>(null);
  const [resettingUser, setResettingUser] = useState<UserItem | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailUser, setDetailUser] = useState<Record<string, unknown> | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [confirmDisable, setConfirmDisable] = useState<UserItem | null>(null);
  const [confirmReset, setConfirmReset] = useState<UserItem | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<UserItem | null>(null);
  const [deleting, setDeleting] = useState(false);

  const fetchList = useCallback(async () => {
    const t = token || getStoredToken();
    if (!t) return;
    setLoading(true);
    try {
      const res = await adminApi.listUsers(t, {
        page,
        page_size: pageSize,
        q: q.trim() || undefined,
        role: roleFilter || undefined,
        is_active: activeFilter === "true" ? true : activeFilter === "false" ? false : undefined,
      });
      setItems((res.items as UserItem[]) || []);
      setTotal(res.total ?? 0);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(msg || "加载失败");
      if (msg.includes("403")) router.replace("/");
    } finally {
      setLoading(false);
    }
  }, [token, page, pageSize, q, roleFilter, activeFilter, router]);

  useEffect(() => {
    if (currentUser?.role === "admin") fetchList();
  }, [currentUser?.role, fetchList]);

  useEffect(() => {
    if (currentUser?.role !== "admin") router.replace("/");
  }, [currentUser, router]);

  const userIdFromUrl = searchParams.get("userId");
  useEffect(() => {
    if (currentUser?.role !== "admin" || !userIdFromUrl) return;
    const id = parseInt(userIdFromUrl, 10);
    if (Number.isNaN(id)) return;
    const t = token || getStoredToken();
    if (!t) return;
    setDetailOpen(true);
    setDetailLoading(true);
    setDetailUser(null);
    adminApi.getUserDetail(t, id)
      .then((res) => { setDetailUser(res.user as Record<string, unknown>); })
      .catch((e) => {
        toast.error(e instanceof Error ? e.message : String(e));
        setDetailOpen(false);
      })
      .finally(() => setDetailLoading(false));
  }, [currentUser?.role, userIdFromUrl, token]);

  const handleCreate = async (form: { username: string; password: string; display_name?: string; role: string; is_active: boolean; must_change_password: boolean }) => {
    const t = token || getStoredToken();
    if (!t) return;
    setSubmitting(true);
    try {
      await adminApi.createUser(t, form);
      toast.success("用户已创建");
      setCreateOpen(false);
      fetchList();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  const handleUpdate = async (userId: number, form: { display_name?: string; role?: string; is_active?: boolean; must_change_password?: boolean }) => {
    const t = token || getStoredToken();
    if (!t) return;
    setSubmitting(true);
    try {
      await adminApi.updateUser(t, userId, form);
      toast.success("已更新");
      setEditOpen(false);
      setEditingUser(null);
      fetchList();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  const handleResetPassword = async (userId: number, newPassword: string, mustChange: boolean) => {
    const t = token || getStoredToken();
    if (!t) return;
    setSubmitting(true);
    try {
      await adminApi.resetPassword(t, userId, { new_password: newPassword, must_change_password: mustChange });
      toast.success("密码已重置");
      setResetOpen(false);
      setResettingUser(null);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  const handleSetActive = async (u: UserItem, isActive: boolean) => {
    if (!isActive) {
      setConfirmDisable(u);
      return;
    }
    await doSetActive(u, isActive);
  };

  const doSetActive = async (u: UserItem, isActive: boolean) => {
    const t = token || getStoredToken();
    if (!t) return;
    try {
      await adminApi.setUserActive(t, u.id, isActive);
      toast.success(isActive ? "已启用" : "已禁用");
      setConfirmDisable(null);
      fetchList();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
      throw e;
    }
  };

  const openUserDetail = async (u: UserItem) => {
    const t = token || getStoredToken();
    if (!t) return;
    setDetailOpen(true);
    setDetailLoading(true);
    setDetailUser(null);
    try {
      const res = await adminApi.getUserDetail(t, u.id);
      setDetailUser(res.user as Record<string, unknown>);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
      setDetailOpen(false);
    } finally {
      setDetailLoading(false);
    }
  };

  const handleDeleteUser = async (u: UserItem) => {
    const t = token || getStoredToken();
    if (!t) return;
    setDeleting(true);
    try {
      await adminApi.deleteUser(t, u.id);
      toast.success("账号已删除");
      setConfirmDelete(null);
      if (detailUser && Number((detailUser as { id?: number }).id) === u.id) {
        setDetailOpen(false);
        setDetailUser(null);
        if (userIdFromUrl) router.replace("/settings/accounts");
      }
      fetchList();
    } catch (e) {
      let msg = e instanceof Error ? e.message : String(e);
      try {
        const parsed = JSON.parse(msg) as { detail?: string };
        if (parsed?.detail) msg = parsed.detail;
      } catch {
        /* ignore */
      }
      toast.error(msg || "删除失败");
    } finally {
      setDeleting(false);
    }
  };

  const handleExport = async () => {
    const t = token || getStoredToken();
    if (!t) return;
    setExporting(true);
    try {
      await adminApi.exportUsers(t, {
        q: q.trim() || undefined,
        role: roleFilter || undefined,
        is_active: activeFilter === "true" ? true : activeFilter === "false" ? false : undefined,
      });
      toast.success("导出成功");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setExporting(false);
    }
  };

  if (currentUser && currentUser.role !== "admin") return null;

  return (
    <div className="mx-auto max-w-6xl">
      <Card>
        <CardHeader>
          <CardTitle>账号管理</CardTitle>
          <CardDescription>管理系统用户：创建、编辑、重置密码、启用/禁用。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <Input
              placeholder="搜索用户名 / 显示名"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              className="max-w-xs"
            />
            <select
              className="h-10 rounded-md border border-input bg-background px-3 text-sm"
              value={roleFilter}
              onChange={(e) => setRoleFilter(e.target.value)}
            >
              <option value="">全部角色</option>
              <option value="admin">管理员</option>
              <option value="user">普通用户</option>
            </select>
            <select
              className="h-10 rounded-md border border-input bg-background px-3 text-sm"
              value={activeFilter}
              onChange={(e) => setActiveFilter(e.target.value)}
            >
              <option value="">全部状态</option>
              <option value="true">启用</option>
              <option value="false">禁用</option>
            </select>
            <Button variant="outline" onClick={fetchList} disabled={loading}>
              <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
              刷新
            </Button>
            <Button variant="outline" onClick={handleExport} disabled={exporting}>
              {exporting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Download className="mr-2 h-4 w-4" />}
              导出 CSV
            </Button>
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />
              新增用户
            </Button>
          </div>
          {loading ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              加载中…
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr className="border-b border-border">
                    <th className="text-left py-2 px-2">用户名</th>
                    <th className="text-left py-2 px-2">显示名</th>
                    <th className="text-left py-2 px-2">角色</th>
                    <th className="text-left py-2 px-2">状态</th>
                    <th className="text-left py-2 px-2">须改密</th>
                    <th className="text-left py-2 px-2">最后登录</th>
                    <th className="text-left py-2 px-2">创建时间</th>
                    <th className="text-left py-2 px-2">飞书绑定</th>
                    <th className="text-left py-2 px-2">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((u) => (
                    <tr key={u.id} className="border-b border-border">
                      <td className="py-2 px-2 font-medium">{u.username}</td>
                      <td className="py-2 px-2">{u.display_name ?? "—"}</td>
                      <td className="py-2 px-2">{u.role === "admin" ? "管理员" : "普通用户"}</td>
                      <td className="py-2 px-2">{u.is_active ? "启用" : "禁用"}</td>
                      <td className="py-2 px-2">{u.must_change_password ? "是" : "否"}</td>
                      <td className="py-2 px-2 text-muted-foreground">
                        {u.last_login_at ? new Date(u.last_login_at).toLocaleString("zh-CN") : "—"}
                      </td>
                      <td className="py-2 px-2 text-muted-foreground">
                        {u.created_at ? new Date(u.created_at).toLocaleString("zh-CN") : "—"}
                      </td>
                      <td className="py-2 px-2">{u.bound_feishu_count ?? 0}</td>
                      <td className="py-2 px-2">
                        <div className="flex items-center gap-1">
                          <Button variant="ghost" size="sm" onClick={() => openUserDetail(u)} title="详情">
                            <FileText className="h-4 w-4" />
                          </Button>
                          <Button variant="ghost" size="sm" onClick={() => { setEditingUser(u); setEditOpen(true); }} title="编辑">
                            <Pencil className="h-4 w-4" />
                          </Button>
                          <Button variant="ghost" size="sm" onClick={() => setConfirmReset(u)} title="重置密码">
                            <Key className="h-4 w-4" />
                          </Button>
                          {u.is_active ? (
                            <Button variant="ghost" size="sm" onClick={() => handleSetActive(u, false)} title="禁用">
                              <UserX className="h-4 w-4" />
                            </Button>
                          ) : (
                            <Button variant="ghost" size="sm" onClick={() => handleSetActive(u, true)} title="启用">
                              <UserCheck className="h-4 w-4" />
                            </Button>
                          )}
                          <Button
                            variant="ghost"
                            size="sm"
                            className="text-destructive hover:text-destructive hover:bg-destructive/10"
                            onClick={() => setConfirmDelete(u)}
                            title="删除账号"
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="flex items-center justify-between pt-2">
                <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
                  上一页
                </Button>
                <span className="text-xs text-muted-foreground">
                  第 {page} 页 / 共 {Math.max(1, Math.ceil(total / pageSize))} 页（共 {total} 条）
                </span>
                <Button variant="outline" size="sm" disabled={page >= Math.ceil(total / pageSize)} onClick={() => setPage((p) => p + 1)}>
                  下一页
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <CreateUserDialog open={createOpen} onOpenChange={setCreateOpen} onSubmit={handleCreate} submitting={submitting} />
      <EditUserDialog open={editOpen} onOpenChange={setEditOpen} user={editingUser} onSubmit={handleUpdate} submitting={submitting} />
      <ResetPasswordDialog open={resetOpen} onOpenChange={setResetOpen} user={resettingUser} onSubmit={handleResetPassword} submitting={submitting} />
      <ConfirmDialog
        open={!!confirmDisable}
        onOpenChange={(open) => !open && setConfirmDisable(null)}
        title="确认禁用用户"
        description={confirmDisable ? `确定要禁用用户「${confirmDisable.display_name || confirmDisable.username}」吗？禁用后该用户将无法登录。` : ""}
        confirmLabel="禁用"
        variant="destructive"
        onConfirm={async () => {
          if (confirmDisable) await doSetActive(confirmDisable, false);
        }}
      />
      <ConfirmDialog
        open={!!confirmReset}
        onOpenChange={(open) => { if (!open) setConfirmReset(null); }}
        title="确认重置密码"
        description={confirmReset ? `确定要为用户「${confirmReset.display_name || confirmReset.username}」重置密码吗？重置后请将新密码安全告知用户。` : ""}
        confirmLabel="去重置"
        onConfirm={() => {
          if (confirmReset) {
            setResettingUser(confirmReset);
            setResetOpen(true);
            setConfirmReset(null);
          }
        }}
      />
      <ConfirmDialog
        open={!!confirmDelete}
        onOpenChange={(open) => !open && setConfirmDelete(null)}
        title="删除账号"
        description={
          confirmDelete
            ? `你确定要删除用户「${confirmDelete.display_name || confirmDelete.username}」吗？删除后该账号将无法登录。若该用户仍拥有项目、客户、日程或会话，将无法删除。${(confirmDelete as UserItem & { bound_feishu_count?: number }).bound_feishu_count ? " 删除时将自动解除该用户的飞书绑定。" : ""}`
            : ""
        }
        confirmLabel="确认删除"
        variant="destructive"
        loading={deleting}
        onConfirm={async () => {
          if (confirmDelete) await handleDeleteUser(confirmDelete);
        }}
      />
      <UserDetailDialog
        open={detailOpen}
        onOpenChange={(open) => {
          setDetailOpen(open);
          if (!open && userIdFromUrl) router.replace("/settings/accounts");
        }}
        user={detailUser}
        loading={detailLoading}
        currentUserId={currentUser?.id}
        onEdit={(u) => { setEditingUser(u); setEditOpen(true); }}
        onReset={(u) => { setResettingUser(u); setResetOpen(true); }}
        onDelete={(u) => { setConfirmDelete(u); setDetailOpen(false); }}
      />
    </div>
  );
}

function CreateUserDialog({
  open,
  onOpenChange,
  onSubmit,
  submitting,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onSubmit: (form: { username: string; password: string; display_name?: string; role: string; is_active: boolean; must_change_password: boolean }) => void;
  submitting: boolean;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [role, setRole] = useState("user");
  const [isActive, setIsActive] = useState(true);
  const [mustChange, setMustChange] = useState(true);

  const handleSubmit = () => {
    if (!username.trim() || !password || password.length < 6) {
      return;
    }
    onSubmit({ username: username.trim(), password, display_name: displayName.trim() || undefined, role, is_active: isActive, must_change_password: mustChange });
    setUsername("");
    setPassword("");
    setDisplayName("");
    setRole("user");
    setIsActive(true);
    setMustChange(true);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>新增用户</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-4">
          <div>
            <label className="text-sm font-medium">用户名 *</label>
            <Input value={username} onChange={(e) => setUsername(e.target.value)} className="mt-1" placeholder="登录名" />
          </div>
          <div>
            <label className="text-sm font-medium">密码 *（至少 6 位）</label>
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="mt-1" />
          </div>
          <div>
            <label className="text-sm font-medium">显示名</label>
            <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} className="mt-1" placeholder="可选" />
          </div>
          <div>
            <label className="text-sm font-medium">角色</label>
            <select className="mt-1 h-10 w-full rounded-md border border-input bg-background px-3 text-sm" value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="user">普通用户</option>
              <option value="admin">管理员</option>
            </select>
          </div>
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
              <span className="text-sm">启用</span>
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={mustChange} onChange={(e) => setMustChange(e.target.checked)} />
              <span className="text-sm">首次登录须改密</span>
            </label>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>取消</Button>
          <Button onClick={handleSubmit} disabled={submitting || !username.trim() || password.length < 6}>
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : "创建"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function EditUserDialog({
  open,
  onOpenChange,
  user,
  onSubmit,
  submitting,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  user: UserItem | null;
  onSubmit: (userId: number, form: { display_name?: string; role?: string; is_active?: boolean; must_change_password?: boolean }) => void;
  submitting: boolean;
}) {
  const [displayName, setDisplayName] = useState("");
  const [role, setRole] = useState("user");
  const [isActive, setIsActive] = useState(true);
  const [mustChange, setMustChange] = useState(false);
  const [showDemoteConfirm, setShowDemoteConfirm] = useState(false);

  useEffect(() => {
    if (user) {
      setDisplayName(user.display_name ?? "");
      setRole(user.role);
      setIsActive(user.is_active);
      setMustChange(user.must_change_password);
    }
  }, [user]);

  const handleSubmit = () => {
    if (!user) return;
    if (role === "user" && user.role === "admin") {
      setShowDemoteConfirm(true);
      return;
    }
    doSubmit();
  };

  const doSubmit = () => {
    if (!user) return;
    onSubmit(user.id, { display_name: displayName.trim() || undefined, role, is_active: isActive, must_change_password: mustChange });
    setShowDemoteConfirm(false);
  };

  if (!user) return null;
  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) setShowDemoteConfirm(false); onOpenChange(v); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>编辑用户：{user.username}</DialogTitle>
        </DialogHeader>
        {showDemoteConfirm ? (
          <div className="space-y-4 py-4">
            <p className="text-sm text-muted-foreground">
              确定将该管理员降为普通用户吗？降级后其将无法访问管理员功能。
            </p>
            <DialogFooter>
              <Button variant="outline" onClick={() => setShowDemoteConfirm(false)}>取消</Button>
              <Button variant="destructive" onClick={doSubmit} disabled={submitting}>
                {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : "确定降级"}
              </Button>
            </DialogFooter>
          </div>
        ) : (
          <>
        <div className="space-y-4 py-4">
          <div>
            <label className="text-sm font-medium">显示名</label>
            <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} className="mt-1" />
          </div>
          <div>
            <label className="text-sm font-medium">角色</label>
            <select className="mt-1 h-10 w-full rounded-md border border-input bg-background px-3 text-sm" value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="user">普通用户</option>
              <option value="admin">管理员</option>
            </select>
          </div>
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
              <span className="text-sm">启用</span>
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={mustChange} onChange={(e) => setMustChange(e.target.checked)} />
              <span className="text-sm">须改密</span>
            </label>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>取消</Button>
          <Button onClick={handleSubmit} disabled={submitting}>
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : "保存"}
          </Button>
        </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function ResetPasswordDialog({
  open,
  onOpenChange,
  user,
  onSubmit,
  submitting,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  user: UserItem | null;
  onSubmit: (userId: number, newPassword: string, mustChange: boolean) => void;
  submitting: boolean;
}) {
  const [password, setPassword] = useState("");
  const [mustChange, setMustChange] = useState(true);

  useEffect(() => {
    if (open) setPassword("");
  }, [open]);

  const handleSubmit = () => {
    if (!user || !password || password.length < 6) return;
    onSubmit(user.id, password, mustChange);
  };

  if (!user) return null;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>重置密码：{user.username}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-4">
          <div>
            <label className="text-sm font-medium">新密码 *（至少 6 位）</label>
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="mt-1" />
          </div>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={mustChange} onChange={(e) => setMustChange(e.target.checked)} />
            <span className="text-sm">下次登录须修改密码</span>
          </label>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>取消</Button>
          <Button onClick={handleSubmit} disabled={submitting || password.length < 6}>
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : "重置"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function UserDetailDialog({
  open,
  onOpenChange,
  user,
  loading,
  currentUserId,
  onEdit,
  onReset,
  onDelete,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  user: Record<string, unknown> | null;
  loading: boolean;
  currentUserId?: number | null;
  onEdit?: (u: UserItem) => void;
  onReset?: (u: UserItem) => void;
  onDelete?: (u: UserItem) => void;
}) {
  const bindings = (user?.bound_feishu_identities as { identity_id: number; tenant_key: string | null; open_id_masked: string; union_id_masked: string; sender_name: string | null; last_seen_at: string | null }[] | undefined) ?? [];
  const asUserItem = (): UserItem | null => {
    if (!user || typeof user.id !== "number") return null;
    return {
      id: Number(user.id),
      username: String(user.username ?? ""),
      display_name: user.display_name != null ? String(user.display_name) : null,
      role: String(user.role ?? "user"),
      is_active: Boolean(user.is_active),
      must_change_password: Boolean(user.must_change_password),
      last_login_at: user.last_login_at != null ? String(user.last_login_at) : null,
      created_at: user.created_at != null ? String(user.created_at) : null,
      updated_at: user.updated_at != null ? String(user.updated_at) : null,
      bound_feishu_count: Number(user.bound_feishu_count ?? 0),
    };
  };
  const u = asUserItem();
  const isCurrentUser = currentUserId != null && u && currentUserId === u.id;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>用户详情</DialogTitle>
        </DialogHeader>
        {loading ? (
          <div className="flex items-center gap-2 py-4 text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            加载中…
          </div>
        ) : user ? (
          <div className="space-y-4 py-2">
            <div className="grid grid-cols-2 gap-2 text-sm">
              <span className="text-muted-foreground">用户名</span>
              <span>{String(user.username ?? "—")}</span>
              <span className="text-muted-foreground">显示名</span>
              <span>{String(user.display_name ?? "—")}</span>
              <span className="text-muted-foreground">角色</span>
              <span>{user.role === "admin" ? "管理员" : "普通用户"}</span>
              <span className="text-muted-foreground">状态</span>
              <span>{user.is_active ? "启用" : "禁用"}</span>
              <span className="text-muted-foreground">最后登录</span>
              <span>{user.last_login_at ? new Date(String(user.last_login_at)).toLocaleString("zh-CN") : "—"}</span>
              <span className="text-muted-foreground">项目数</span>
              <span>{Number(user.project_count ?? 0)}</span>
              <span className="text-muted-foreground">客户数</span>
              <span>{Number(user.customer_count ?? 0)}</span>
              <span className="text-muted-foreground">会话数</span>
              <span>{Number(user.conversation_count ?? 0)}</span>
            </div>
            <div>
              <p className="text-sm font-medium mb-2">已绑定飞书身份（{bindings.length}）</p>
              {bindings.length === 0 ? (
                <p className="text-muted-foreground text-sm">未绑定</p>
              ) : (
                <ul className="space-y-1 text-sm">
                  {bindings.map((b: { identity_id: number; sender_name: string | null; tenant_key: string | null; open_id_masked?: string; last_seen_at: string | null }) => (
                    <li key={b.identity_id} className="rounded border border-border px-2 py-1">
                      {b.sender_name ?? "—"} · tenant: {b.tenant_key ?? "—"}
                      {b.last_seen_at && ` · ${new Date(b.last_seen_at).toLocaleString("zh-CN")}`}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            {(onEdit || onReset || onDelete) && u && (
              <DialogFooter>
                {onEdit && <Button variant="outline" onClick={() => { onEdit(u); onOpenChange(false); }}>编辑</Button>}
                {onReset && <Button variant="outline" onClick={() => { onReset(u); onOpenChange(false); }}>重置密码</Button>}
                {onDelete && !isCurrentUser && (
                  <Button variant="destructive" onClick={() => { onDelete(u); onOpenChange(false); }}>
                    删除账号
                  </Button>
                )}
              </DialogFooter>
            )}
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
