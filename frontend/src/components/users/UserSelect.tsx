"use client";

import { useMemo, useState } from "react";
import { cn } from "@/lib/utils";

export type SelectableUser = {
  id: number;
  username: string;
  display_name?: string | null;
};

interface UserSelectProps {
  users: SelectableUser[];
  value: number | null;
  onChange: (userId: number | null) => void;
  placeholder?: string;
  disabled?: boolean;
}

export function UserSelect({
  users,
  value,
  onChange,
  placeholder = "搜索并选择负责人",
  disabled,
}: UserSelectProps) {
  const [keyword, setKeyword] = useState("");
  const [open, setOpen] = useState(false);
  const selected = users.find((u) => u.id === value) ?? null;
  const filtered = useMemo(() => {
    const k = keyword.trim().toLowerCase();
    if (!k) return users.slice(0, 10);
    return users
      .filter((u) =>
        `${u.display_name || ""} ${u.username}`.toLowerCase().includes(k)
      )
      .slice(0, 10);
  }, [users, keyword]);

  return (
    <div className="space-y-2">
      {selected ? (
        <div className="flex items-center justify-between rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-sm">
          <span className="truncate">
            当前负责人：{selected.display_name || selected.username} ({selected.username})
          </span>
          <button
            type="button"
            className="ml-2 text-xs text-muted-foreground hover:text-foreground"
            onClick={() => {
              onChange(null);
              setKeyword("");
              setOpen(true);
            }}
            disabled={disabled}
          >
            更换
          </button>
        </div>
      ) : null}
      <input
        type="text"
        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
        placeholder={selected ? "输入关键词筛选并重新选择负责人" : placeholder}
        value={keyword}
        onFocus={() => setOpen(true)}
        onChange={(e) => {
          setKeyword(e.target.value);
          setOpen(true);
        }}
        disabled={disabled}
      />
      <div className={cn("max-h-44 overflow-auto rounded-md border border-border bg-card p-1", !open && "hidden")}>
        {filtered.length === 0 ? (
          <div className="px-2 py-1.5 text-xs text-muted-foreground">未找到匹配用户，请换个关键词</div>
        ) : (
          filtered.map((u) => {
            const label = `${u.display_name || u.username} (${u.username})`;
            const active = value === u.id;
            return (
              <button
                key={u.id}
                type="button"
                className={cn(
                  "w-full rounded px-2 py-1.5 text-left text-sm transition-colors",
                  active ? "bg-primary/10 text-primary font-medium" : "hover:bg-muted"
                )}
                onClick={() => {
                  onChange(u.id);
                  setKeyword("");
                  setOpen(false);
                }}
              >
                {label}
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}

