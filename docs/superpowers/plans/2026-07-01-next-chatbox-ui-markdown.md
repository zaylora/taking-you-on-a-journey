# Next Chatbox UI And Markdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle `frontend-next` chatbox to match the Vercel AI Chatbot video, add forward-compatible multi-message request history, and render assistant Markdown.

**Architecture:** Keep existing React reducer/SSE architecture. Put visual rendering and Markdown inside `ChatPanel`, add serialized history to the `fetchTripChatStream` contract, and keep route artifact behavior unchanged.

**Tech Stack:** Next.js 16 App Router, React 19 Client Components, Tailwind CSS 4, Vitest, Testing Library, `react-markdown`, `remark-gfm`.

## Global Constraints

- Do not change the FastAPI SSE endpoint path or existing `message` / `thread_id` request fields.
- Use mature Markdown dependencies instead of a hand-written parser.
- Preserve existing artifact/map UI behavior.
- Add task records under `docs/` and update `docs/README.md`.

---

### Task 1: Request Contract And Markdown Tests

**Files:**
- Modify: `frontend-next/src/lib/sse.ts`
- Modify: `frontend-next/src/lib/sse.test.ts`
- Modify: `frontend-next/src/components/chat-panel.tsx`
- Create: `frontend-next/src/components/chat-panel.test.tsx`
- Modify: `frontend-next/package.json`

**Interfaces:**
- Consumes: `ChatMessage` from `frontend-next/src/lib/types.ts`
- Produces: optional `messages?: ChatMessage[]` on `FetchTripChatStreamInput`

- [ ] Write failing tests for the `messages` request body and Markdown rendering.
- [ ] Run targeted tests and verify failure.
- [ ] Add `react-markdown` and `remark-gfm`.
- [ ] Implement minimal request serialization and Markdown rendering.
- [ ] Run targeted tests and verify pass.

### Task 2: Vercel-Style Chat UI

**Files:**
- Modify: `frontend-next/src/components/chat-panel.tsx`
- Modify: `frontend-next/src/components/trip-chat-app.tsx`

**Interfaces:**
- Consumes: `onSubmit(message: string)` and `onStop()`
- Produces: same `ChatPanel` props API plus Vercel-style DOM roles and labels

- [ ] Write or update component expectations for visible toolbar/composer behavior.
- [ ] Run targeted tests and verify failure if behavior is missing.
- [ ] Replace the old boxed chat layout with toolbar, centered message rail, and floating composer.
- [ ] Pass serialized message history from `TripChatApp` into `fetchTripChatStream`.
- [ ] Run component tests and verify pass.

### Task 3: Verification And Records

**Files:**
- Create: `docs/20260701_next_chatbox_ui_markdown/README.md`
- Modify: `docs/README.md`

- [ ] Run `bun run test` in `frontend-next`.
- [ ] Run `bun run lint` in `frontend-next`.
- [ ] Run `bun run build` in `frontend-next`.
- [ ] Start the dev server and visually verify the chatbox with browser automation.
- [ ] Document changed files, details, test results, and decisions.

