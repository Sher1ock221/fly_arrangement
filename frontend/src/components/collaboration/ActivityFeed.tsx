"use client";
import { useState } from "react";
import { MessageSquare, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatLocalDateTime } from "@/lib/time";

interface ActivityItem {
  id: number;
  content: string;
  created_at: string | null;
  author_display_name?: string | null;
  author_user_id?: number | null;
  update_type?: string;
}

interface Props {
  title: string;
  items: ActivityItem[];
  canAdd: boolean;
  onAdd: (content: string, updateType?: string) => Promise<void>;
  onDelete?: (itemId: number) => Promise<void>;
  currentUserId?: number | null;
  isResourceOwner?: boolean;
  loading?: boolean;
  showTypeSelect?: boolean;
  placeholder?: string;
  subtitle?: string;
}

const TYPE_LABELS: Record<string, string> = {
  progress: "进度",
  note: "备注",
  requirement: "需求",
};

export default function ActivityFeed({
  title, items, canAdd, onAdd, onDelete, currentUserId, isResourceOwner,
  loading, showTypeSelect, placeholder, subtitle,
}: Props) {
  const [content, setContent] = useState("");
  const [updateType, setUpdateType] = useState("note");
  const [busy, setBusy] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const handleSubmit = async () => {
    if (!content.trim()) return;
    setBusy(true);
    try {
      await onAdd(content.trim(), showTypeSelect ? updateType : undefined);
      setContent("");
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (itemId: number) => {
    if (!onDelete) return;
    if (!confirm("确定删除这条记录吗？删除后不可恢复。")) return;
    setDeletingId(itemId);
    try {
      await onDelete(itemId);
      toast.success("记录已删除");
    } catch (e) {
      const msg = e instanceof Error ? e.message : "删除失败";
      toast.error(msg);
    } finally {
      setDeletingId(null);
    }
  };

  const canDeleteItem = (item: ActivityItem) => {
    if (!onDelete) return false;
    if (isResourceOwner) return true;
    if (currentUserId != null && item.author_user_id === currentUserId) return true;
    return false;
  };

  return (
    <Card className="rounded-xl border border-border bg-card shadow-sm overflow-hidden">
      <CardHeader className="pb-3 border-b border-border/60">
        <CardTitle className="text-sm font-semibold flex items-center gap-2 text-foreground">
          <MessageSquare className="h-4 w-4" />
          {title}
        </CardTitle>
        <p className="text-xs text-muted-foreground mt-1">{subtitle || "按时间记录最近协作内容"}</p>
      </CardHeader>

      <CardContent className="p-4 md:p-6">
        {loading ? (
          <p className="text-sm text-muted-foreground py-4 text-center">加载中…</p>
        ) : items.length === 0 ? (
          <p className="text-sm text-muted-foreground py-6 text-center">暂无记录</p>
        ) : (
          <ul className="divide-y divide-border/60 -mx-1 max-h-80 overflow-y-auto">
            {items.map((item) => {
              const authorName = item.author_display_name || "未知";
              return (
                <li key={item.id} className="py-3 px-1 group">
                  <div className="flex items-center gap-2 text-xs mb-1.5">
                    <div className="h-5 w-5 rounded-full bg-primary/10 flex items-center justify-center text-[10px] font-medium text-primary">
                      {authorName.charAt(0)}
                    </div>
                    <span className="font-medium text-foreground">{authorName}</span>
                    {item.update_type && (
                      <span className="bg-muted px-1.5 py-0.5 rounded text-xs text-muted-foreground">
                        {TYPE_LABELS[item.update_type] || item.update_type}
                      </span>
                    )}
                    {item.created_at && (
                      <span className="text-muted-foreground">
                        {formatLocalDateTime(item.created_at)}
                      </span>
                    )}
                    <span className="flex-1" />
                    {canDeleteItem(item) && (
                      <button
                        type="button"
                        title="删除记录"
                        disabled={deletingId === item.id}
                        onClick={() => handleDelete(item.id)}
                        className="opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-destructive disabled:opacity-50 p-0.5 rounded"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </div>
                  <p className="text-sm text-foreground whitespace-pre-wrap break-words pl-7">{item.content}</p>
                </li>
              );
            })}
          </ul>
        )}

        {canAdd && (
          <div className="pt-4 mt-2 border-t border-border/60 space-y-2">
            {showTypeSelect && (
              <select
                value={updateType}
                onChange={(e) => setUpdateType(e.target.value)}
                className="text-sm border border-border rounded-md px-3 py-1.5 w-full bg-background focus:outline-none focus:ring-2 focus:ring-ring"
              >
                <option value="note">备注</option>
                <option value="progress">进度更新</option>
                <option value="requirement">需求补充</option>
              </select>
            )}
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder={placeholder || "输入内容…"}
              className="w-full text-sm border border-border rounded-md px-3 py-2 bg-background resize-none focus:outline-none focus:ring-2 focus:ring-ring"
              rows={2}
            />
            <button
              disabled={busy || !content.trim()}
              onClick={handleSubmit}
              className="text-sm bg-primary text-primary-foreground px-4 py-1.5 rounded-md hover:bg-primary/90 disabled:opacity-50 transition-colors"
            >
              提交
            </button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
