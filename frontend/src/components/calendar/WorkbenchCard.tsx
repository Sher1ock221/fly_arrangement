"use client";

import * as React from "react";
import Link from "next/link";
import { ChevronRight, LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export interface WorkbenchCardProps {
  title: string;
  icon: LucideIcon;
  count?: number;
  description?: string;
  viewAllHref?: string;
  viewAllLabel?: string;
  children: React.ReactNode;
  className?: string;
}

export function WorkbenchCard({
  title,
  icon: Icon,
  count,
  description,
  viewAllHref,
  viewAllLabel = "查看全部",
  children,
  className,
}: WorkbenchCardProps) {
  return (
    <div
      className={cn(
        "rounded-xl border border-border bg-card text-card-foreground shadow-sm transition-shadow hover:shadow",
        "flex flex-col min-h-0 min-w-0",
        className
      )}
    >
      <div className="flex items-start justify-between gap-2 p-3 pb-1.5 sm:p-4 sm:pb-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 min-w-0">
            <Icon className="h-4 w-4 text-muted-foreground shrink-0 sm:h-5 sm:w-5" />
            <h3 className="text-sm font-semibold text-foreground truncate">
              {title}
            </h3>
            {count !== undefined && count > 0 && (
              <span className="shrink-0 rounded-full bg-primary/10 px-1.5 py-0.5 text-xs font-medium text-primary tabular-nums">
                {count}
              </span>
            )}
          </div>
          {description && (
            <p className="mt-0.5 text-xs text-muted-foreground line-clamp-1 sm:line-clamp-2 sm:mt-1 md:block">
              {description}
            </p>
          )}
        </div>
        {viewAllHref && (
          <Link
            href={viewAllHref}
            className="shrink-0 inline-flex items-center min-h-[44px] text-xs text-primary hover:underline focus:outline-none focus:ring-2 focus:ring-primary/20 rounded whitespace-nowrap touch-manipulation active:opacity-90 md:min-h-0"
            title={viewAllLabel}
            aria-label={viewAllLabel}
          >
            {viewAllLabel}
            <ChevronRight className="h-3.5 w-3.5 ml-0.5" />
          </Link>
        )}
      </div>
      <div className="flex-1 min-h-0 min-w-0 px-3 pb-3 pt-0.5 sm:px-4 sm:pb-4 sm:pt-1">
        {children}
      </div>
    </div>
  );
}
