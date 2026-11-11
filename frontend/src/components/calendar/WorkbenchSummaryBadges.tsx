"use client";

import { Calendar, FolderKanban, Users, Bell } from "lucide-react";

export interface WorkbenchSummaryBadgesProps {
  todayEvents: number;
  weekEvents: number;
  projectsDueSoon: number;
  customersTotal: number;
}

export function WorkbenchSummaryBadges({
  todayEvents,
  weekEvents,
  projectsDueSoon,
  customersTotal,
}: WorkbenchSummaryBadgesProps) {
  const items = [
    { label: "今日日程", value: todayEvents, icon: Calendar },
    { label: "本周日程", value: weekEvents, icon: Bell },
    { label: "即将到期项目", value: projectsDueSoon, icon: FolderKanban },
    { label: "待跟进客户", value: customersTotal, icon: Users },
  ];

  return (
    <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:gap-3 md:gap-3">
      {items.map(({ label, value, icon: Icon }) => (
        <span
          key={label}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-2 text-xs text-foreground shadow-sm min-w-0 min-h-[44px] sm:min-h-0 sm:min-w-[120px] md:px-3 md:py-2 md:text-sm"
        >
          <Icon className="h-3.5 w-3.5 text-muted-foreground shrink-0 md:h-4 md:w-4" />
          <span className="text-muted-foreground truncate">{label}</span>
          <span className="font-medium tabular-nums shrink-0">{value}</span>
        </span>
      ))}
    </div>
  );
}
