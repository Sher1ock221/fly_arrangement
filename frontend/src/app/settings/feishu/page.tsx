"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/** 旧书签 /settings/feishu：重定向到个人设置，不发起任何飞书接口 */
export default function FeishuSettingsRedirectPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/settings/profile");
  }, [router]);
  return (
    <div className="flex h-full items-center justify-center p-6 text-sm text-muted-foreground">
      正在跳转到设置…
    </div>
  );
}
