"use client";

import * as React from "react";
import { LucideIcon, Inbox } from "lucide-react";
import { cn } from "@/lib/utils";

export interface WorkbenchEmptyStateProps {
  /** 主文案 */
  message: string;
  /** 次级提示 */
  secondary?: string;
  /** 图标，默认 Inbox */
  icon?: LucideIcon;
  className?: string;
}

export function WorkbenchEmptyState({
  message,
  secondary,
  icon: Icon = Inbox,
  className,
}: WorkbenchEmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center py-6 px-3 text-center sm:py-8 sm:px-4",
        className
      )}
    >
      <Icon className="h-9 w-9 text-muted-foreground/60 mb-2 sm:h-10 sm:w-10 sm:mb-3" />
      <p className="text-sm font-medium text-foreground">{message}</p>
      {secondary && (
        <p className="mt-1 text-xs text-muted-foreground line-clamp-2 max-w-[200px]">
          {secondary}
        </p>
      )}
    </div>
  );
}
