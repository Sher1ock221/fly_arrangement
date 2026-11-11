"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { X, Maximize2, PanelLeft, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { ConversationSidebar } from "@/components/chat/ConversationSidebar";
import { useChatContext } from "@/contexts/ChatContext";
import { cn } from "@/lib/utils";

interface ChatWindowProps {
  open: boolean;
  onClose: () => void;
  /** 点击全屏图标时跳转到 /ai-assistant */
  onFullscreen?: () => void;
}

/** 桌面端悬浮聊天窗口：与全屏 AI 页共享 ChatContext，messages / sendMessage 来自同一状态，两边同步更新 */
export function ChatWindow({ open, onClose, onFullscreen }: ChatWindowProps) {
  const {
    currentConversation,
    messages,
    sendMessage,
    cancelPendingChat,
    loading,
    messagesLoading,
    messagesError,
    refetchMessages,
    createNewConversation,
  } = useChatContext();
  const router = useRouter();
  const [historyOpen, setHistoryOpen] = useState(false);

  useEffect(() => {
    if (!open) setHistoryOpen(false);
  }, [open]);

  const handleFullscreen = () => {
    onClose();
    (onFullscreen ?? (() => router.push("/ai-assistant")))();
  };

  return (
    <>
      {/* 遮罩 */}
      <div
        role="presentation"
        className={cn(
          "fixed inset-0 z-40 bg-black/40 transition-opacity",
          open ? "opacity-100" : "opacity-0 pointer-events-none"
        )}
        onClick={onClose}
        aria-hidden
      />
      {/* 抽屉面板 */}
      <div
        className={cn(
          "fixed z-50 transition-transform duration-200 ease-out",
          "right-0 top-0 bottom-0 w-full sm:right-4 sm:top-4 sm:bottom-4 sm:w-[430px] md:w-[440px]",
          open ? "translate-x-0" : "translate-x-full"
        )}
      >
        <aside
          className={cn(
            "absolute right-full top-0 h-full w-[288px] border border-border border-r-0 bg-card shadow-lg transition-transform duration-200 ease-out",
            "rounded-l-2xl overflow-hidden",
            historyOpen ? "translate-x-0" : "translate-x-full pointer-events-none"
          )}
        >
          <ConversationSidebar
            disableFixedWidth
            className="!w-full border-r-0"
            newConversationLabel="新建对话"
            prominentNewConversation
            onSelect={() => setHistoryOpen(false)}
          />
        </aside>

        <div className="relative flex h-full min-h-0 w-full flex-col overflow-hidden border border-border bg-background shadow-xl sm:rounded-2xl">
          <div className="flex items-center justify-between shrink-0 border-b border-border px-4 py-3">
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setHistoryOpen((v) => !v)}
                aria-label="历史会话"
                title="历史会话"
              >
                <PanelLeft className="h-4 w-4" />
              </Button>
              <h2 className="text-base font-semibold text-foreground">AI 助手</h2>
            </div>
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="icon"
                onClick={() => {
                  createNewConversation();
                  setHistoryOpen(false);
                }}
                aria-label="新建对话"
                title="新建对话"
              >
                <Plus className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                onClick={handleFullscreen}
                aria-label="全屏打开"
                title="全屏打开"
              >
                <Maximize2 className="h-4 w-4" />
              </Button>
              <Button variant="ghost" size="icon" onClick={onClose} aria-label="关闭">
                <X className="h-4 w-4" />
              </Button>
            </div>
          </div>

          {/* 右侧工具条：提供快速新建入口 */}
          <div className="absolute right-2 top-20 z-10">
            <Button
              variant="outline"
              size="icon"
              className="h-9 w-9 bg-background/90"
              onClick={() => {
                createNewConversation();
                setHistoryOpen(false);
              }}
              aria-label="新建对话"
              title="新建对话"
            >
              <Plus className="h-4 w-4" />
            </Button>
          </div>

          <div className="flex-1 min-h-0">
            <ChatPanel
              mode="widget"
              messages={messages}
              onSend={sendMessage}
              onCancelPending={cancelPendingChat}
              loading={loading}
              messagesLoading={!!currentConversation && messagesLoading}
              messagesError={!!currentConversation && messagesError}
              onRetryMessages={refetchMessages}
              emptyPlaceholder={currentConversation ? "no-messages" : "welcome"}
            />
          </div>
        </div>
      </div>
    </>
  );
}
