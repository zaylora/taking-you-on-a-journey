"use client";

import {
  Copy,
  CornerDownLeft,
  Menu,
  Paperclip,
  Plus,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
} from "lucide-react";
import { type ReactNode, useState } from "react";

import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import {
  Message,
  MessageAction,
  MessageActions,
  MessageContent,
  MessageResponse,
} from "@/components/ai-elements/message";
import {
  PromptInput,
  PromptInputBody,
  PromptInputButton,
  PromptInputFooter,
  type PromptInputMessage,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
} from "@/components/ai-elements/prompt-input";
import {
  Reasoning,
  ReasoningContent,
  ReasoningTrigger,
} from "@/components/ai-elements/reasoning";
import { Shimmer } from "@/components/ai-elements/shimmer";
import {
  Tool,
  ToolContent,
  ToolHeader,
  ToolOutput,
} from "@/components/ai-elements/tool";
import { Button } from "@/components/ui/button";
import type { ChatMessage, ChatPart } from "@/lib/types";
import { cn } from "@/lib/utils";

interface ChatPanelProps {
  messages: ChatMessage[];
  activeNodeLabel?: string | null;
  loading: boolean;
  onSubmit: (message: string) => void;
  onStop: () => void;
}

export function ChatPanel({
  messages,
  activeNodeLabel = null,
  loading,
  onSubmit,
  onStop,
}: ChatPanelProps) {
  const [input, setInput] = useState("");
  const showThinking =
    loading &&
    !!activeNodeLabel &&
    !lastAssistantIsStreamingText(messages) &&
    !lastAssistantHasRunningTool(messages);

  const handleSubmit = (message: PromptInputMessage) => {
    const text = message.text.trim();
    if (!text || loading) return;
    setInput("");
    onSubmit(text);
  };

  return (
    <section className="dark flex h-full min-w-0 flex-1 flex-col bg-background text-foreground">
      <header className="flex h-14 shrink-0 items-center justify-between border-b border-border px-3">
        <div className="flex items-center gap-2">
          <ToolbarIcon label="切换侧栏">
            <Menu className="size-4" />
          </ToolbarIcon>
          <ToolbarIcon label="新建会话">
            <Plus className="size-4" />
          </ToolbarIcon>
          <Button
            type="button"
            variant="outline"
            className="h-9 gap-2 bg-background px-3 text-sm"
            aria-label="选择聊天模型"
          >
            <span>旅行规划模型</span>
            <CornerDownLeft className="size-3.5 rotate-45 text-muted-foreground" />
          </Button>
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="secondary"
            className="hidden h-9 px-3 text-sm sm:inline-flex"
          >
            导出行程
          </Button>
          <Button type="button" variant="outline" className="h-9 px-3 text-sm">
            登录
          </Button>
        </div>
      </header>

      <div className="relative min-h-0 flex-1">
        <Conversation
          data-testid="ai-elements-conversation"
          className="h-full"
        >
          <ConversationContent className="mx-auto w-full max-w-3xl gap-8 px-4 pb-6 pt-8">
            {messages.length === 0 ? (
              <ConversationEmptyState
                icon={<Sparkles className="size-10" />}
                title="旅行规划助手"
                description="输入目的地、天数、预算和偏好，我会生成路线并在右侧展开地图工作区。"
                className="min-h-[42vh] text-muted-foreground"
              />
            ) : (
              messages.map((message, index) => (
                <ChatMessageItem
                  key={message.id}
                  loading={loading}
                  message={message}
                  isLatestAssistant={
                    message.role === "assistant" &&
                    index === messages.length - 1
                  }
                />
              ))
            )}
            {showThinking ? <ThinkingStatus label={activeNodeLabel} /> : null}
          </ConversationContent>
          <ConversationScrollButton />
        </Conversation>
      </div>

      <div className="shrink-0 px-4 pb-5">
        <PromptInput
          data-testid="ai-elements-prompt-input"
          onSubmit={handleSubmit}
          className="mx-auto max-w-3xl"
        >
          <PromptInputBody>
            <PromptInputTextarea
              aria-label="发送消息"
              value={input}
              onChange={(event) => setInput(event.currentTarget.value)}
              placeholder="例如：帮我规划广州三天两晚，喜欢岭南建筑和本地美食"
              className="min-h-20 text-base"
            />
          </PromptInputBody>
          <PromptInputFooter>
            <PromptInputTools>
              <PromptInputButton
                type="button"
                aria-label="添加附件"
                tooltip="添加附件"
              >
                <Paperclip className="size-4" />
              </PromptInputButton>
            </PromptInputTools>
            <PromptInputSubmit
              aria-label={loading ? "停止生成" : "发送"}
              disabled={!loading && !input.trim()}
              onStop={onStop}
              status={loading ? "streaming" : "ready"}
              className="rounded-full"
            />
          </PromptInputFooter>
        </PromptInput>
      </div>
    </section>
  );
}

