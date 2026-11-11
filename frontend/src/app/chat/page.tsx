"use client";

import { useState, useEffect } from "react";
import { Menu } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { ConversationSidebar } from "@/components/chat/ConversationSidebar";
import { useChatContext } from "@/contexts/ChatContext";
import { projectsApi } from "@/lib/apiClient";
import { cn } from "@/lib/utils";

const SIDER_WIDTH = 280;
const MOBILE_BREAK = 768;

function useIsMobile() {
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${MOBILE_BREAK - 1}px)`);
    const handler = () => setIsMobile(mql.matches);
    handler();
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);
  return isMobile;
}

function useProjectName(projectId: number | undefined) {
  const [name, setName] = useState<string | null>(null);
  useEffect(() => {
    if (projectId == null) {
      setName(null);
      return;
    }
    let cancelled = false;
    projectsApi
      .get(projectId)
      .then((p) => {
        if (!cancelled) setName(p.name);
      })
      .catch(() => {
        if (!cancelled) setName(null);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);
  return name;
}

export default function ChatPage() {
  const {
    currentConversation,
    messages,
    sendMessage,
    cancelPendingChat,
    loading,
    messagesLoading,
    messagesError,
    refetchMessages,
    setConversationProjectId,
  } = useChatContext();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [bindProjectOpen, setBindProjectOpen] = useState(false);
  const isMobile = useIsMobile();
  const projectName = useProjectName(currentConversation?.projectId);
  const { data: projects = [] } = useQuery({
    queryKey: ["projects"],
    queryFn: () => projectsApi.list(),
    enabled: bindProjectOpen,
  });

  useEffect(() => {
    if (!isMobile) setSidebarOpen(false);
  }, [isMobile]);

  return (
    <div className="flex h-full min-h-0 w-full">
      {/* 侧栏：桌面常显，移动端用 Drawer */}
      <aside
        className={cn(
          "shrink-0 border-r border-border bg-card flex flex-col",
          "hidden md:flex",
          "md:w-[280px]"
        )}
        style={{ width: SIDER_WIDTH }}
      >
        <ConversationSidebar />
      </aside>

      {/* 移动端 Drawer 显示会话列表 */}
      {isMobile && (
        <>
          <div
            className={cn(
              "fixed inset-0 z-40 bg-black/40 transition-opacity",
              sidebarOpen ? "opacity-100" : "opacity-0 pointer-events-none"
            )}
            onClick={() => setSidebarOpen(false)}
            aria-hidden
          />
          <div
            className={cn(
              "fixed top-0 left-0 z-50 h-full w-[280px] max-w-[85vw] bg-card border-r border-border shadow-xl flex flex-col transition-transform duration-200 ease-out md:hidden",
              sidebarOpen ? "translate-x-0" : "-translate-x-full"
            )}
          >
            <ConversationSidebar onSelect={() => setSidebarOpen(false)} />
          </div>
        </>
      )}

      {/* 主内容区 */}
      <main className="flex flex-1 min-w-0 flex-col p-3 md:p-6">
        {/* 顶部：移动端菜单按钮 + 标题 + 当前项目 */}
        <div className="flex shrink-0 items-center gap-2 mb-4">
          {isMobile && (
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setSidebarOpen(true)}
              aria-label="打开会话列表"
            >
              <Menu className="h-5 w-5" />
            </Button>
          )}
          <h1 className="text-xl font-semibold text-foreground">AI 助手</h1>
          {projectName != null && (
            <span className="text-sm text-muted-foreground ml-2">
              当前项目：{projectName}
            </span>
          )}
          {currentConversation && (
            <Button
              variant="ghost"
              size="sm"
              className="text-muted-foreground ml-auto"
              onClick={() => setBindProjectOpen(true)}
            >
              {currentConversation.projectId != null ? "更换项目" : "绑定项目"}
            </Button>
          )}
        </div>

        {/* 绑定项目弹层 */}
        {bindProjectOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
            <div className="bg-background border border-border rounded-lg shadow-lg w-full max-w-md max-h-[70vh] overflow-hidden flex flex-col">
              <div className="p-3 border-b border-border font-medium">选择项目</div>
              <ul className="overflow-y-auto p-2">
                <li>
                  <button
                    type="button"
                    className="w-full text-left px-3 py-2 rounded hover:bg-muted text-sm"
                    onClick={() => {
                      if (currentConversation)
                        setConversationProjectId(currentConversation.id, undefined);
                      setBindProjectOpen(false);
                    }}
                  >
                    不绑定
                  </button>
                </li>
                {projects.map((p) => (
                  <li key={p.id}>
                    <button
                      type="button"
                      className="w-full text-left px-3 py-2 rounded hover:bg-muted text-sm"
                      onClick={() => {
                        if (currentConversation)
                          setConversationProjectId(currentConversation.id, p.id);
                        setBindProjectOpen(false);
                      }}
                    >
                      {p.name}
                      {p.project_no && (
                        <span className="text-muted-foreground ml-2">({p.project_no})</span>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
              <div className="p-2 border-t border-border">
                <Button variant="outline" size="sm" onClick={() => setBindProjectOpen(false)}>
                  关闭
                </Button>
              </div>
            </div>
          </div>
        )}

        <div className="flex-1 min-h-0 rounded-lg border border-border bg-background overflow-hidden flex flex-col">
          <ChatPanel
            mode="page"
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
      </main>
    </div>
  );
}
