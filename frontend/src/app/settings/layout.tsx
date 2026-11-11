"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { cn } from "@/lib/utils";
import { ScrollArea } from "@/components/ui/scroll-area";
import { getPageTitle, isRouteActive, getSettingsNavItemsForRole } from "@/components/navigation/nav-items";
import { useAuth } from "@/contexts/AuthContext";
import { useQuery } from "@tanstack/react-query";
import { adminApi, getStoredToken } from "@/lib/apiClient";
import { queryKeys } from "@/lib/queryKeys";

export default function SettingsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const pageTitle = getPageTitle(pathname);
  const { user, loading, token } = useAuth();
  const navItems = getSettingsNavItemsForRole(user?.role);

  const { data: projectGovernanceSummary } = useQuery({
    queryKey: queryKeys.projectGovernanceSummary(),
    queryFn: () => adminApi.projectGovernanceSummary(token ?? getStoredToken()),
    enabled: user?.role === "admin" && !!(token ?? getStoredToken()),
    refetchInterval: 60000,
    staleTime: 30000,
  });

  const overdueCount = Number(projectGovernanceSummary?.overdue_repair_queue_count ?? 0);
  const activeCount = Number(projectGovernanceSummary?.manual_repair_queue_count ?? 0);
  const hasOverdue = overdueCount > 0;
  const hasActive = activeCount > 0;

  const badgeText = hasOverdue ? (overdueCount > 99 ? "99+" : String(overdueCount)) : hasActive ? (activeCount > 99 ? "99+" : String(activeCount)) : null;
  const badgeTitle = hasOverdue
    ? `当前有 ${overdueCount} 条超时中的治理问题；当前有 ${activeCount} 条活跃治理问题`
    : hasActive
      ? `当前有 ${activeCount} 条活跃治理问题`
      : undefined;

  const adminOnlyPaths = [
    "/settings/dashboard",
    "/settings/accounts",
    "/settings/audit-logs",
    "/settings/system-status",
    "/settings/system-info",
    "/settings/ai-config",
    "/settings/logs",
    "/settings/data-maintenance",
    "/settings/project-governance",
  ];
  const isAdminOnly = adminOnlyPaths.some((p) => pathname === p || pathname.startsWith(p + "/"));

  useEffect(() => {
    if (loading) return;
    if (!user) {
      router.replace("/login");
      return;
    }
    if (pathname === "/settings" || pathname === "/settings/") {
      router.replace(user.role === "admin" ? "/settings/dashboard" : "/settings/profile");
      return;
    }
    if (isAdminOnly && user.role !== "admin") {
      router.replace("/settings/profile");
    }
  }, [loading, user, pathname, router, isAdminOnly]);

  if (loading || !user) {
    return (
      <div className="flex flex-col h-full items-center justify-center p-8 text-muted-foreground">
        <p>加载中…</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="border-b border-border bg-card px-4 md:px-6 py-3 md:py-4 shrink-0">
        <h1 className="text-lg md:text-xl font-semibold">{pageTitle}</h1>
      </div>
      <div className="md:hidden border-b border-border bg-card">
        <ScrollArea className="w-full">
          <nav className="flex gap-1 px-3 py-2" aria-label="设置导航">
            {navItems.map(({ href, label, icon: Icon }) => {
              const isActive = isRouteActive(pathname, href);
              return (
                <Link
                  key={href}
                  href={href}
                  className={cn(
                    "inline-flex items-center gap-2 rounded-md px-3 py-2 text-sm whitespace-nowrap",
                    isActive
                      ? "bg-primary/15 text-primary"
                      : "text-muted-foreground hover:bg-muted"
                  )}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  {label}
                  {href === "/settings/project-governance" && badgeText ? (
                    <span
                      title={badgeTitle}
                      className={cn(
                        "ml-2 inline-flex items-center justify-center rounded-full px-1.5 py-0.5 text-[10px] font-semibold",
                        hasOverdue
                          ? "bg-orange-500 text-white"
                          : "bg-primary/20 text-primary border border-primary/30"
                      )}
                    >
                      {badgeText}
                    </span>
                  ) : null}
                </Link>
              );
            })}
          </nav>
        </ScrollArea>
      </div>
      <div className="hidden md:flex flex-1 min-h-0">
        <nav
          className="w-52 shrink-0 border-r border-border bg-card p-3"
          aria-label="设置导航"
        >
          <ul className="space-y-0.5">
            {navItems.map(({ href, label, icon: Icon }) => {
              const isActive = isRouteActive(pathname, href);
              return (
                <li key={href}>
                  <Link
                    href={href}
                    className={cn(
                      "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                      isActive
                        ? "bg-primary/15 text-primary hover:bg-primary/15"
                        : "text-muted-foreground hover:bg-muted"
                    )}
                  >
                    <Icon className="h-5 w-5 shrink-0" />
                    <span className="flex items-center gap-2">
                      <span>{label}</span>
                      {href === "/settings/project-governance" && badgeText ? (
                        <span
                          title={badgeTitle}
                          className={cn(
                            "inline-flex items-center justify-center rounded-full px-1.5 py-0.5 text-[10px] font-semibold",
                            hasOverdue
                              ? "bg-orange-500 text-white"
                              : "bg-primary/20 text-primary border border-primary/30"
                          )}
                        >
                          {badgeText}
                        </span>
                      ) : null}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
        <ScrollArea className="flex-1 min-h-0">
          <div className="p-4 md:p-6">{children}</div>
        </ScrollArea>
      </div>
      <ScrollArea className="md:hidden flex-1 min-h-0">
        <div className="p-4">{children}</div>
      </ScrollArea>
    </div>
  );
}