function ToolbarIcon({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <Button
      type="button"
      aria-label={label}
      title={label}
      variant="outline"
      size="icon"
      className="h-9 w-9 bg-background"
    >
      {children}
    </Button>
  );
}

function ThinkingStatus({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground">
      <Shimmer as="span" duration={1.25}>
        {label}
      </Shimmer>
    </div>
  );
}

function lastAssistantIsStreamingText(messages: ChatMessage[]) {
  const last = messages[messages.length - 1];
  if (last?.role !== "assistant") return false;
  const lastPart = last.parts[last.parts.length - 1];
  return lastPart?.type === "text" && lastPart.text.length > 0;
}

function lastAssistantHasRunningTool(messages: ChatMessage[]) {
  const last = messages[messages.length - 1];
  if (last?.role !== "assistant") return false;
  return last.parts.some(
    (part) => part.type === "tool" && part.status === "running",
  );
}

function ChatMessageItem({
  message,
  loading,
  isLatestAssistant,
}: {
  message: ChatMessage;
  loading: boolean;
  isLatestAssistant: boolean;
}) {
  const isUser = message.role === "user";
  const lastAssistantTextIndex = isUser
    ? -1
    : findLastAssistantTextIndex(message.parts);
  const showActions =
    !isUser && message.kind !== "error" && !(loading && isLatestAssistant);

  return (
    <Message
      data-testid="ai-elements-message"
      from={message.role}
      className={cn(
        isUser ? "max-w-[80%]" : "max-w-full",
        message.kind === "error" && "text-destructive",
      )}
    >
      <MessageContent
        className={cn(
          isUser && "rounded-xl bg-primary px-4 py-2.5 text-primary-foreground",
          message.kind === "error" &&
            "rounded-md border border-destructive/40 bg-destructive/10 px-4 py-3",
        )}
      >
        {message.parts.map((part, index) => (
          <MessagePart
            key={`${part.type}-${index}`}
            part={part}
            isUser={isUser}
            isReasoning={
              !isUser &&
              part.type === "text" &&
              index !== lastAssistantTextIndex
            }
            isStreamingReasoning={
              loading &&
              isLatestAssistant &&
              part.type === "text" &&
              index !== lastAssistantTextIndex
            }
          />
        ))}
      </MessageContent>
      {showActions ? (
        <MessageActions className="ml-0 text-muted-foreground">
          <MessageAction label="复制" tooltip="复制">
            <Copy className="size-3.5" />
          </MessageAction>
          <MessageAction label="赞" tooltip="赞">
            <ThumbsUp className="size-3.5" />
          </MessageAction>
          <MessageAction label="踩" tooltip="踩">
            <ThumbsDown className="size-3.5" />
          </MessageAction>
        </MessageActions>
      ) : null}
    </Message>
  );
}

function findLastAssistantTextIndex(parts: ChatPart[]) {
  for (let index = parts.length - 1; index >= 0; index -= 1) {
    if (parts[index]?.type === "text") return index;
  }
  return -1;
}

function MessagePart({
  part,
  isUser,
  isReasoning,
  isStreamingReasoning,
}: {
  part: ChatPart;
  isUser: boolean;
  isReasoning: boolean;
  isStreamingReasoning: boolean;
}) {
  if (part.type === "tool") {
    const state = part.status === "running" ? "input-available" : "output-available";

    return (
      <Tool
        data-testid="ai-elements-tool"
        defaultOpen={part.status === "running"}
        className="border-border bg-muted/20"
      >
        <ToolHeader
          state={state}
          title={part.label}
          type={`tool-${part.tool}`}
        />
        <ToolContent>
          <ToolOutput
            errorText={undefined}
            output={
              part.status === "running" ? (
                <Shimmer as="span" duration={1.15}>
                  运行中
                </Shimmer>
              ) : (
                <span>完成</span>
              )
            }
          />
        </ToolContent>
      </Tool>
    );
  }

  if (isUser) {
    return <p className="whitespace-pre-wrap">{part.text}</p>;
  }

  if (isReasoning) {
    return (
      <Reasoning
        data-testid="ai-elements-reasoning"
        defaultOpen
        isStreaming={isStreamingReasoning}
      >
        <ReasoningTrigger
          getThinkingMessage={(isStreaming, duration) => {
            if (isStreaming || duration === 0) {
              return (
                <Shimmer as="span" duration={1}>
                  正在推理
                </Shimmer>
              );
            }
            return <span>{duration ? `已思考 ${duration} 秒` : "已思考"}</span>;
          }}
        />
        <ReasoningContent>{part.text}</ReasoningContent>
      </Reasoning>
    );
  }

  return (
    <MessageResponse className="text-[0.9375rem] leading-7">
      {part.text}
    </MessageResponse>
  );
}
