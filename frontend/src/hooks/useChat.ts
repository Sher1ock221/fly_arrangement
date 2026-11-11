"use client";

import { useState, useCallback, useEffect } from "react";
import { aiConfigApi } from "@/lib/apiClient";
import type { ChatMessage } from "@/types/chat";

const STORAGE_KEY = "ai_chat_history";

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as ChatMessage[];
        if (Array.isArray(parsed)) setMessages(parsed);
      }
    } catch {
      // ignore
    }
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated || messages.length === 0) return;
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
    } catch {
      // ignore
    }
  }, [hydrated, messages]);

  const send = useCallback(async (text: string) => {
    const userMsg: ChatMessage = {
      id: Date.now(),
      conversationId: 0,
      role: "user",
      content: text,
      createdAt: new Date().toISOString(),
    };
    const listForApi = [...messages, userMsg];
    setMessages(listForApi);
    setLoading(true);
    try {
      const res = await aiConfigApi.chat({
        messages: listForApi.map((m) => ({ role: m.role, content: m.content })),
      });
      const content =
        (res as { content?: string }).content ??
        (typeof res.message === "object" && res.message && "content" in res.message
          ? String((res.message as { content?: string }).content ?? "")
          : "");
      const assistantMsg: ChatMessage = {
        id: Date.now() + 1,
        conversationId: 0,
        role: "assistant",
        content: content || "无回复",
        createdAt: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : String(e);
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 1,
          conversationId: 0,
          role: "assistant",
          content: `错误：${errMsg}`,
          createdAt: new Date().toISOString(),
        },
      ]);
    } finally {
      setLoading(false);
    }
  }, [messages]);

  return { messages, send, loading, hydrated };
}
