"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";

export default function SettingsIndexPage() {
  const router = useRouter();
  const { user, loading } = useAuth();

  useEffect(() => {
    if (loading) return;
    if (!user) {
      router.replace("/login");
      return;
    }
    router.replace(user.role === "admin" ? "/settings/dashboard" : "/settings/profile");
  }, [loading, user, router]);

  return (
    <div className="flex items-center justify-center p-8 text-muted-foreground">
      <p>加载中…</p>
    </div>
  );
}
