"use client";

/**
 * 全站 AI 对话状态：全屏页 /ai-assistant 与右下角悬浮窗共享同一 Context，
 * messages、conversations、当前会话、发送消息均由此提供，两边实时同步。
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { aiConfigApi, conversationApi, ApiRequestError, formatApiErrorUserMessage } from "@/lib/apiClient";
import { processExecutionResults, normalizeExecutionResults } from "@/lib/aiExecutionProcessor";
import type { ChatMessage } from "@/types/chat";
import type { AiChatDiagnostic, ChatApiResponse } from "@/types/ai";
import type { Conversation } from "@/types/conversation";
import { markAiReadyProvenBySuccessfulChat } from "@/lib/aiReadyCache";
import { queryKeys } from "@/lib/queryKeys";

const MESSAGES_KEY = "ai_messages";
const EMPTY_MESSAGES: ChatMessage[] = [];

function loadJson<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") return fallback;
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function saveJson(key: string, value: unknown) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // ignore
  }
}

function readStoredMessagesFor(conversationId: number): ChatMessage[] {
  const map = loadJson<Record<string, ChatMessage[]>>(MESSAGES_KEY, {});
  return map[String(conversationId)] ?? [];
}

interface ChatContextValue {
  conversations: Conversation[];
  currentConversation: Conversation | null;
  /** 当前会话 ID，与 currentConversation?.id 一致，便于消费 */
  currentConversationId: number | null;
  messages: ChatMessage[];
  /** 切换/首次打开会话时拉取消息；为 true 时不应展示其它会话内容 */
  messagesLoading: boolean;
  /** 当前会话消息加载失败 */
  messagesError: boolean;
  refetchMessages: () => void;
  loading: boolean;
  createConversation: () => void;
  /** 与 createConversation 相同，新建对话 */
  createNewConversation: () => void;
  selectConversation: (id: number) => void;
  /** 与 selectConversation 相同，切换会话（历史记录点击） */
  switchConversation: (id: number) => void;
  deleteConversation: (id: number) => void;
  renameConversation: (id: number, title: string) => void;
  sendMessage: (text: string) => Promise<void>;
  /** 中止当前进行中的 AI 聊天请求（仅影响前端 fetch，后端可能仍会跑完） */
  cancelPendingChat: () => void;
  setConversationProjectId: (conversationId: number, projectId: number | undefined) => void;
}

const ChatContext = createContext<ChatContextValue | null>(null);

let nextMessageId = 1;

function genMsgId() {
  return nextMessageId++;
}

