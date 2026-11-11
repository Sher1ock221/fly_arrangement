"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * 根路径重定向到日历工作台（实际首页）。
 * 登录后默认进入 /calendar，此处统一“首页”即日历。
 */
export default function HomePage() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/calendar");
  }, [router]);
  return (
    <div className="flex min-h-screen items-center justify-center">
      <p className="text-sm text-muted-foreground">正在跳转到日历…</p>
    </div>
  );
}
