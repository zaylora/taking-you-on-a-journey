"use client";

import { AnimatePresence, motion } from "motion/react";
import { Plus } from "lucide-react";
import { useEffect, useReducer, useRef, useState } from "react";

import { ChatPanel } from "@/components/chat-panel";
import { TripArtifact } from "@/components/trip-artifact";
import { Button } from "@/components/ui/button";
import {
  createSession,
  getSession,
  listSessions,
  tripStateFromSessionSnapshot,
} from "@/lib/sessions";
import { fetchTripChatStream } from "@/lib/sse";
import {
  applyTripEvent,
  createInitialTripState,
  setActiveDay,
  setActivePoi,
  userMessage,
} from "@/lib/trip-state";
import type {
  ChatMessage,
  SessionListItem,
  TripSseEvent,
  TripUiState,
} from "@/lib/types";
import { cn } from "@/lib/utils";

type Action =
  | { type: "event"; event: TripSseEvent }
  | { type: "submit"; message: string }
  | { type: "loading"; value: boolean }
  | { type: "load-snapshot"; state: Partial<TripUiState> }
  | { type: "close-artifact" }
  | { type: "select-day"; day: number | null }
  | { type: "select-poi"; poiId: string | null };

interface TripChatAppProps {
  initialState?: Partial<TripUiState>;
}

export function TripChatApp({ initialState }: TripChatAppProps) {
  const abortRef = useRef<AbortController | null>(null);
  const shouldLoadSessions = initialState === undefined;
  const [sessions, setSessions] = useState<SessionListItem[]>([]);
  const [historySidebarOpen, setHistorySidebarOpen] = useState(true);
  const [state, dispatch] = useReducer(
    reducer,
    createInitialTripState(initialState),
  );

  useEffect(() => {
    if (!shouldLoadSessions) return;

    let cancelled = false;
    const restoreLatestSession = async () => {
      try {
        const { sessions: nextSessions } = await listSessions();
        if (cancelled) return;

        setSessions(nextSessions);
        const latest = nextSessions[0];
        if (!latest) return;

        const snapshot = await getSession(latest.thread_id);
        if (!cancelled) {
          dispatch({
            type: "load-snapshot",
            state: tripStateFromSessionSnapshot(snapshot),
          });
        }
      } catch (error) {
        console.warn("恢复会话列表失败:", error);
      }
    };

    void restoreLatestSession();
    return () => {
      cancelled = true;
    };
  }, [shouldLoadSessions]);

  const refreshSessionList = async () => {
    if (!shouldLoadSessions) return;
    try {
      const { sessions: nextSessions } = await listSessions();
      setSessions(nextSessions);
    } catch (error) {
      console.warn("刷新会话列表失败:", error);
    }
  };

  const handleNewSession = async () => {
    if (state.loading) return;

    try {
      const session = await createSession();
      setSessions((items) => upsertSession(items, session));
      dispatch({
        type: "load-snapshot",
        state: {
          threadId: session.thread_id,
          messages: [],
          dayPlans: [],
          budget: null,
          planVersion: 0,
          artifactOpen: false,
          activeDay: null,
          activePoiId: null,
          loading: false,
          error: null,
        },
      });
    } catch (error) {
      console.warn("新建会话失败:", error);
    }
  };

  const handleSelectSession = async (threadId: string) => {
    if (state.loading || threadId === state.threadId) return;

    try {
      const snapshot = await getSession(threadId);
      dispatch({
        type: "load-snapshot",
        state: tripStateFromSessionSnapshot(snapshot),
      });
    } catch (error) {
      console.warn("加载历史会话失败:", error);
    }
  };

  const handleSubmit = async (message: string) => {
    const controller = new AbortController();
    let streamedThreadId = state.threadId;
    const history: ChatMessage[] = [
      ...state.messages,
      userMessage(message, state.messages.length + 1),
    ];
    abortRef.current = controller;
    dispatch({ type: "submit", message });

    try {
      await fetchTripChatStream(
        { message, threadId: state.threadId, messages: history },
        (event, data) => {
          if (typeof data === "object" && data !== null) {
            const threadId = stringValue((data as Record<string, unknown>).thread_id);
            if (event === "session" && threadId) {
              streamedThreadId = threadId;
            }
            dispatch({
              type: "event",
              event: { event, data: data as Record<string, unknown> },
            });
          }
        },
        controller.signal,
      );
    } catch (error) {
      if ((error as Error).name !== "AbortError") {
        dispatch({
          type: "event",
          event: {
            event: "error",
            data: { message: "连接失败，请确认后端已启动" },
          },
        });
      }
    } finally {
      dispatch({ type: "loading", value: false });
      abortRef.current = null;
      if (streamedThreadId) {
        void refreshSessionList();
      }
    }
  };

  const handleStop = () => {
    abortRef.current?.abort();
    dispatch({ type: "loading", value: false });
  };

  return (
    <main className="flex h-dvh min-h-0 overflow-hidden bg-zinc-950">
      {historySidebarOpen ? (
        <SessionSidebar
          activeThreadId={state.threadId}
          loading={state.loading}
          onNewSession={handleNewSession}
          onSelectSession={handleSelectSession}
          sessions={sessions}
        />
      ) : null}
      <motion.div
        layout
        className="flex h-full min-w-0 flex-1"
        transition={layoutTransition}
      >
        <ChatPanel
          messages={state.messages}
          activeNodeLabel={state.activeNodeLabel}
          loading={state.loading}
          onSubmit={handleSubmit}
          onStop={handleStop}
          onToggleHistorySidebar={() =>
            setHistorySidebarOpen((isOpen) => !isOpen)
          }
        />
      </motion.div>

      <AnimatePresence initial={false}>
        {state.artifactOpen ? (
          <motion.div
            key="trip-artifact"
            data-testid="trip-artifact-motion"
            data-state="open"
            layout
            initial="closed"
            animate="open"
            exit="closed"
            variants={artifactPanelVariants}
            transition={artifactPanelTransition}
            className="fixed inset-x-0 bottom-0 top-14 z-20 will-change-transform lg:static lg:h-full lg:w-[min(46vw,820px)] lg:max-w-[820px] lg:shrink-0"
          >
            <TripArtifact
              state={state}
              onClose={() => dispatch({ type: "close-artifact" })}
              onSelectDay={(day) => dispatch({ type: "select-day", day })}
              onSelectPoi={(poiId) => dispatch({ type: "select-poi", poiId })}
            />
          </motion.div>
        ) : null}
      </AnimatePresence>
    </main>
  );
}

