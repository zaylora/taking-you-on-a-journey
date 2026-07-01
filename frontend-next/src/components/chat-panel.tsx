"use client";

import { Loader2, Send, Square, Wrench } from "lucide-react";
import { FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { ChatMessage } from "@/lib/types";
import { cn } from "@/lib/utils";

interface ChatPanelProps {
  messages: ChatMessage[];
  loading: boolean;
  onSubmit: (message: string) => void;
  onStop: () => void;
}

export function ChatPanel({
  messages,
  loading,
  onSubmit,
  onStop,
}: ChatPanelProps) {
  const [input, setInput] = useState("");

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    const message = input.trim();
    if (!message || loading) return;
    setInput("");
    onSubmit(message);
  };

  return (
    <section className="flex h-full min-w-0 flex-1 flex-col bg-zinc-950 text-zinc-50">
      <header className="flex h-14 items-center justify-between border-b border-white/10 px-5">
        <div>
          <h1 className="text-sm font-semibold">旅行规划助手</h1>
          <p className="text-xs text-zinc-400">对接 FastAPI + LangGraph 后端</p>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-6">
        <div className="mx-auto flex max-w-3xl flex-col gap-5">
          {messages.length === 0 ? (
            <div className="rounded-md border border-white/10 bg-white/[0.03] p-5 text-sm text-zinc-300">
              输入目的地、天数、预算和偏好，我会生成路线并在右侧展开地图工作区。
            </div>
          ) : (
            messages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))
          )}
          {loading ? (
            <div className="flex items-center gap-2 text-sm text-zinc-400">
              <Loader2 className="h-4 w-4 animate-spin" />
              正在生成
            </div>
          ) : null}
        </div>
      </div>

      <form
        onSubmit={handleSubmit}
        className="border-t border-white/10 bg-zinc-950/95 px-4 py-4"
      >
        <div className="mx-auto flex max-w-3xl items-end gap-2">
          <Textarea
            aria-label="发送消息"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="例如：帮我规划广州三天两晚，喜欢岭南建筑和本地美食"
            className="min-h-14 border-white/10 bg-zinc-900 text-zinc-50 placeholder:text-zinc-500 focus:border-zinc-500"
          />
          {loading ? (
            <Button type="button" size="icon" variant="outline" onClick={onStop}>
              <Square className="h-4 w-4" />
            </Button>
          ) : (
            <Button type="submit" size="icon" aria-label="发送">
              <Send className="h-4 w-4" />
            </Button>
          )}
        </div>
      </form>
    </section>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  return (
    <article
      className={cn(
        "flex",
        message.role === "user" ? "justify-end" : "justify-start",
      )}
    >
      <div
        className={cn(
          "max-w-[82%] rounded-md px-4 py-3 text-sm leading-6",
          message.role === "user"
            ? "bg-white text-zinc-950"
            : "bg-zinc-900 text-zinc-100",
          message.kind === "error" && "border border-red-400/40 text-red-100",
        )}
      >
        {message.parts.map((part, index) => {
          if (part.type === "tool") {
            return (
              <div
                key={`${part.tool}-${index}`}
                className="mb-2 inline-flex items-center gap-2 rounded-md border border-white/10 bg-black/20 px-2 py-1 text-xs text-zinc-300"
              >
                <Wrench className="h-3.5 w-3.5" />
                <span>{part.label}</span>
                <span className="text-zinc-500">
                  {part.status === "running" ? "进行中" : "完成"}
                </span>
              </div>
            );
          }
          return (
            <p key={index} className="whitespace-pre-wrap">
              {part.text}
            </p>
          );
        })}
      </div>
    </article>
  );
}

