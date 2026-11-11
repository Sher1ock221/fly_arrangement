"use client";

import Link from "next/link";
import { Menu, X, Settings, LayoutGrid, LogIn, LogOut } from "lucide-react";
import { usePathname } from "next/navigation";
import { useState, useEffect } from "react";
import { ChatWidget } from "@/components/chat/ChatWidget";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Sidebar } from "@/components/sidebar";
import { useMobile } from "@/hooks/use-mobile";
import { useSwipeDismiss } from "@/hooks/use-swipe-dismiss";
import { cn } from "@/lib/utils";
import { getPageTitle, isRouteActive, mainNavItems } from "@/components/navigation/nav-items";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const isMobile = useMobile();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const swipeDismissHandlers = useSwipeDismiss({
    onDismiss: () => setMobileMenuOpen(false),
  });
  const isAiAssistant = pathname === "/ai-assistant" || pathname?.startsWith("/ai-assistant/");
  const pageTitle = getPageTitle(pathname);

  useEffect(() => {
    if (!isMobile) return;
    if (mobileMenuOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [isMobile, mobileMenuOpen]);

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main
        className={cn(
          "flex-1 min-w-0 bg-background",
          isMobile ? "overflow-hidden" : "overflow-auto"
        )}
      >
        {isMobile && (
          <header className="h-14 shrink-0 border-b border-border bg-card px-2 flex items-center justify-between gap-2">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => setMobileMenuOpen(true)}
              aria-label="打开菜单"
              className="min-h-[44px] min-w-[44px] touch-manipulation"
            >
              <Menu className="h-5 w-5" />
            </Button>
            <h1 className="text-sm font-semibold truncate flex-1 min-w-0 text-center">{pageTitle}</h1>
            <Button asChild type="button" variant="ghost" size="sm" className="min-h-[44px] min-w-[44px] touch-manipulation px-2">
              <Link href="/ai-assistant">AI</Link>
            </Button>
          </header>
        )}
        {user?.must_change_password && (
          <div className="shrink-0 border-b border-amber-500/50 bg-amber-50 dark:bg-amber-950/30 px-4 py-2 flex items-center justify-between gap-2">
            <p className="text-sm text-amber-800 dark:text-amber-200">
              你当前需要修改密码后再继续安全使用系统。
            </p>
            <Link href="/settings/profile">
              <Button variant="outline" size="sm" className="border-amber-600 text-amber-800 dark:text-amber-200">
                去修改密码
              </Button>
            </Link>
          </div>
        )}
        <div
          className={cn(
            "min-h-0",
            isMobile
              ? "h-[calc(100%-3.5rem)] overflow-auto"
              : isAiAssistant
                ? "h-full"
                : ""
          )}
        >
          {children}
        </div>
      </main>
      {!isAiAssistant && <ChatWidget />}

      <Dialog open={isMobile && mobileMenuOpen} onOpenChange={setMobileMenuOpen}>
        <DialogContent
          showClose={false}
          className="left-0 top-0 translate-x-0 translate-y-0 h-dvh w-[85vw] max-w-[320px] rounded-none p-0 border-r border-border overflow-hidden"
        >
          <div className="h-full flex flex-col overflow-y-auto" {...swipeDismissHandlers}>
            <div className="h-14 shrink-0 border-b border-border px-4 flex items-center justify-between">
              <Link href="/calendar" className="font-semibold text-foreground" onClick={() => setMobileMenuOpen(false)}>
                Fly Arrangement
              </Link>
              <Button type="button" variant="ghost" size="icon" onClick={() => setMobileMenuOpen(false)} aria-label="关闭菜单">
                <X className="h-5 w-5" />
              </Button>
            </div>
            <nav className="p-2 space-y-0.5 flex-1 min-h-0">
              {mainNavItems.map(({ href, label, icon: Icon }) => {
                const active = isRouteActive(pathname, href);
                return (
                  <Link
                    key={href}
                    href={href}
                    onClick={() => setMobileMenuOpen(false)}
                    className={cn(
                      "flex items-center gap-3 rounded-lg px-3 py-3 text-sm font-medium min-h-[44px] touch-manipulation active:opacity-90",
                      active
                        ? "bg-primary text-primary-foreground"
                        : "text-muted-foreground hover:bg-muted"
                    )}
                  >
                    <Icon className="h-5 w-5 shrink-0" />
                    {label}
                  </Link>
                );
              })}
            </nav>
            <div className="shrink-0 border-t border-border p-2 space-y-0.5">
              {user && (
                <Link
                  href="/settings/profile"
                  onClick={() => setMobileMenuOpen(false)}
                  className={cn(
                    "flex items-center gap-3 rounded-lg px-3 py-3 text-sm font-medium min-h-[44px] touch-manipulation",
                    isRouteActive(pathname, "/settings/profile")
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:bg-muted"
                  )}
                >
                  <Settings className="h-5 w-5 shrink-0" />
                  个人设置
                </Link>
              )}
              {user?.role === "admin" && (
                <>
                  <div className="px-2 pt-2 pb-1 [&_select]:min-h-[44px] [&_select]:touch-manipulation">
                  </div>
                  <Link
                    href="/settings/dashboard"
                    onClick={() => setMobileMenuOpen(false)}
                    className={cn(
                      "flex items-center gap-3 rounded-lg px-3 py-3 text-sm font-medium min-h-[44px] touch-manipulation",
                      isRouteActive(pathname, "/settings/dashboard")
                        ? "bg-primary text-primary-foreground"
                        : "text-muted-foreground hover:bg-muted"
                    )}
                  >
                    <LayoutGrid className="h-5 w-5 shrink-0" />
                    管理员
                  </Link>
                </>
              )}
              {user ? (
                <div className="flex items-center justify-between gap-2 px-3 py-3 min-h-[44px]">
                  <span className="truncate text-sm text-muted-foreground" title={user.display_name || user.username}>
                    {user.display_name || user.username}
                    {user.role === "admin" ? " (管理员)" : ""}
                  </span>
                  <Button type="button" variant="ghost" size="sm" onClick={logout} aria-label="退出" className="shrink-0 touch-manipulation min-h-[44px] min-w-[44px]">
                    <LogOut className="h-4 w-4" />
                  </Button>
                </div>
              ) : (
                <Link
                  href="/login"
                  onClick={() => setMobileMenuOpen(false)}
                  className="flex items-center gap-3 rounded-lg px-3 py-3 text-sm font-medium text-muted-foreground hover:bg-muted min-h-[44px] touch-manipulation"
                >
                  <LogIn className="h-5 w-5 shrink-0" />
                  登录
                </Link>
              )}
            </div>
          </div>
          <DialogTitle className="sr-only">菜单</DialogTitle>
        </DialogContent>
      </Dialog>
    </div>
  );
}