function SessionSidebar({
  activeThreadId,
  loading,
  onNewSession,
  onSelectSession,
  sessions,
}: {
  activeThreadId: string | null;
  loading: boolean;
  onNewSession: () => void;
  onSelectSession: (threadId: string) => void;
  sessions: SessionListItem[];
}) {
  return (
    <aside className="flex h-full w-60 shrink-0 flex-col border-r border-border bg-background text-foreground">
      <div className="flex h-14 shrink-0 items-center justify-between border-b border-border px-3">
        <h2 className="text-sm font-medium">历史会话</h2>
        <Button
          type="button"
          aria-label="新建会话"
          title="新建会话"
          variant="outline"
          size="icon"
          disabled={loading}
          onClick={onNewSession}
          className="h-8 w-8 bg-background"
        >
          <Plus className="size-4" />
        </Button>
      </div>

      <nav
        aria-label="历史会话"
        className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto p-2"
      >
        {sessions.map((session) => {
          const active = session.thread_id === activeThreadId;
          return (
            <button
              key={session.thread_id}
              type="button"
              aria-current={active ? "page" : undefined}
              className={cn(
                "w-full truncate rounded-md px-3 py-2 text-left text-sm transition-colors",
                active
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
              disabled={loading}
              onClick={() => onSelectSession(session.thread_id)}
            >
              {session.title || "新的行程"}
            </button>
          );
        })}
      </nav>
    </aside>
  );
}

const layoutTransition = {
  type: "spring",
  stiffness: 420,
  damping: 38,
  mass: 0.7,
} as const;

const artifactPanelVariants = {
  closed: {
    opacity: 0,
    x: 56,
    scale: 0.985,
    filter: "blur(2px)",
  },
  open: {
    opacity: 1,
    x: 0,
    scale: 1,
    filter: "blur(0px)",
  },
};

const artifactPanelTransition = {
  layout: layoutTransition,
  opacity: { duration: 0.18, ease: "easeOut" },
  x: layoutTransition,
  scale: layoutTransition,
  filter: { duration: 0.16, ease: "easeOut" },
} as const;

function reducer(state: TripUiState, action: Action): TripUiState {
  switch (action.type) {
    case "event":
      return applyTripEvent(state, action.event);
    case "submit":
      return {
        ...state,
        loading: true,
        error: null,
        nodeProgress: {},
        nodeLabels: {},
        activeNodeLabel: null,
        messages: [...state.messages, userMessage(action.message, state.messages.length + 1)],
      };
    case "loading":
      return {
        ...state,
        loading: action.value,
        activeNodeLabel: action.value ? state.activeNodeLabel : null,
        nodeProgress: action.value ? state.nodeProgress : {},
        nodeLabels: action.value ? state.nodeLabels : {},
      };
    case "load-snapshot":
      return createInitialTripState(action.state);
    case "close-artifact":
      return { ...state, artifactOpen: false };
    case "select-day":
      return setActiveDay(state, action.day);
    case "select-poi":
      return setActivePoi(state, action.poiId);
    default:
      return state;
  }
}

function upsertSession(
  sessions: SessionListItem[],
  session: SessionListItem,
): SessionListItem[] {
  return [session, ...sessions.filter((item) => item.thread_id !== session.thread_id)]
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at));
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}
