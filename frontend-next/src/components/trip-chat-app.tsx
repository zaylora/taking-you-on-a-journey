"use client";

import { useReducer, useRef } from "react";

import { ChatPanel } from "@/components/chat-panel";
import { TripArtifact } from "@/components/trip-artifact";
import { fetchTripChatStream } from "@/lib/sse";
import {
  applyTripEvent,
  createInitialTripState,
  setActiveDay,
  setActivePoi,
  userMessage,
} from "@/lib/trip-state";
import type { TripSseEvent, TripUiState } from "@/lib/types";

type Action =
  | { type: "event"; event: TripSseEvent }
  | { type: "submit"; message: string }
  | { type: "loading"; value: boolean }
  | { type: "close-artifact" }
  | { type: "select-day"; day: number | null }
  | { type: "select-poi"; poiId: string | null };

interface TripChatAppProps {
  initialState?: Partial<TripUiState>;
}

export function TripChatApp({ initialState }: TripChatAppProps) {
  const abortRef = useRef<AbortController | null>(null);
  const [state, dispatch] = useReducer(
    reducer,
    createInitialTripState(initialState),
  );

  const handleSubmit = async (message: string) => {
    const controller = new AbortController();
    abortRef.current = controller;
    dispatch({ type: "submit", message });

    try {
      await fetchTripChatStream(
        { message, threadId: state.threadId },
        (event, data) => {
          if (typeof data === "object" && data !== null) {
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
    }
  };

  const handleStop = () => {
    abortRef.current?.abort();
    dispatch({ type: "loading", value: false });
  };

  return (
    <main className="flex h-dvh min-h-0 overflow-hidden bg-zinc-950">
      <ChatPanel
        messages={state.messages}
        loading={state.loading}
        onSubmit={handleSubmit}
        onStop={handleStop}
      />

      {state.artifactOpen ? (
        <div className="fixed inset-x-0 bottom-0 top-14 z-20 lg:static lg:h-full">
          <TripArtifact
            state={state}
            onClose={() => dispatch({ type: "close-artifact" })}
            onSelectDay={(day) => dispatch({ type: "select-day", day })}
            onSelectPoi={(poiId) => dispatch({ type: "select-poi", poiId })}
          />
        </div>
      ) : null}
    </main>
  );
}

function reducer(state: TripUiState, action: Action): TripUiState {
  switch (action.type) {
    case "event":
      return applyTripEvent(state, action.event);
    case "submit":
      return {
        ...state,
        loading: true,
        error: null,
        messages: [...state.messages, userMessage(action.message, state.messages.length + 1)],
      };
    case "loading":
      return { ...state, loading: action.value };
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
