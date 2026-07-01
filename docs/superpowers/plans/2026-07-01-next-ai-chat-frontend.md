# Next AI Chat Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a separate `frontend-next/` Next.js chat UI that connects to the existing FastAPI travel-planning backend.

**Architecture:** Keep the FastAPI SSE contract unchanged. Add a Next App Router shell with a client-side chat app, a small SSE adapter, a pure reducer, and an Artifact-style route/map panel.

**Tech Stack:** Next.js 16.2.9, React 19, AI SDK 7.0.9, `@ai-sdk/react` 4.0.10, Tailwind CSS 4, shadcn/ui style components, Vitest, React Testing Library, 高德 JS API, bun.

## Global Constraints

- New code lives under `frontend-next/` except docs updates.
- Do not modify backend API contracts.
- Do not modify old Vue frontend behavior.
- Use `NEXT_PUBLIC_API_BASE` for the backend base URL.
- Use `NEXT_PUBLIC_AMAP_JS_KEY` and `NEXT_PUBLIC_AMAP_SECURITY_CODE` for browser-side map loading.
- Use bun for `frontend-next/` package management and scripts.
- Every hand-written behavior starts with a failing test.

---

### Task 1: Project Shell And Test Harness

**Files:**
- Modify: `frontend-next/package.json`
- Create: `frontend-next/vitest.config.mts`
- Create: `frontend-next/src/test/setup.ts`

**Interfaces:**
- Produces: `bun run test -- --run` for unit/component tests.

- [ ] Add Vitest scripts and config.
- [ ] Run `bun run test -- --run` and confirm tests execute.

### Task 2: Backend SSE Adapter

**Files:**
- Create: `frontend-next/src/lib/types.ts`
- Create: `frontend-next/src/lib/sse.ts`
- Test: `frontend-next/src/lib/sse.test.ts`

**Interfaces:**
- Produces: `parseSseChunk(text: string): ParsedSseEvent[]`
- Produces: `fetchTripChatStream(input, handlers): Promise<void>`

- [ ] Write a failing parser test for `token` and `final` frames.
- [ ] Implement the parser and fetch adapter.
- [ ] Run `bun run test -- --run src/lib/sse.test.ts`.

### Task 3: Trip State Reducer

**Files:**
- Create: `frontend-next/src/lib/trip-state.ts`
- Test: `frontend-next/src/lib/trip-state.test.ts`

**Interfaces:**
- Consumes: `TripSseEvent` from `src/lib/types.ts`
- Produces: `createInitialTripState()`
- Produces: `applyTripEvent(state, event): TripUiState`

- [ ] Write failing reducer tests for streamed text, tool steps, and `final.day_plans`.
- [ ] Implement minimal reducer behavior.
- [ ] Run `bun run test -- --run src/lib/trip-state.test.ts`.

### Task 4: Chat And Artifact UI

**Files:**
- Modify: `frontend-next/src/app/page.tsx`
- Modify: `frontend-next/src/app/globals.css`
- Create: `frontend-next/src/components/trip-chat-app.tsx`
- Create: `frontend-next/src/components/chat-panel.tsx`
- Create: `frontend-next/src/components/trip-artifact.tsx`
- Create: `frontend-next/src/components/ui/button.tsx`
- Create: `frontend-next/src/components/ui/textarea.tsx`
- Create: `frontend-next/src/components/ui/badge.tsx`
- Create: `frontend-next/src/lib/utils.ts`
- Test: `frontend-next/src/components/trip-chat-app.test.tsx`

**Interfaces:**
- Consumes: reducer from Task 3.
- Produces: a responsive chat app where the Artifact panel opens after a final event with day plans.

- [ ] Write a failing component test for final event opening the Artifact panel.
- [ ] Implement the UI with shadcn-style components.
- [ ] Run `bun run test -- --run src/components/trip-chat-app.test.tsx`.

### Task 5: AMap Panel

**Files:**
- Create: `frontend-next/src/components/amap-view.tsx`

**Interfaces:**
- Consumes: `DayPlan[]`, `activeDay`, `activePoiId`
- Produces: map placeholder without key, and map markers/routes when key exists.

- [ ] Add build-safe map component with no server-side `window` access.
- [ ] Wire it into `trip-artifact.tsx`.
- [ ] Run `bun run build`.

### Task 6: Documentation And Verification

**Files:**
- Create: `docs/20260701_next_ai_chat_frontend/README.md`
- Modify: `docs/README.md`

**Interfaces:**
- Produces: project change record matching AGENTS.md.

- [ ] Record changed files, decisions, and test results.
- [ ] Run backend tests, old frontend build, new frontend tests/lint/build.
- [ ] Ensure final git diff excludes unrelated generated Vue files.
