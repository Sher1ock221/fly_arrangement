"use client";

import { Bell, Bot, Calendar, ClipboardList, Cpu, LayoutGrid, Settings, Users, UserCircle, ShieldCheck, FileText, Activity, Info, HelpCircle, Database } from "lucide-react";
import type { ComponentType } from "react";

export type NavIcon = ComponentType<{ className?: string }>;

export interface NavItem {
  href: string;
  label: string;
  icon: NavIcon;
}

export const mainNavItems: NavItem[] = [
  { href: "/calendar", label: "日历", icon: Calendar },
  { href: "/projects", label: "项目管理", icon: LayoutGrid },
  { href: "/customers", label: "客户管理", icon: Users },
  { href: "/ai-assistant", label: "AI 助手", icon: Bot },
];

/** 普通用户可见：个人设置、帮助 */
export const userSettingsNavItems: NavItem[] = [
  { href: "/settings/profile", label: "个人设置", icon: UserCircle },
  { href: "/settings/reminders", label: "我的提醒", icon: Bell },
  { href: "/settings/help", label: "帮助", icon: HelpCircle },
];

/** 仅管理员可见（桌面版已隐藏飞书相关入口） */
export const adminSettingsNavItems: NavItem[] = [
  { href: "/settings/dashboard", label: "管理员概览", icon: LayoutGrid },
  { href: "/settings/accounts", label: "账号管理", icon: ShieldCheck },
  { href: "/settings/audit-logs", label: "审计日志", icon: FileText },
  { href: "/settings/system-status", label: "系统状态", icon: Activity },
  { href: "/settings/system-info", label: "系统信息", icon: Info },
  { href: "/settings/ai-config", label: "模型配置", icon: Cpu },
  { href: "/settings/logs", label: "日志与审计", icon: ClipboardList },
  { href: "/settings/data-maintenance", label: "数据维护", icon: Database },
  { href: "/settings/project-governance", label: "项目治理", icon: Activity },
  { href: "/settings/help", label: "帮助", icon: HelpCircle },
];

/** @deprecated 兼容：原“仅管理员”项已合并进 adminSettingsNavItems */
export const settingsNavItems: NavItem[] = [
  { href: "/settings/ai-config", label: "模型配置", icon: Cpu },
  { href: "/settings/logs", label: "日志与审计", icon: ClipboardList },
];

/** 主导航 + 系统设置（仅管理员显示系统设置） */
export function getShellMenuItems(role: string | undefined): NavItem[] {
  const items = [...mainNavItems];
  if (role === "admin") {
    items.push({ href: "/settings/accounts", label: "系统设置", icon: Settings });
  }
  return items;
}

/** @deprecated 使用 getShellMenuItems(role) 以根据角色显示系统设置 */
export const shellMenuItems: NavItem[] = [
  ...mainNavItems,
  { href: "/settings/ai-config", label: "系统设置", icon: Settings },
];

/** pathname 与 href 完全相等，或为 href 的子路径（href 后跟 /），避免 /settings/feishu 匹配到 /settings/feishu-identities */
export function isRouteActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(href + "/");
}

export function getPageTitle(pathname: string): string {
  if (pathname.startsWith("/settings/profile")) return "个人设置";
  if (pathname.startsWith("/settings/reminders")) return "我的提醒";
  if (pathname.startsWith("/settings/dashboard")) return "管理员概览";
  if (pathname.startsWith("/settings/accounts")) return "账号管理";
  if (pathname.startsWith("/settings/audit-logs")) return "审计日志";
  if (pathname.startsWith("/settings/system-status")) return "系统状态";
  if (pathname.startsWith("/settings/system-info")) return "系统信息";
  if (pathname.startsWith("/settings/help")) return "帮助";
  if (pathname.startsWith("/settings/ai-config")) return "模型配置";
  if (pathname.startsWith("/settings/logs")) return "日志与审计";
  if (pathname.startsWith("/settings/data-maintenance")) return "数据维护";
  if (pathname.startsWith("/settings/project-governance")) return "项目治理";
  if (pathname.startsWith("/settings")) return "系统设置";
  if (pathname.startsWith("/calendar")) return "日历";
  if (pathname.startsWith("/projects")) return "项目管理";
  if (pathname.startsWith("/customers")) return "客户管理";
  if (pathname.startsWith("/ai-assistant")) return "AI 助手";
  if (pathname.startsWith("/login")) return "登录";
  return "Fly Arrangement";
}

/** 管理员可见的系统设置菜单（含个人设置 + 管理员项）；普通用户仅个人设置 */
export function getSettingsNavItemsForRole(role: string | undefined): NavItem[] {
  if (role === "admin") {
    return [
      { href: "/settings/profile", label: "个人设置", icon: UserCircle },
      { href: "/settings/reminders", label: "我的提醒", icon: Bell },
      ...adminSettingsNavItems,
    ];
  }
  return userSettingsNavItems;
}
