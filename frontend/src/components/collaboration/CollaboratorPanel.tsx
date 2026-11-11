"use client";
import { useState } from "react";
import { Users } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { Collaborator } from "@/types/collaboration";

interface UserOption {
  id: number;
  username: string;
  display_name: string | null;
  is_active?: boolean;
}

interface Props {
  collaborators: Collaborator[];
  initiator?: { user_id: number; display_name: string; username: string } | null;
  legacyMembers?: { legacy_key: string; display_name: string; reason: string }[];
  isOwner: boolean;
  ownerUserId?: number;
  ownerDisplayName?: string;
  allUsers: UserOption[];
  onAdd: (userId: number) => Promise<void>;
  onRemove: (userId: number) => Promise<void>;
  onCleanupLegacy?: (legacyKey: string) => Promise<void>;
  loading?: boolean;
}

export default function CollaboratorPanel({
  collaborators, initiator, legacyMembers = [], isOwner, ownerUserId, ownerDisplayName, allUsers, onAdd, onRemove, onCleanupLegacy, loading,
}: Props) {
  const [selectedUserId, setSelectedUserId] = useState<number | "">("");
  const [busy, setBusy] = useState(false);

  const existingIds = new Set(collaborators.map((c) => c.user_id));
  const addableUsers = allUsers.filter(
    (u) =>
      !existingIds.has(u.id) &&
      u.id !== ownerUserId &&
      u.is_active !== false,
  );

  const handleAdd = async () => {
    if (!selectedUserId) return;
    setBusy(true);
    try {
      await onAdd(Number(selectedUserId));
      setSelectedUserId("");
    } finally {
      setBusy(false);
    }
  };

  const handleRemove = async (userId: number) => {
    setBusy(true);
    try {
      await onRemove(userId);
    } finally {
      setBusy(false);
    }
  };

  const nameOf = (c: Collaborator) => c.display_name || c.username || `用户 ${c.user_id}`;

  return (
    <Card className="rounded-xl border border-border bg-card shadow-sm overflow-hidden">
      <CardHeader className="pb-3 border-b border-border/60">
        <CardTitle className="text-sm font-semibold flex items-center gap-2 text-foreground">
          <Users className="h-4 w-4" />
          共享成员
        </CardTitle>
        {isOwner ? (
          <p className="text-xs text-muted-foreground mt-1">可添加或移除协作者，共同推进此项工作</p>
        ) : (
          <p className="text-xs text-muted-foreground mt-1">你当前以协作者身份参与，可查看成员但不可管理</p>
        )}
      </CardHeader>

      <CardContent className="p-4 md:p-6">
        {initiator && (
          <div className="flex items-center justify-between py-2.5 px-1 mb-1">
            <div className="flex items-center gap-2">
              <div className="h-7 w-7 rounded-full bg-indigo-100 flex items-center justify-center text-xs font-medium text-indigo-700">
                {initiator.display_name.charAt(0)}
              </div>
              <div>
                <div className="text-sm font-medium text-foreground">{initiator.display_name}</div>
              </div>
            </div>
            <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700 font-medium">发起人</span>
          </div>
        )}

        {ownerUserId && ownerDisplayName && (
          <div className="flex items-center justify-between py-2.5 px-1 mb-1">
            <div className="flex items-center gap-2">
              <div className="h-7 w-7 rounded-full bg-blue-100 flex items-center justify-center text-xs font-medium text-blue-700">
                {ownerDisplayName.charAt(0)}
              </div>
              <div>
                <div className="text-sm font-medium text-foreground">{ownerDisplayName}</div>
              </div>
            </div>
            <span className="text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 font-medium">负责人</span>
          </div>
        )}

        {loading ? (
          <p className="text-sm text-muted-foreground py-4 text-center">加载中…</p>
        ) : collaborators.length === 0 ? (
          <p className="text-sm text-muted-foreground py-6 text-center">
            {isOwner ? "当前暂无协作者，可添加成员共同协作" : "当前暂无其他协作者"}
          </p>
        ) : (
          <ul className="divide-y divide-border/60 -mx-1">
            {collaborators.map((c) => {
              const name = nameOf(c);
              return (
                <li key={c.user_id} className="flex items-center justify-between py-2.5 px-1">
                  <div className="flex items-center gap-2">
                    <div className="h-7 w-7 rounded-full bg-primary/10 flex items-center justify-center text-xs font-medium text-primary">
                      {name.charAt(0)}
                    </div>
                    <div>
                      <div className="text-sm font-medium text-foreground">{name}</div>
                      {c.username && (
                        <div className="text-xs text-muted-foreground">{c.username}</div>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700">协作者</span>
                    {isOwner && (
                      <button
                        disabled={busy}
                        onClick={() => handleRemove(c.user_id)}
                        className="text-xs text-muted-foreground hover:text-destructive transition-colors disabled:opacity-50"
                      >
                        移除
                      </button>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}

        {legacyMembers.length > 0 && (
          <div className="mt-4 rounded-md border border-amber-300/60 bg-amber-50/40 p-2">
            <p className="text-xs font-medium text-amber-800 mb-1">待清理旧成员</p>
            <ul className="space-y-1">
              {legacyMembers.map((m) => (
                <li key={m.legacy_key} className="flex items-center justify-between gap-2 text-xs">
                  <span className="text-muted-foreground">{m.display_name}（{m.reason}）</span>
                  {isOwner && onCleanupLegacy ? (
                    <button
                      disabled={busy}
                      onClick={() => {
                        setBusy(true);
                        onCleanupLegacy(m.legacy_key).finally(() => setBusy(false));
                      }}
                      className="text-amber-700 hover:text-amber-900 disabled:opacity-50"
                    >
                      清理
                    </button>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        )}

        {isOwner && (
          <div className="pt-4 mt-4 border-t border-border/60 flex gap-2 items-center">
            {addableUsers.length > 0 ? (
              <>
                <select
                  value={selectedUserId}
                  onChange={(e) => setSelectedUserId(e.target.value ? Number(e.target.value) : "")}
                  className="flex-1 text-sm border border-border rounded-md px-3 py-1.5 bg-background focus:outline-none focus:ring-2 focus:ring-ring"
                >
                  <option value="">选择用户…</option>
                  {addableUsers.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.display_name || u.username}
                    </option>
                  ))}
                </select>
                <button
                  disabled={busy || selectedUserId === ""}
                  onClick={handleAdd}
                  className="text-sm bg-primary text-primary-foreground px-4 py-1.5 rounded-md hover:bg-primary/90 disabled:opacity-50 transition-colors"
                >
                  添加
                </button>
              </>
            ) : (
              <p className="text-xs text-muted-foreground">暂无可添加成员</p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
