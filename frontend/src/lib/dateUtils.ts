"use client";

import { useMemo } from "react";

function toISO(date: Date): string {
  return date.toISOString().slice(0, 19);
}

export function getTodayStartEnd(): { start: string; end: string } {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  const start = toISO(d);
  d.setHours(23, 59, 59, 999);
  const end = toISO(d);
  return { start, end };
}

export function getWeekStartEnd(): { start: string; end: string } {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  const start = toISO(d);
  const e = new Date(d);
  e.setDate(e.getDate() + 6);
  e.setHours(23, 59, 59, 999);
  const end = toISO(e);
  return { start, end };
}

export function getUpcomingRange(days: number): { start: string; end: string } {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  const start = toISO(d);
  const e = new Date(d);
  e.setDate(e.getDate() + days);
  e.setHours(23, 59, 59, 999);
  const end = toISO(e);
  return { start, end };
}

export function formatEventDate(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const tomorrow = new Date(today);
  tomorrow.setDate(tomorrow.getDate() + 1);
  const dDay = new Date(d);
  dDay.setHours(0, 0, 0, 0);
  if (dDay.getTime() === today.getTime()) return "今日";
  if (dDay.getTime() === tomorrow.getTime()) return "明日";
  if (dDay.getTime() < today.getTime()) return "已过期";
  return d.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
}

export function formatEventTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
}

export function formatDateShort(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric", year: "numeric" });
}
