"use client";

import Link from "next/link";
import { AlertCircle } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";

interface DetailErrorProps {
  backHref: string;
  backLabel: string;
  message?: string;
  action?: ReactNode;
}

export default function DetailError({
  backHref,
  backLabel,
  message,
  action,
}: DetailErrorProps) {
  return (
    <div className="min-h-screen bg-background flex items-center justify-center">
      <div className="text-center space-y-4">
        <AlertCircle className="h-12 w-12 text-destructive mx-auto" />
        <p className="text-sm text-muted-foreground">
          {message || "加载失败，请稍后重试"}
        </p>
        {action ?? (
          <Button variant="outline" asChild>
            <Link href={backHref}>{backLabel || "返回"}</Link>
          </Button>
        )}
      </div>
    </div>
  );
}
