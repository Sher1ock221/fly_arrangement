"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

export interface WorkbenchSkeletonProps {
  /** 是否显示标题栏 skeleton */
  showHeader?: boolean;
  /** 内容行数 */
  lines?: number;
  className?: string;
}

export function WorkbenchSkeleton({
  showHeader = true,
  lines = 3,
  className,
}: WorkbenchSkeletonProps) {
  return (
    <div className={cn("space-y-3", className)}>
      {showHeader && (
        <div className="flex items-center gap-2">
          <div className="h-4 w-4 rounded bg-muted animate-pulse shrink-0 sm:h-5 sm:w-5" />
          <div className="h-3 w-16 rounded bg-muted animate-pulse sm:h-4 sm:w-24" />
        </div>
      )}
      <div className="space-y-2">
        {Array.from({ length: lines }).map((_, i) => (
          <div
            key={i}
            className="flex items-center gap-3 rounded-lg bg-muted/50 p-2.5 animate-pulse sm:p-3"
            style={{ animationDelay: `${i * 60}ms` }}
          >
            <div className="h-4 flex-1 max-w-[80%] rounded bg-muted/80 sm:h-5" />
            <div className="h-3 w-12 rounded bg-muted/80 shrink-0 sm:h-4 sm:w-14" />
          </div>
        ))}
      </div>
    </div>
  );
}
