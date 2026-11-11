"use client";

import { usePathname } from "next/navigation";
import { AuthGuard } from "@/components/AuthGuard";

const LOGIN_PATH = "/login";

/**
 * 根布局认证层：登录页仅渲染子级（无侧栏/壳子），其余路由走 AuthGuard（未登录不渲染主应用壳）。
 */
export function AuthLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isLoginPage = pathname === LOGIN_PATH;

  if (isLoginPage) {
    return <>{children}</>;
  }

  return <AuthGuard>{children}</AuthGuard>;
}
