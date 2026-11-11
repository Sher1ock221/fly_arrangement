"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/** 旧书签 /settings/feishu-identities：重定向到个人设置 */
export default function FeishuIdentitiesRedirectPage() {
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
