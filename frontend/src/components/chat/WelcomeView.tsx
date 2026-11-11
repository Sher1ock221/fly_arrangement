"use client";

import { useState } from "react";
import { Bot, Send, Loader2, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const QUICK_PROMPTS = [
  "帮我创建营销项目",
  "分析本周进度",
  "列出所有待办事项",
  "总结客户反馈",
];

export interface WelcomeViewProps {
  onSend: (text: string) => Promise<void>;
  loading: boolean;
}

export function WelcomeView({ onSend, loading }: WelcomeViewProps) {
  const [inputValue, setInputValue] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const text = inputValue.trim();
    if (!text || loading) return;
    setInputValue("");
    await onSend(text);
  };

  const handleQuickCard = (text: string) => {
    if (loading) return;
    onSend(text);
  };

  return (
    <div className="flex h-full flex-col min-h-0">
      <div className="flex-1 min-h-0 overflow-y-auto px-4 py-8 md:px-6 md:py-10">
        <div className="mx-auto flex h-full w-full max-w-5xl flex-col items-center justify-center text-center">
          <div className="rounded-2xl bg-primary/10 p-4 mb-6">
            <Bot className="h-14 w-14 text-primary" strokeWidth={1.5} />
          </div>
          <h1 className="text-2xl font-semibold text-foreground mb-2">AI 助手</h1>
          <p className="text-muted-foreground text-sm mb-10">
            你好，我是一名企业项目管理助手，主要可以帮你做这些事。选一个快捷指令开始，或直接输入你的需求。
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 w-full max-w-3xl">
            {QUICK_PROMPTS.map((label) => (
              <button
                key={label}
                type="button"
                onClick={() => handleQuickCard(label)}
                disabled={loading}
                className={cn(
                  "flex items-center gap-3 rounded-xl border border-border bg-card px-4 py-3.5 text-left text-sm font-medium",
                  "hover:bg-accent hover:border-accent transition-colors",
                  "disabled:opacity-50 disabled:pointer-events-none"
                )}
              >
                <Sparkles className="h-4 w-4 shrink-0 text-primary" />
                <span className="truncate">{label}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
      <form
        onSubmit={handleSubmit}
        className="border-t border-border shrink-0 bg-background px-3 py-3 md:px-6 md:py-4"
      >
        <div className="mx-auto flex w-full max-w-6xl gap-2">
          <Input
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="输入消息或选择上方快捷指令..."
            disabled={loading}
            className="flex-1"
          />
          <Button type="submit" size="icon" className="h-10 w-10" disabled={loading || !inputValue.trim()}>
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
            <span className="sr-only">发送</span>
          </Button>
        </div>
      </form>
    </div>
  );
}
