"use client";

import { Calendar } from "lucide-react";

export interface CalendarWorkbenchHeaderProps {
  todayCount?: number;
  weekCount?: number;
}

export function CalendarWorkbenchHeader({
  todayCount = 0,
  weekCount = 0,
}: CalendarWorkbenchHeaderProps) {
  return (
    <header className="shrink-0">
      <div className="flex flex-col gap-0.5 md:gap-1">
        <h1 className="text-xl font-semibold text-foreground tracking-tight flex items-center gap-2 md:text-2xl">
          <Calendar className="h-6 w-6 text-primary shrink-0 md:h-7 md:w-7" />
          <span className="truncate">日历</span>
        </h1>
        <p className="text-xs text-muted-foreground line-clamp-1 sm:line-clamp-2 md:text-sm">
          查看今天的安排、近期项目与待跟进事项
        </p>
      </div>
      {(todayCount > 0 || weekCount > 0) && (
        <div className="mt-2 flex flex-wrap gap-2 md:mt-3">
          {todayCount > 0 && (
            <span className="inline-flex items-center rounded-full bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary md:px-3">
              今日 {todayCount} 项日程
            </span>
          )}
          {weekCount > 0 && (
            <span className="inline-flex items-center rounded-full bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground md:px-3">
              本周 {weekCount} 项
            </span>
          )}
        </div>
      )}
    </header>
  );
}
