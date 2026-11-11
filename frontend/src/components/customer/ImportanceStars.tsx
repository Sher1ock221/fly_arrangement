"use client";

import { Star } from "lucide-react";
import { cn } from "@/lib/utils";

type ImportanceStarsVariant = "compact" | "prominent";

/** 1~5 星级展示，用于沟通记录 importance */
export function ImportanceStars({
  value,
  variant = "compact",
}: {
  value: number | null | undefined;
  variant?: ImportanceStarsVariant;
}) {
  const n = value == null || Number.isNaN(value) ? 0 : Math.min(5, Math.max(0, Math.round(value)));
  const isProminent = variant === "prominent";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1",
        isProminent && "rounded-md bg-amber-500/10 px-2 py-1"
      )}
      aria-label={n ? `重要性 ${n} 星` : "未设置"}
    >
      {isProminent && n > 0 && (
        <span className="text-xs font-medium text-amber-700 dark:text-amber-400">重要性</span>
      )}
      {[1, 2, 3, 4, 5].map((i) => (
        <Star
          key={i}
          className={cn(
            i <= n ? "fill-amber-400 text-amber-500" : "text-muted-foreground/40",
            isProminent ? "h-5 w-5" : "h-4 w-4"
          )}
          aria-hidden
        />
      ))}
      {isProminent && n > 0 && (
        <span className="text-xs text-amber-700/80 dark:text-amber-400/80">{n} 星</span>
      )}
    </span>
  );
}
