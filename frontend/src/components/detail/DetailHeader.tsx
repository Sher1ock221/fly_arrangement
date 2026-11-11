"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";

interface DetailHeaderProps {
  backHref: string;
  backLabel: string;
  title: string;
  subtitle?: string;
  accessRole?: "owner" | "collaborator";
  actions?: React.ReactNode;
}

export default function DetailHeader({
  backHref,
  backLabel,
  title,
  subtitle,
  accessRole,
  actions,
}: DetailHeaderProps) {
  return (
    <div className="border-b border-border bg-card px-4 md:px-6 py-3 md:py-4">
      <div className="flex items-center flex-wrap gap-2">
        <Button variant="ghost" size="icon" asChild className="shrink-0">
          <Link href={backHref} aria-label={backLabel}>
            <ArrowLeft className="h-5 w-5" />
          </Link>
        </Button>

        <div className="flex items-center gap-2 min-w-0">
          <h1 className="text-lg md:text-xl font-semibold truncate">{title}</h1>
          {subtitle && (
            <span className="text-sm text-muted-foreground truncate hidden sm:inline">
              {subtitle}
            </span>
          )}
          {accessRole === "owner" && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 font-medium whitespace-nowrap">
              我负责
            </span>
          )}
          {accessRole === "collaborator" && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 font-medium whitespace-nowrap">
              协作中
            </span>
          )}
        </div>

        <div className="flex-1" />

        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}
