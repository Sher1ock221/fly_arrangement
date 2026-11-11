"use client";

import { useState } from "react";
import { Menu, X } from "lucide-react";
import { ConversationSidebar } from "@/components/chat/ConversationSidebar";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { useMobile } from "@/hooks/use-mobile";
import { useSwipeDismiss } from "@/hooks/use-swipe-dismiss";

const SIDEBAR_WIDTH = 288;

export default function AIAssistantLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const isMobile = useMobile();
  const [openConversations, setOpenConversations] = useState(false);
  const swipeDismissHandlers = useSwipeDismiss({
    onDismiss: () => setOpenConversations(false),
  });

  if (isMobile) {
    return (
      <div className="flex h-full w-full min-h-0 flex-col">
        <div className="h-12 shrink-0 border-b border-border bg-card px-3 flex items-center justify-between">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="gap-2"
            onClick={() => setOpenConversations(true)}
          >
            <Menu className="h-4 w-4" />
            会话
          </Button>
          <span className="text-sm font-medium">AI 助手</span>
          <div className="w-14" />
        </div>
        <main className="flex-1 min-h-0 flex flex-col bg-background">
          {children}
        </main>
        <Dialog open={openConversations} onOpenChange={setOpenConversations}>
          <DialogContent
            showClose={false}
            className="left-0 top-0 translate-x-0 translate-y-0 h-dvh w-[86vw] max-w-[320px] rounded-none p-0 border-r border-border"
          >
            <div className="h-full flex flex-col" {...swipeDismissHandlers}>
              <div className="h-12 border-b border-border px-3 flex items-center justify-between">
                <span className="text-sm font-medium">对话列表</span>
                <Button type="button" variant="ghost" size="icon" onClick={() => setOpenConversations(false)}>
                  <X className="h-4 w-4" />
                </Button>
              </div>
              <ConversationSidebar
                className="!w-full border-r-0"
                disableFixedWidth
                newConversationLabel="新建对话"
                prominentNewConversation
                onSelect={() => setOpenConversations(false)}
              />
            </div>
            <DialogTitle className="sr-only">会话列表</DialogTitle>
          </DialogContent>
        </Dialog>
      </div>
    );
  }

  return (
    <div className="flex h-full w-full min-h-0">
      {/* 左侧二级侧边栏：渲染 ChatContext.conversations，点击项调用 switchConversation(id) */}
      <aside
        className="shrink-0 flex flex-col border-r border-border bg-card"
        style={{ width: SIDEBAR_WIDTH }}
      >
        <ConversationSidebar newConversationLabel="新建对话" prominentNewConversation disableFixedWidth className="!w-full" />
      </aside>
      {/* 右侧主对话区：占据剩余空间 */}
      <main className="flex-1 min-w-0 flex flex-col bg-background">
        {children}
      </main>
    </div>
  );
}
