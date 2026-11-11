"use client";

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

interface InfoField {
  label: string;
  value: string | null | undefined;
  span?: 2;
}

interface InfoGridProps {
  title: string;
  icon?: React.ReactNode;
  fields: InfoField[];
}

export default function InfoGrid({ title, icon, fields }: InfoGridProps) {
  return (
    <Card className="rounded-xl border border-border bg-card shadow-sm overflow-hidden">
      <CardHeader className="pb-3 border-b border-border/60">
        <CardTitle className="text-sm font-semibold flex items-center gap-2 text-foreground">
          {icon}
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-4 md:p-6">
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-4">
          {fields.map((field) => (
            <div
              key={field.label}
              className={field.span === 2 ? "sm:col-span-2" : ""}
            >
              <dt className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-1">
                {field.label}
              </dt>
              <dd
                className={
                  field.value
                    ? "text-sm text-foreground whitespace-pre-wrap break-words"
                    : "text-sm text-muted-foreground/60"
                }
              >
                {field.value || "未填写"}
              </dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}
