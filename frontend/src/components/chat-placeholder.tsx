"use client";

import { MessageCircle } from "lucide-react";
import { cn } from "@/lib/utils";

/** 右侧预留的悬浮聊天窗口占位，后续接入 AI 助手 */
export function ChatPlaceholder() {
  return (
    <div
      className={cn(
        "fixed right-6 bottom-6 z-40 flex h-14 w-14 cursor-pointer items-center justify-center rounded-full bg-primary text-primary-foreground shadow-lg transition hover:scale-105",
        "focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
      )}
      title="AI 助手（即将开放）"
      aria-label="打开 AI 助手"
    >
      <MessageCircle className="h-6 w-6" />
    </div>
  );
}
