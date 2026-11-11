"use client";

import { useState } from "react";
import { Plus, MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useChatContext } from "@/contexts/ChatContext";
import type { Conversation } from "@/types/conversation";
import { cn } from "@/lib/utils";
import { formatLocalTime, parseDateTime } from "@/lib/time";

const SIDER_WIDTH = 288;

function formatRelativeTime(iso: string): string {
  const d = parseDateTime(iso);
  if (!d) return "更早";
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const weekAgo = new Date(today);
  weekAgo.setDate(weekAgo.getDate() - 7);

  const dateOnly = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  if (dateOnly.getTime() === today.getTime()) {
    return formatLocalTime(d);
  }
  if (dateOnly.getTime() === yesterday.getTime()) return "昨天";
  if (dateOnly.getTime() >= weekAgo.getTime()) return "7天内";
  return "更早";
}

function groupConversations(conversations: Conversation[]) {
  const groups: Record<string, Conversation[]> = {
    今天: [],
    昨天: [],
    "7天内": [],
    更早: [],
  };
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const weekAgo = new Date(today);
  weekAgo.setDate(weekAgo.getDate() - 7);

  for (const c of conversations) {
    const d = parseDateTime(c.updatedAt);
    if (!d) {
      groups["更早"].push(c);
      continue;
    }
    const dateOnly = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    if (dateOnly.getTime() === today.getTime()) groups["今天"].push(c);
    else if (dateOnly.getTime() === yesterday.getTime()) groups["昨天"].push(c);
    else if (dateOnly.getTime() >= weekAgo.getTime()) groups["7天内"].push(c);
    else groups["更早"].push(c);
  }
  return groups;
}

export interface ConversationSidebarProps {
  className?: string;
  onSelect?: () => void;
  /** 新建对话按钮文案，默认「新对话」 */
  newConversationLabel?: string;
  /** 是否使用醒目的新建对话按钮（如 AI 助手页左侧栏） */
  prominentNewConversation?: boolean;
  /** 是否禁用固定宽度（移动端抽屉可用） */
  disableFixedWidth?: boolean;
}

export function ConversationSidebar({
  className,
  onSelect,
  newConversationLabel = "新对话",
  prominentNewConversation,
  disableFixedWidth,
}: ConversationSidebarProps) {
  const {
    conversations,
    currentConversation,
    createNewConversation,
    switchConversation,
    deleteConversation,
    renameConversation,
  } = useChatContext();
  const onSelectConversation = switchConversation;
  const [renameId, setRenameId] = useState<number | null>(null);
  const [renameTitle, setRenameTitle] = useState("");
  const [menuOpenId, setMenuOpenId] = useState<number | null>(null);

  const groups = groupConversations(conversations);

  const handleRename = (c: Conversation) => {
    setRenameId(c.id);
    setRenameTitle(c.title);
    setMenuOpenId(null);
  };

  const submitRename = () => {
    if (renameId != null && renameTitle.trim()) {
      renameConversation(renameId, renameTitle.trim());
      setRenameId(null);
      setRenameTitle("");
    }
  };

  const handleDelete = (id: number) => {
    deleteConversation(id);
    setMenuOpenId(null);
  };

  return (
    <div
      className={cn("flex h-full flex-col border-r border-border bg-card", className)}
      style={disableFixedWidth ? undefined : { width: SIDER_WIDTH }}
    >
      <div className="shrink-0 border-b border-border p-2">
        <Button
          type="button"
          variant={prominentNewConversation ? "default" : "outline"}
          className={cn(
            "w-full justify-center gap-2",
            prominentNewConversation && "py-3 text-sm font-semibold"
          )}
          onClick={() => {
            createNewConversation();
            onSelect?.();
          }}
        >
          <Plus className={prominentNewConversation ? "h-5 w-5" : "h-4 w-4"} />
          {newConversationLabel}
        </Button>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        {(["今天", "昨天", "7天内", "更早"] as const).map((label) => {
          const list = groups[label];
          if (list.length === 0) return null;
          return (
            <div key={label} className="mb-4">
              <p className="mb-1.5 px-2 text-xs font-medium text-muted-foreground">{label}</p>
              <ul className="space-y-0.5">
                {list.map((c) => (
                  <li key={c.id}>
                    <div
                      className={cn(
                        "group flex items-center gap-1 rounded-lg px-2 py-2 text-sm cursor-pointer",
                        currentConversation?.id === c.id
                          ? "bg-primary/10 text-foreground"
                          : "text-muted-foreground hover:bg-muted"
                      )}
                      onClick={() => {
                        onSelectConversation(c.id);
                        onSelect?.();
                      }}
                    >
                      <span className="min-w-0 flex-1 truncate" title={c.title}>
                        {c.title}
                        {c.source === "feishu_private" && (
                          <span className="ml-1.5 inline-flex items-center rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                            飞书
                          </span>
                        )}
                      </span>
                      <span className="shrink-0 text-xs text-muted-foreground">
                        {formatRelativeTime(c.updatedAt)}
                      </span>
                      <div className="relative shrink-0">
                        <button
                          type="button"
                          className="p-1 rounded hover:bg-muted opacity-0 group-hover:opacity-100 focus:opacity-100"
                          onClick={(e) => {
                            e.stopPropagation();
                            setMenuOpenId(menuOpenId === c.id ? null : c.id);
                          }}
                          aria-label="菜单"
                        >
                          <MoreHorizontal className="h-4 w-4" />
                        </button>
                        {menuOpenId === c.id && (
                          <>
                            <div
                              className="fixed inset-0 z-10"
                              aria-hidden
                              onClick={() => setMenuOpenId(null)}
                            />
                            <div className="absolute right-0 top-full z-20 mt-0.5 w-32 rounded-md border border-border bg-popover py-1 shadow-md">
                              <button
                                type="button"
                                className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-muted"
                                onClick={() => handleRename(c)}
                              >
                                <Pencil className="h-3.5 w-3.5" />
                                重命名
                              </button>
                              <button
                                type="button"
                                className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm text-destructive hover:bg-muted"
                                onClick={() => handleDelete(c.id)}
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                                删除
                              </button>
                            </div>
                          </>
                        )}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
        {conversations.length === 0 && (
          <p className="px-2 py-4 text-center text-sm text-muted-foreground">暂无对话，点击上方新建</p>
        )}
      </div>

      <Dialog open={renameId != null} onOpenChange={(open) => !open && setRenameId(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>重命名对话</DialogTitle>
          </DialogHeader>
          <Input
            value={renameTitle}
            onChange={(e) => setRenameTitle(e.target.value)}
            placeholder="输入新标题"
            onKeyDown={(e) => e.key === "Enter" && submitRename()}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setRenameId(null)}>
              取消
            </Button>
            <Button onClick={submitRename}>确定</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
