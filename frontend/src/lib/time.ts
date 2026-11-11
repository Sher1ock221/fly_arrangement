"use client";

function pad2(value: number): string {
  return String(value).padStart(2, "0");
}

export function normalizeUtcIso(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return trimmed;

  const withT = trimmed.includes(" ") ? trimmed.replace(" ", "T") : trimmed;
  const hasTimezone = /(?:Z|[+-]\d{2}:\d{2})$/i.test(withT);
  const utcLike = /^\d{4}-\d{2}-\d{2}T/.test(withT);
  let normalized = hasTimezone ? withT : utcLike ? `${withT}Z` : withT;

  normalized = normalized.replace(
    /(\.\d{3})\d+(Z|[+-]\d{2}:\d{2})$/i,
    "$1$2"
  );

  return normalized;
}

export function parseDateTime(value: string | Date | null | undefined): Date | null {
  if (value == null) return null;
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value;
  }

  const normalized = normalizeUtcIso(value);
  const parsed = new Date(normalized);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed;
}

export function formatLocalDateTime(
  value: string | Date | null | undefined
): string {
  if (value == null || value === "") return "-";
  const parsed = parseDateTime(value);
  if (!parsed) return typeof value === "string" ? value : "-";

  return `${parsed.getFullYear()}/${pad2(parsed.getMonth() + 1)}/${pad2(
    parsed.getDate()
  )} ${pad2(parsed.getHours())}:${pad2(parsed.getMinutes())}:${pad2(
    parsed.getSeconds()
  )}`;
}

export function formatLocalDate(value: string | Date | null | undefined): string {
  if (value == null || value === "") return "-";
  const parsed = parseDateTime(value);
  if (!parsed) return typeof value === "string" ? value : "-";
  return `${parsed.getFullYear()}/${pad2(parsed.getMonth() + 1)}/${pad2(
    parsed.getDate()
  )}`;
}

export function formatLocalTime(value: string | Date | null | undefined): string {
  if (value == null || value === "") return "-";
  const parsed = parseDateTime(value);
  if (!parsed) return typeof value === "string" ? value : "-";
  return `${pad2(parsed.getHours())}:${pad2(parsed.getMinutes())}`;
}
