"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { MessageCircle } from "lucide-react";
import { ChatWindow } from "@/components/chat/ChatWindow";
import { cn } from "@/lib/utils";
import { useMobile } from "@/hooks/use-mobile";

/** 右下角悬浮助手按钮：全站显示；桌面端打开 ChatWindow，移动端跳转 /ai-assistant */
export function ChatWidget() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const isMobile = useMobile();

  const handleClick = () => {
    if (isMobile) {
      router.push("/ai-assistant");
      return;
    }
    setOpen(true);
  };

  const handleFullscreen = () => {
    setOpen(false);
    router.push("/ai-assistant");
  };

  return (
    <>
      <button
        type="button"
        onClick={handleClick}
        aria-label="打开 AI 助手"
        className={cn(
          "fixed bottom-6 right-6 z-30 flex h-14 w-14 items-center justify-center rounded-full bg-[#1677ff] text-white shadow-lg transition-transform hover:scale-105 focus:outline-none focus:ring-2 focus:ring-[#1677ff] focus:ring-offset-2"
        )}
      >
        <MessageCircle className="h-6 w-6" />
      </button>
      <ChatWindow open={open} onClose={() => setOpen(false)} onFullscreen={handleFullscreen} />
    </>
  );
}
