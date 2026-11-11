"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";

interface DetailSkeletonProps {
  backHref: string;
  backLabel: string;
}

export default function DetailSkeleton({
  backHref,
  backLabel,
}: DetailSkeletonProps) {
  return (
    <div className="min-h-screen bg-background">
      <div className="border-b border-border bg-card px-4 md:px-6 py-3 md:py-4">
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="icon" asChild className="shrink-0">
            <Link href={backHref} aria-label={backLabel}>
              <ArrowLeft className="h-5 w-5" />
            </Link>
          </Button>
          <div className="h-6 w-48 rounded bg-muted animate-pulse" />
        </div>
      </div>

      <div className="max-w-4xl mx-auto p-4 md:p-6 space-y-4">
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            className="rounded-xl border border-border h-32 animate-pulse bg-muted/40"
          />
        ))}
      </div>
    </div>
  );
}
