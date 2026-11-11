"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/lib/queryKeys";
import { CalendarView } from "@/components/calendar/CalendarView";
import { CalendarDrawer } from "@/components/calendar/CalendarDrawer";
import { CalendarWorkbenchHeader } from "@/components/calendar/CalendarWorkbenchHeader";
import { WorkbenchSummaryBadges } from "@/components/calendar/WorkbenchSummaryBadges";
import { WorkbenchCard } from "@/components/calendar/WorkbenchCard";
import { WorkbenchEmptyState } from "@/components/calendar/WorkbenchEmptyState";
import { WorkbenchSkeleton } from "@/components/calendar/WorkbenchSkeleton";
import { useMobile } from "@/hooks/use-mobile";
import { calendarApi, projectsApi, customersApi } from "@/lib/apiClient";
import {
  getUpcomingRange,
  getTodayStartEnd,
  getWeekStartEnd,
  formatEventDate,
  formatEventTime,
  formatDateShort,
} from "@/lib/dateUtils";
import {
  Calendar as CalendarIcon,
  FolderKanban,
  Users,
  Bell,
  ChevronRight,
  CalendarX,
  FolderOpen,
  UserX,
} from "lucide-react";

const LIMIT = 5;
const MOBILE_LIMIT = 3;

export default function CalendarPage() {
  const queryClient = useQueryClient();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const isMobile = useMobile();
  const cardLimit = isMobile ? MOBILE_LIMIT : LIMIT;

  const { start: upcomingStart, end: upcomingEnd } = getUpcomingRange(30);
  const { start: todayStart, end: todayEnd } = getTodayStartEnd();
  const { start: weekStart, end: weekEnd } = getWeekStartEnd();

  const workbenchEventsQuery = useQuery({
    queryKey: [...queryKeys.calendarEvents(), "upcoming", upcomingStart, upcomingEnd, "self"],
    queryFn: () => calendarApi.listEvents({ start: upcomingStart, end: upcomingEnd }),
    staleTime: 2 * 60 * 1000,
    refetchOnWindowFocus: false,
  });
  const upcomingEvents = useMemo(() => workbenchEventsQuery.data ?? [], [workbenchEventsQuery.data]);
  const eventsLoading = workbenchEventsQuery.isLoading;

  const todayEvents = useMemo(
    () => upcomingEvents.filter((ev) => ev.start_time >= todayStart && ev.start_time <= todayEnd),
    [upcomingEvents, todayStart, todayEnd]
  );
  const weekEvents = useMemo(
    () => upcomingEvents.filter((ev) => ev.start_time >= weekStart && ev.start_time <= weekEnd),
    [upcomingEvents, weekStart, weekEnd]
  );

  const { data: projects = [], isLoading: projectsLoading } = useQuery({
    queryKey: [...queryKeys.projects(), "list", "self"],
    queryFn: () => projectsApi.list(),
    staleTime: 2 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const { data: customers = [], isLoading: customersLoading } = useQuery({
    queryKey: [...queryKeys.customers(), "list", "self"],
    queryFn: () => customersApi.list(),
    staleTime: 2 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const upcomingSorted = useMemo(() => {
    const list = [...upcomingEvents].sort(
      (a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime()
    );
    return list.slice(0, cardLimit);
  }, [upcomingEvents, cardLimit]);

  const recentProjects = useMemo(() => {
    const list = [...projects].sort((a, b) => {
      const aDate = a.update_date ? new Date(a.update_date).getTime() : 0;
      const bDate = b.update_date ? new Date(b.update_date).getTime() : 0;
      return bDate - aDate;
    });
    return list.slice(0, cardLimit);
  }, [projects, cardLimit]);

  const recentCustomers = useMemo(() => {
    const list = [...customers].sort((a, b) => {
      const aDate = a.updated_at ? new Date(a.updated_at).getTime() : 0;
      const bDate = b.updated_at ? new Date(b.updated_at).getTime() : 0;
      return bDate - aDate;
    });
    return list.slice(0, cardLimit);
  }, [customers, cardLimit]);

  const now = Date.now();
  const sevenDaysLater = now + 7 * 24 * 60 * 60 * 1000;
  const projectsDueSoon = projects.filter((p) => {
    if (!p.deadline) return false;
    const t = new Date(p.deadline).getTime();
    return t >= now && t <= sevenDaysLater;
  });

  const handleSelectDate = (date: string) => {
    setSelectedDate(date);
    setDrawerOpen(true);
  };

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="mx-auto w-full max-w-5xl xl:max-w-6xl flex flex-col flex-1 min-h-0 px-3 py-4 sm:px-4 sm:py-5 md:px-5 md:py-6 lg:px-6 lg:py-8">
        {/* 顶部欢迎区 */}
        <CalendarWorkbenchHeader
          todayCount={todayEvents.length}
          weekCount={weekEvents.length}
        />

        {/* 摘要条 */}
        <div className="mt-3 md:mt-4">
          <WorkbenchSummaryBadges
            todayEvents={todayEvents.length}
            weekEvents={weekEvents.length}
            projectsDueSoon={projectsDueSoon.length}
            customersTotal={customers.length}
          />
        </div>

        {/* 月历主卡片 */}
        <div className="mt-5 shrink-0 sm:mt-6 lg:mt-8">
          <div className="rounded-xl border border-border bg-card shadow-sm overflow-hidden">
            <CalendarView onSelectDate={handleSelectDate} />
          </div>
        </div>

        {/* 下方工作台卡片区 */}
        <div className="mt-5 flex-1 min-h-0 overflow-auto sm:mt-6 lg:mt-8">
          <h2 className="text-sm font-medium text-foreground mb-3 sm:text-base sm:mb-4">概览</h2>
          <div className="grid grid-cols-1 gap-3 pb-4 sm:gap-4 lg:grid-cols-2 xl:grid-cols-4 lg:gap-5">
            {/* 待处理行程 */}
            <WorkbenchCard
              title="待处理行程"
              icon={CalendarIcon}
              count={upcomingSorted.length}
              description="优先处理即将到来的安排"
              viewAllHref="/calendar"
              viewAllLabel="查看日历"
            >
              {eventsLoading ? (
                <WorkbenchSkeleton showHeader={false} lines={3} />
              ) : upcomingSorted.length === 0 ? (
                <WorkbenchEmptyState
                  icon={CalendarX}
                  message="暂无待处理行程"
                  secondary="今天安排比较轻松，可前往日历新增行程"
                />
              ) : (
                <ul className="space-y-1.5 sm:space-y-2">
                  {upcomingSorted.map((ev) => (
                    <li key={ev.id}>
                      <Link
                        href="/calendar"
                        onClick={() => {
                          setSelectedDate(ev.start_time.slice(0, 10));
                          setDrawerOpen(true);
                        }}
                        className="flex items-start gap-2 rounded-lg border border-border bg-muted/30 px-3 py-3 text-sm min-h-[44px] touch-manipulation active:opacity-90 hover:bg-muted/50 hover:border-muted-foreground/15 transition-colors sm:gap-3 sm:py-2.5"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="font-medium truncate">{ev.title}</div>
                          <div className="text-xs text-muted-foreground mt-0.5 truncate">
                            {formatEventDate(ev.start_time)} {formatEventTime(ev.start_time)}
                          </div>
                        </div>
                        <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </WorkbenchCard>

            {/* 近期项目 */}
            <WorkbenchCard
              title="近期项目"
              icon={FolderKanban}
              count={recentProjects.length}
              description="跟进最近更新或即将到期的项目"
              viewAllHref="/projects"
              viewAllLabel="前往项目"
            >
              {projectsLoading ? (
                <WorkbenchSkeleton showHeader={false} lines={3} />
              ) : recentProjects.length === 0 ? (
                <WorkbenchEmptyState
                  icon={FolderOpen}
                  message="暂无近期项目"
                  secondary="当前还没有可展示的项目，可前往项目管理创建"
                />
              ) : (
                <ul className="space-y-1.5 sm:space-y-2">
                  {recentProjects.map((p) => (
                    <li key={p.id}>
                      <Link
                        href={`/projects/${p.id}`}
                        className="flex items-start gap-2 rounded-lg border border-border bg-muted/30 px-3 py-3 text-sm min-h-[44px] touch-manipulation active:opacity-90 hover:bg-muted/50 hover:border-muted-foreground/15 transition-colors sm:gap-3 sm:py-2.5"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="font-medium truncate">{p.name}</div>
                          <div className="text-xs text-muted-foreground mt-0.5 flex items-center gap-2 min-w-0">
                            {p.deadline && <span className="truncate">截止 {formatDateShort(p.deadline)}</span>}
                            {p.owner && <span className="truncate shrink-0">· {p.owner}</span>}
                          </div>
                        </div>
                        <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </WorkbenchCard>

            {/* 待跟进客户 */}
            <WorkbenchCard
              title="待跟进客户"
              icon={Users}
              count={recentCustomers.length}
              description="及时处理近期需要跟进的客户"
              viewAllHref="/customers"
              viewAllLabel="前往客户"
            >
              {customersLoading ? (
                <WorkbenchSkeleton showHeader={false} lines={3} />
              ) : recentCustomers.length === 0 ? (
                <WorkbenchEmptyState
                  icon={UserX}
                  message="暂无待跟进客户"
                  secondary="可前往客户管理查看详情"
                />
              ) : (
                <ul className="space-y-1.5 sm:space-y-2">
                  {recentCustomers.map((c) => (
                    <li key={c.id}>
                      <Link
                        href={`/customers/${c.id}`}
                        className="flex items-start gap-2 rounded-lg border border-border bg-muted/30 px-3 py-3 text-sm min-h-[44px] touch-manipulation active:opacity-90 hover:bg-muted/50 hover:border-muted-foreground/15 transition-colors sm:gap-3 sm:py-2.5"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="font-medium truncate">{c.name}</div>
                          <div className="text-xs text-muted-foreground mt-0.5 truncate">
                            {c.updated_at && `更新于 ${formatDateShort(c.updated_at)}`}
                            {c.company && ` · ${c.company}`}
                          </div>
                        </div>
                        <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </WorkbenchCard>

            {/* 本周提醒 */}
            <WorkbenchCard
              title="本周提醒"
              icon={Bell}
              count={weekEvents.length + projectsDueSoon.length}
              description="快速了解今天与本周的重点"
              viewAllHref="/calendar"
              viewAllLabel="查看日历"
            >
              <div className="space-y-1.5 sm:space-y-2">
                <div className="flex items-center justify-between gap-2 rounded-lg border border-border bg-muted/30 px-3 py-3 min-h-[44px] hover:bg-muted/40 transition-colors sm:py-2.5">
                  <span className="text-xs text-muted-foreground sm:text-sm truncate">今日日程</span>
                  <span className="text-sm font-semibold tabular-nums shrink-0">{todayEvents.length}</span>
                </div>
                <div className="flex items-center justify-between gap-2 rounded-lg border border-border bg-muted/30 px-3 py-3 min-h-[44px] hover:bg-muted/40 transition-colors sm:py-2.5">
                  <span className="text-xs text-muted-foreground sm:text-sm truncate">本周日程</span>
                  <span className="text-sm font-semibold tabular-nums shrink-0">{weekEvents.length}</span>
                </div>
                <div className="flex items-center justify-between gap-2 rounded-lg border border-border bg-muted/30 px-3 py-3 min-h-[44px] hover:bg-muted/40 transition-colors sm:py-2.5">
                  <span className="text-xs text-muted-foreground sm:text-sm truncate">7 日内截止</span>
                  <span className="text-sm font-semibold tabular-nums shrink-0">{projectsDueSoon.length}</span>
                </div>
                <div className="flex items-center justify-between gap-2 rounded-lg border border-border bg-muted/30 px-3 py-3 min-h-[44px] hover:bg-muted/40 transition-colors sm:py-2.5">
                  <span className="text-xs text-muted-foreground sm:text-sm truncate">待跟进客户</span>
                  <span className="text-sm font-semibold tabular-nums shrink-0">{customers.length}</span>
                </div>
              </div>
              <div className="mt-2 flex flex-wrap gap-x-3 gap-y-2 pt-2 border-t border-border sm:mt-3 sm:gap-2">
                <Link href="/calendar" className="inline-flex items-center text-xs text-primary hover:underline min-h-[44px] items-center touch-manipulation py-1">
                  查看日历 <ChevronRight className="h-3 w-3 ml-0.5" />
                </Link>
                <Link href="/projects" className="inline-flex items-center text-xs text-primary hover:underline min-h-[44px] items-center touch-manipulation py-1">
                  前往项目 <ChevronRight className="h-3 w-3 ml-0.5" />
                </Link>
                <Link href="/customers" className="inline-flex items-center text-xs text-primary hover:underline min-h-[44px] items-center touch-manipulation py-1">
                  前往客户 <ChevronRight className="h-3 w-3 ml-0.5" />
                </Link>
              </div>
            </WorkbenchCard>
          </div>
        </div>
      </div>

      <CalendarDrawer
        open={drawerOpen}
        date={selectedDate}
        onClose={() => {
          setDrawerOpen(false);
          setSelectedDate(null);
        }}
        onRefresh={() => {
          queryClient.invalidateQueries({ queryKey: queryKeys.calendarEvents() });
        }}
      />
    </div>
  );
}
