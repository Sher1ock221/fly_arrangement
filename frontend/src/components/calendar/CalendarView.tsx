"use client";

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { calendarApi } from "@/lib/apiClient";
import { cn } from "@/lib/utils";

const WEEKDAYS = ["日", "一", "二", "三", "四", "五", "六"];

function getMonthStartEnd(year: number, month: number) {
  const pad = (n: number) => String(n).padStart(2, "0");
  const start = `${year}-${pad(month)}-01T00:00:00`;
  const lastDay = new Date(year, month, 0).getDate();
  const end = `${year}-${pad(month)}-${pad(lastDay)}T23:59:59`;
  return { start, end };
}

function getCalendarDays(year: number, month: number): { date: string; day: number; isCurrentMonth: boolean }[] {
  const first = new Date(year, month - 1, 1);
  const last = new Date(year, month, 0);
  const startWeekday = first.getDay();
  const days: { date: string; day: number; isCurrentMonth: boolean }[] = [];
  const pad = (n: number) => String(n).padStart(2, "0");

  for (let i = 0; i < startWeekday; i++) {
    const d = new Date(year, month - 1, -startWeekday + i + 1);
    days.push({
      date: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`,
      day: d.getDate(),
      isCurrentMonth: false,
    });
  }
  for (let d = 1; d <= last.getDate(); d++) {
    days.push({
      date: `${year}-${pad(month)}-${pad(d)}`,
      day: d,
      isCurrentMonth: true,
    });
  }
  const rest = 42 - days.length;
  for (let i = 1; i <= rest; i++) {
    const d = new Date(year, month, i);
    days.push({
      date: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`,
      day: d.getDate(),
      isCurrentMonth: false,
    });
  }
  return days;
}

export interface CalendarViewProps {
  onSelectDate: (date: string) => void;
}

export function CalendarView({ onSelectDate }: CalendarViewProps) {
  const [year, setYear] = useState(() => new Date().getFullYear());
  const [month, setMonth] = useState(() => new Date().getMonth() + 1);

  const { start, end } = useMemo(
    () => getMonthStartEnd(year, month),
    [year, month]
  );

  const { data: events = [] } = useQuery({
    queryKey: ["calendar", "events", year, month, start, end],
    queryFn: () => calendarApi.listEvents({ start, end }),
    staleTime: 2 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const eventsByDate = useMemo(() => {
    const map: Record<string, typeof events> = {};
    for (const ev of events) {
      const d = ev.start_time.slice(0, 10);
      if (!map[d]) map[d] = [];
      map[d].push(ev);
    }
    return map;
  }, [events]);

  const days = useMemo(() => getCalendarDays(year, month), [year, month]);

  const prevMonth = () => {
    if (month === 1) {
      setMonth(12);
      setYear((y) => y - 1);
    } else {
      setMonth((m) => m - 1);
    }
  };

  const nextMonth = () => {
    if (month === 12) {
      setMonth(1);
      setYear((y) => y + 1);
    } else {
      setMonth((m) => m + 1);
    }
  };

  const today = new Date();
  const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;

  const goToToday = () => {
    const n = new Date();
    setYear(n.getFullYear());
    setMonth(n.getMonth() + 1);
  };

  const isCurrentMonth = year === today.getFullYear() && month === today.getMonth() + 1;

  return (
    <div className="rounded-lg overflow-hidden">
      <div className="flex items-center justify-between border-b border-border px-2 py-2 bg-muted/30 sm:px-4 sm:py-3">
        <button
          type="button"
          onClick={prevMonth}
          className="rounded-md p-2 min-h-[44px] min-w-[44px] hover:bg-muted text-muted-foreground transition-colors touch-manipulation active:opacity-80 sm:p-2"
          aria-label="上一月"
        >
          ‹
        </button>
        <h2 className="text-sm font-semibold text-foreground truncate px-1 sm:text-base md:text-lg">
          {year} 年 {month} 月
        </h2>
        <div className="flex items-center gap-1 shrink-0">
          {!isCurrentMonth && (
            <button
              type="button"
              onClick={goToToday}
              className="rounded-md px-2 py-2 min-h-[44px] text-xs font-medium bg-primary text-primary-foreground hover:opacity-90 active:opacity-95 transition-opacity touch-manipulation sm:px-3 sm:py-1.5 sm:min-h-0"
            >
              今天
            </button>
          )}
          <button
            type="button"
            onClick={nextMonth}
            className="rounded-md p-2 min-h-[44px] min-w-[44px] hover:bg-muted text-muted-foreground transition-colors touch-manipulation active:opacity-80 sm:p-2"
            aria-label="下一月"
          >
            ›
          </button>
        </div>
      </div>

      <div className="grid grid-cols-7 text-center text-[10px] sm:text-xs md:text-sm">
        {WEEKDAYS.map((w) => (
          <div key={w} className="border-b border-border py-1 font-medium text-muted-foreground sm:py-1.5 md:py-2">
            {w}
          </div>
        ))}
        {days.map(({ date: d, day, isCurrentMonth }) => {
          const dayEvents = eventsByDate[d] ?? [];
          const isToday = d === todayStr;
          const count = dayEvents.length;
          return (
            <button
              key={d}
              type="button"
              onClick={() => onSelectDate(d)}
              className={cn(
                "min-h-[44px] border-b border-r border-border p-1 text-left hover:bg-muted/50 active:bg-muted/70 transition-colors touch-manipulation sm:min-h-[56px] sm:p-1.5 md:min-h-[68px] lg:min-h-[80px] md:p-2",
                !isCurrentMonth && "bg-muted/30 text-muted-foreground",
                isToday && "ring-2 ring-inset ring-primary bg-primary/5"
              )}
            >
              <span
                className={cn(
                  "inline-flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-medium sm:h-6 sm:w-6 sm:text-xs md:h-7 md:w-7 md:text-sm",
                  isToday && "bg-primary text-primary-foreground ring-2 ring-primary ring-offset-2 ring-offset-background"
                )}
              >
                {day}
              </span>
              {count > 0 && (
                <>
                  {/* 窄屏：仅显示圆点或数量 */}
                  <div className="mt-0.5 flex items-center justify-center gap-0.5 sm:hidden">
                    {count <= 3 ? (
                      Array.from({ length: count }).map((_, i) => (
                        <span key={i} className="h-1 w-1 rounded-full bg-primary shrink-0" title={dayEvents[i]?.title} />
                      ))
                    ) : (
                      <span className="text-[10px] font-medium text-primary tabular-nums" title={dayEvents.map((e) => e.title).join("\n")}>
                        {count}
                      </span>
                    )}
                  </div>
                  {/* 宽屏：显示事件标题 */}
                  <div className="mt-0.5 hidden space-y-0.5 overflow-hidden sm:block sm:mt-1">
                    {dayEvents.slice(0, 2).map((ev) => (
                      <div
                        key={ev.id}
                        className="truncate rounded px-1 py-0.5 text-[10px] bg-primary/10 text-foreground md:text-xs md:px-1.5"
                        title={ev.title}
                      >
                        {ev.title}
                      </div>
                    ))}
                    {count > 2 && (
                      <div className="text-[10px] text-muted-foreground md:text-xs">+{count - 2}</div>
                    )}
                  </div>
                </>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