export function ChatProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [currentConversation, setCurrentConversation] = useState<Conversation | null>(null);
  const [loading, setLoading] = useState(false);
  const [hydrated, setHydrated] = useState(false);
  const summarizedRef = useRef<Set<number>>(new Set());
  const chatAbortRef = useRef<AbortController | null>(null);
  const sendInFlightRef = useRef(false);

  const convId = currentConversation?.id ?? null;

  const messagesQuery = useQuery({
    queryKey: queryKeys.chatMessages(convId ?? 0),
    enabled: convId != null && convId > 0,
    staleTime: 0,
    queryFn: async ({ queryKey }) => {
      const id = queryKey[2] as number;
      try {
        const serverMessages = await conversationApi.getMessages(id);
        const postCache = queryClient.getQueryData<ChatMessage[]>(queryKeys.chatMessages(id)) ?? [];
        if (serverMessages && serverMessages.length > 0) {
          return serverMessages.map((m, i) => ({
            id: id * 10000 + i,
            conversationId: id,
            role: m.role === "system" ? "assistant" : (m.role as "user" | "assistant"),
            content: m.content,
            createdAt: m.created_at ?? new Date().toISOString(),
          })) as ChatMessage[];
        }
        const local = readStoredMessagesFor(id);
        if (postCache.length > local.length) {
          return postCache.map((m) => ({ ...m, conversationId: id }));
        }
        return local.map((m) => ({ ...m, conversationId: m.conversationId ?? id }));
      } catch {
        const postCache = queryClient.getQueryData<ChatMessage[]>(queryKeys.chatMessages(id)) ?? [];
        const local = readStoredMessagesFor(id);
        if (postCache.length > local.length) {
          return postCache.map((m) => ({ ...m, conversationId: id }));
        }
        return local.map((m) => ({ ...m, conversationId: m.conversationId ?? id }));
      }
    },
  });

  const messages = convId != null && convId > 0 ? (messagesQuery.data ?? EMPTY_MESSAGES) : EMPTY_MESSAGES;

  const messagesLoading =
    convId != null &&
    convId > 0 &&
    (messagesQuery.isPending || (messagesQuery.isFetching && messagesQuery.data === undefined));

  const messagesError = convId != null && convId > 0 && messagesQuery.isError;

  useEffect(() => {
    let cancelled = false;
    // 初始化时拉取历史会话列表（GET /api/v1/chat/conversations），填充 conversations
    conversationApi
      .list()
      .then((list) => {
        if (!cancelled) setConversations(list);
      })
      .catch(() => {
        if (!cancelled) setConversations([]);
      });
    const msgsMap = loadJson<Record<string, ChatMessage[]>>(MESSAGES_KEY, {});
    const allMsgs = Object.values(msgsMap).flat();
    nextMessageId = allMsgs.length ? Math.max(...allMsgs.map((m) => m.id)) + 1 : 1;
    setHydrated(true);
    return () => {
      cancelled = true;
    };
  }, []);

  const persistMessagesFor = useCallback((conversationId: number, msgs: ChatMessage[]) => {
    const map = loadJson<Record<string, ChatMessage[]>>(MESSAGES_KEY, {});
    map[String(conversationId)] = msgs;
    saveJson(MESSAGES_KEY, map);
  }, []);

  useEffect(() => {
    if (!hydrated || convId == null || convId <= 0) return;
    const data = messagesQuery.data;
    if (data === undefined) return;
    if (data.some((m) => m.conversationId !== convId)) return;
    persistMessagesFor(convId, data);
  }, [hydrated, convId, messagesQuery.data, persistMessagesFor]);

  const createConversation = useCallback(() => {
    conversationApi
      .create()
      .then((conv) => {
        setConversations((prev) => [conv, ...prev]);
        setCurrentConversation(conv);
        queryClient.setQueryData(queryKeys.chatMessages(conv.id), []);
        persistMessagesFor(conv.id, []);
      })
      .catch(() => {});
  }, [persistMessagesFor, queryClient]);

  /** 新建对话（仅清空当前会话与消息，不调后端）；发第一条消息时由 sendMessage 创建会话并加入历史列表 */
  const createNewConversation = useCallback(() => {
    setCurrentConversation(null);
  }, []);

  const selectConversation = useCallback(
    (id: number) => {
      const conv = conversations.find((c) => c.id === id);
      if (conv) setCurrentConversation(conv);
    },
    [conversations]
  );

  const refetchMessages = useCallback(() => {
    void messagesQuery.refetch();
  }, [messagesQuery]);

  const deleteConversation = useCallback(
    (id: number) => {
      conversationApi
        .delete(id)
        .then(() => {
          queryClient.removeQueries({ queryKey: queryKeys.chatMessages(id) });
          const next = conversations.filter((c) => c.id !== id);
          setConversations(next);
          if (currentConversation?.id === id) {
            const other = next[0];
            if (other) {
              setCurrentConversation(other);
            } else {
              setCurrentConversation(null);
            }
          }
          const map = loadJson<Record<string, ChatMessage[]>>(MESSAGES_KEY, {});
          delete map[String(id)];
          saveJson(MESSAGES_KEY, map);
        })
        .catch(() => {});
    },
    [conversations, currentConversation, queryClient]
  );

  const renameConversation = useCallback(
    (id: number, title: string) => {
      conversationApi
        .updateTitle(id, title)
        .then((updated) => {
          setConversations((prev) =>
            prev.map((c) => (c.id === id ? { ...c, title: updated.title, updatedAt: updated.updatedAt } : c))
          );
          if (currentConversation?.id === id) {
            setCurrentConversation((prev) => (prev ? { ...prev, title: updated.title, updatedAt: updated.updatedAt } : null));
          }
        })
        .catch(() => {});
    },
    [currentConversation]
  );

  const cancelPendingChat = useCallback(() => {
    chatAbortRef.current?.abort();
    chatAbortRef.current = null;
  }, []);

  const sendMessage = useCallback(
    async (text: string) => {
      if (sendInFlightRef.current) {
        toast.warning("上一条 AI 请求仍在处理中，请稍候或先取消。");
        return;
      }
      let conv = currentConversation;
      if (!conv) {
        try {
          const newConv = await conversationApi.create();
          setConversations((prev) => [newConv, ...prev]);
          setCurrentConversation(newConv);
          queryClient.setQueryData(queryKeys.chatMessages(newConv.id), []);
          persistMessagesFor(newConv.id, []);
          conv = newConv;
        } catch {
          return;
        }
      }

      const cacheKey = queryKeys.chatMessages(conv.id);
      const prev = queryClient.getQueryData<ChatMessage[]>(cacheKey) ?? [];
      const userMsg: ChatMessage = {
        id: genMsgId(),
        conversationId: conv.id,
        role: "user",
        content: text,
        createdAt: new Date().toISOString(),
      };
      const listForApi = [...prev, userMsg];
      queryClient.setQueryData(cacheKey, listForApi);
      sendInFlightRef.current = true;
      setLoading(true);
      const ac = new AbortController();
      chatAbortRef.current = ac;
      const API_CHAT_MESSAGE_CAP = 12;
      const messagesPayload =
        listForApi.length > API_CHAT_MESSAGE_CAP
          ? listForApi.slice(-API_CHAT_MESSAGE_CAP)
          : listForApi;
      try {
        const res = await aiConfigApi.chat(
          {
            messages: messagesPayload.map((m) => ({ role: m.role, content: m.content })),
          },
          { signal: ac.signal }
        );
        const content =
          (res as ChatApiResponse).content ??
          (typeof res.message === "object" && res.message && "content" in res.message
            ? String((res.message as { content?: string }).content ?? "")
            : "");
        const executionResults = normalizeExecutionResults(
          (res as ChatApiResponse).execution_results
        );
        const diag = (res as ChatApiResponse & { diagnostic?: AiChatDiagnostic }).diagnostic;
        const assistantMsg: ChatMessage = {
          id: genMsgId(),
          conversationId: conv.id,
          role: "assistant",
          content: content || "无回复",
          createdAt: new Date().toISOString(),
          ...(executionResults.length > 0 ? { execution_results: executionResults } : {}),
          // diagnostic.shortcut：ChatPanel / AIChatWindow 展示为「本地快速处理：…」
          ...(diag && typeof diag === "object" ? { ai_debug: diag } : {}),
        };
        const newList = [...listForApi, assistantMsg];
        queryClient.setQueryData(cacheKey, newList);
        const successClaimRegex = /(已创建成功|已安排成功|已添加到日历|日程已创建)/;
        if (executionResults.length === 0 && successClaimRegex.test(assistantMsg.content || "")) {
          console.warn("[chat] assistant claimed success without execution_results", {
            conversationId: conv.id,
            content: assistantMsg.content,
          });
        }
        markAiReadyProvenBySuccessfulChat(queryClient);
        processExecutionResults(executionResults, queryClient);
        persistMessagesFor(conv.id, newList);

        if (
          newList.length >= 2 &&
          conv.title === "新对话" &&
          !summarizedRef.current.has(conv.id)
        ) {
          summarizedRef.current.add(conv.id);
          conversationApi
            .summarizeTitle(
              conv.id,
              newList.map((m) => ({ role: m.role, content: m.content }))
            )
            .then(({ title }) => {
              setConversations((prev) =>
                prev.map((c) =>
                  c.id === conv.id ? { ...c, title, updatedAt: new Date().toISOString() } : c
                )
              );
              setCurrentConversation((prev) =>
                prev && prev.id === conv.id ? { ...prev, title, updatedAt: new Date().toISOString() } : prev
              );
            })
            .catch(() => {
              summarizedRef.current.delete(conv.id);
            });
        }
      } catch (e) {
        if (e instanceof ApiRequestError && e.status === 499) {
          const cancelled: ChatMessage = {
            id: genMsgId(),
            conversationId: conv.id,
            role: "assistant",
            content: "已取消本次请求。",
            createdAt: new Date().toISOString(),
          };
          const cancelledList = [...listForApi, cancelled];
          queryClient.setQueryData(cacheKey, cancelledList);
          persistMessagesFor(conv.id, cancelledList);
          return;
        }
        let errMsg =
          e instanceof ApiRequestError
            ? formatApiErrorUserMessage(e.responseText)
            : e instanceof Error
              ? e.message
              : String(e);
        let partialAppend = "";
        if (e instanceof ApiRequestError) {
          try {
            const parsed = JSON.parse(e.responseText) as {
              detail?:
                | string
                | {
                    partial_results?: Array<{ tool?: string; success?: boolean; error?: string }>;
                  };
            };
            const d = parsed?.detail;
            if (d && typeof d === "object" && Array.isArray(d.partial_results) && d.partial_results.length) {
              const lines = d.partial_results.map((r) => {
                const t = typeof r.tool === "string" ? r.tool : "?";
                const ok = r.success === true ? "成功" : "失败";
                const er = typeof r.error === "string" && r.error ? `：${r.error}` : "";
                return `- ${t}：${ok}${er}`;
              });
              partialAppend = `\n\n已完成的步骤：\n${lines.join("\n")}`;
            }
          } catch {
            // ignore
          }
        }
        if (!(e instanceof ApiRequestError)) {
          try {
            const parsed = JSON.parse(errMsg) as { detail?: string };
            if (parsed?.detail && typeof parsed.detail === "string") errMsg = parsed.detail;
          } catch {
            // ignore
          }
        }
        const errAssistant: ChatMessage = {
          id: genMsgId(),
          conversationId: conv.id,
          role: "assistant",
          content: `错误：${errMsg}${partialAppend}`,
          createdAt: new Date().toISOString(),
        };
        const failedList = [...listForApi, errAssistant];
        queryClient.setQueryData(cacheKey, failedList);
        persistMessagesFor(conv.id, failedList);
        if (e instanceof ApiRequestError && e.status === 409) {
          toast.warning(errMsg);
        } else if (/正在启动|正在预热|请.*秒后重试/.test(errMsg)) {
          toast.warning(errMsg);
        } else {
          toast.error(errMsg);
        }
      } finally {
        chatAbortRef.current = null;
        sendInFlightRef.current = false;
        setLoading(false);
      }
    },
    [currentConversation, persistMessagesFor, queryClient]
  );

  const setConversationProjectId = useCallback(
    (conversationId: number, projectId: number | undefined) => {
      setConversations((prev) =>
        prev.map((c) =>
          c.id === conversationId ? { ...c, projectId, updatedAt: new Date().toISOString() } : c
        )
      );
      if (currentConversation?.id === conversationId) {
        setCurrentConversation((prev) =>
          prev ? { ...prev, projectId } : null
        );
      }
    },
    [currentConversation]
  );

  const value = useMemo<ChatContextValue>(
    () => ({
      conversations,
      currentConversation,
      currentConversationId: currentConversation?.id ?? null,
      messages,
      messagesLoading,
      messagesError,
      refetchMessages,
      loading,
      createConversation,
      createNewConversation,
      selectConversation,
      switchConversation: selectConversation,
      deleteConversation,
      renameConversation,
      sendMessage,
      cancelPendingChat,
      setConversationProjectId,
    }),
    [
      conversations,
      currentConversation,
      messages,
      messagesLoading,
      messagesError,
      refetchMessages,
      loading,
      createConversation,
      createNewConversation,
      selectConversation,
      deleteConversation,
      renameConversation,
      sendMessage,
      cancelPendingChat,
      setConversationProjectId,
    ]
  );

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}

export function useChatContext() {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error("useChatContext must be used within ChatProvider");
  return ctx;
}
