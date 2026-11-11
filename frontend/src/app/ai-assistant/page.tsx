"use client";

import { useRef, useEffect } from "react";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { WelcomeView } from "@/components/chat/WelcomeView";
import { useChatContext } from "@/contexts/ChatContext";

/** 全屏 AI 助手页：与悬浮窗共享 ChatContext；新建对话仅保留左侧栏顶部按钮 */
export default function AIAssistantPage() {
  const {
    currentConversation,
    messages,
    messagesLoading,
    messagesError,
    refetchMessages,
    sendMessage,
    cancelPendingChat,
    loading,
  } = useChatContext();
  const chatInputRef = useRef<HTMLInputElement>(null);
  const currentConversationId = currentConversation?.id;

  useEffect(() => {
    if (currentConversationId != null && messages.length === 0) {
      chatInputRef.current?.focus();
    }
  }, [currentConversationId, messages.length]);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      {/* 主对话区：直接读取 Context 的 messages，发送调用 sendMessage */}
      {!currentConversation ? (
        <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
          <WelcomeView onSend={sendMessage} loading={loading} />
        </div>
      ) : (
        <div className="flex-1 min-h-0 overflow-hidden">
          <ChatPanel
            mode="page"
            messages={messages}
            onSend={sendMessage}
            onCancelPending={cancelPendingChat}
            loading={loading}
            messagesLoading={messagesLoading}
            messagesError={messagesError}
            onRetryMessages={refetchMessages}
            emptyPlaceholder="no-messages"
            inputRef={chatInputRef}
          />
        </div>
      )}
    </div>
  );
}
