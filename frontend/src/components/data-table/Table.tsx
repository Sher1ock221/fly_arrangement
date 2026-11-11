"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

/** 表格根容器，配合 rounded border */
export function TableRoot({
  className,
  ...props
}: React.HTMLAttributes<HTMLTableElement>) {
  return (
    <table
      className={cn("w-full border-collapse", className)}
      {...props}
    />
  );
}

/** 表头：极浅灰底、小号字、加粗、大写间距 */
export function TableHead({
  className,
  ...props
}: React.HTMLAttributes<HTMLTableSectionElement>) {
  return (
    <thead
      className={cn("bg-muted/60 backdrop-blur supports-[backdrop-filter]:bg-muted/55", className)}
      {...props}
    />
  );
}

export function TableBody({
  className,
  ...props
}: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={cn(className)} {...props} />;
}

/** 表头单元格：统一内边距、最小高度、列宽由 className 控制 */
export function TableHeadCell({
  className,
  ...props
}: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={cn(
        "px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-foreground",
        "min-h-[3rem] border-b border-border/80",
        className
      )}
      {...props}
    />
  );
}

/** 表格行：最小高度、hover 过渡 */
export function TableRow({
  className,
  ...props
}: React.HTMLAttributes<HTMLTableRowElement>) {
  return (
    <tr
      className={cn(
        "border-b border-border min-h-[3rem] transition-colors hover:bg-slate-50/50 dark:hover:bg-slate-500/10",
        "odd:bg-background even:bg-muted/[0.15]",
        className
      )}
      {...props}
    />
  );
}

/** 表格单元格：统一内边距 px-4 py-3，overflow-hidden 防止编辑框溢出 */
export function TableCell({
  className,
  ...props
}: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return (
    <td
      className={cn(
        "px-4 py-3 align-middle text-sm relative overflow-hidden",
        "min-h-[3.25rem]",
        className
      )}
      {...props}
    />
  );
}

/** 空状态占位单元格 */
export function TableCellEmpty({
  colSpan,
  className,
  children = "暂无数据",
  ...props
}: React.TdHTMLAttributes<HTMLTableCellElement> & { colSpan: number }) {
  return (
    <td
      colSpan={colSpan}
      className={cn(
        "px-4 py-8 text-center text-muted-foreground text-sm",
        className
      )}
      {...props}
    >
      {children}
    </td>
  );
}
