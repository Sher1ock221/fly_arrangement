"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { mainNavItems, isRouteActive } from "@/components/navigation/nav-items";
import { Settings, LogIn, LogOut, LayoutGrid } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";

function NavLink({
  href,
  label,
  icon: Icon,
  pathname,
  compact = false,
}: {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  pathname: string;
  compact?: boolean;
}) {
  const isActive = isRouteActive(pathname, href);
  return (
    <Link
      href={href}
      className={cn(
        "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
        compact && "flex-col gap-1 py-2 px-2 min-w-0 flex-1 justify-center",
        isActive
          ? "bg-primary text-primary-foreground"
          : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
      )}
      aria-current={isActive ? "page" : undefined}
    >
      <Icon className={cn("shrink-0", compact ? "h-5 w-5" : "h-5 w-5")} />
      {compact ? (
        <span className="text-[10px] truncate w-full text-center">{label}</span>
      ) : (
        label
      )}
    </Link>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const { user, logout } = useAuth();

  return (
    <aside className="hidden md:flex h-full w-52 shrink-0 flex-col border-r border-border bg-card lg:w-56">
      <div className="flex h-14 items-center border-b border-border px-4">
        <Link href="/calendar" className="font-semibold text-foreground">
          Fly Arrangement
        </Link>
      </div>
      <nav className="flex-1 space-y-0.5 p-2">
        {mainNavItems.map(({ href, label, icon }) => (
          <NavLink
            key={href}
            href={href}
            label={label}
            icon={icon}
            pathname={pathname}
          />
        ))}
      </nav>
      <div className="border-t border-border p-2 space-y-0.5">
        {user && (
          <NavLink href="/settings/profile" label="个人设置" icon={Settings} pathname={pathname} />
        )}
        {user?.role === "admin" && (
          <>
            <NavLink href="/settings/dashboard" label="管理员" icon={LayoutGrid} pathname={pathname} />
          </>
        )}
        {user ? (
          <div className="flex items-center justify-between gap-2 px-3 py-2 text-sm">
            <span className="truncate text-muted-foreground" title={user.display_name || user.username}>
              {user.display_name || user.username}
              {user.role === "admin" ? " (管理员)" : ""}
            </span>
            <Button type="button" variant="ghost" size="sm" onClick={logout} aria-label="退出">
              <LogOut className="h-4 w-4" />
            </Button>
          </div>
        ) : (
          <Link
            href="/login"
            className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-accent hover:text-accent-foreground"
          >
            <LogIn className="h-5 w-5 shrink-0" />
            登录
          </Link>
        )}
      </div>
    </aside>
  );
}
