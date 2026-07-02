# AI Elements Artifact UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `frontend-next` chat page UI with AI Elements components wherever the library has a matching component, including messages, prompt input, and the right-side trip Artifact workspace.

**Architecture:** Keep the existing reducer, SSE contract, `AmapView`, and trip state. Install AI Elements source components into `frontend-next/src/components/ai-elements/`, then compose them from `ChatPanel` and `TripArtifact` while preserving all callbacks and map/card behavior.

**Tech Stack:** Next.js 16 App Router, React 19, Tailwind CSS 4, AI Elements CLI, Vitest, Testing Library, lucide-react.

## Global Constraints

- Work only in `frontend-next` plus required docs under `docs/`.
- Use AI Elements as the UI baseline for chat page components that exist in the library.
- Preserve backend SSE and frontend state contracts.
- Do not remove `AmapView` or the existing map/POI selection behavior.
- Use `bun run test` and `bun run build` for verification.

---

### Task 1: Install AI Elements Components

**Files:**
- Create/Modify: `frontend-next/src/components/ai-elements/*.tsx`
- Modify: `frontend-next/package.json`
- Modify: `frontend-next/bun.lock`
- Modify if generated: `frontend-next/components.json`
- Modify if generated: `frontend-next/src/app/globals.css`

**Interfaces:**
- Produces: imports under `@/components/ai-elements/artifact`, `conversation`, `message`, and `prompt-input`.

- [ ] **Step 1: Inspect CLI help**

Run: `cd frontend-next && bun x ai-elements@latest --help`

Expected: CLI lists an `add` command or usage for installing components.

- [ ] **Step 2: Install needed components**

Run: `cd frontend-next && bun x ai-elements@latest add artifact conversation message prompt-input`

Expected: component files are created under `src/components/ai-elements/`. If the CLI prompts for shadcn setup, choose defaults compatible with `src`, `@/*`, Tailwind CSS 4, and React Server Components.

- [ ] **Step 3: Verify generated files**

Run: `cd frontend-next && find src/components/ai-elements -maxdepth 1 -type f | sort`

Expected: includes `artifact.tsx`, `conversation.tsx`, `message.tsx`, and `prompt-input.tsx`.

### Task 2: Test ChatPanel AI Elements Behavior

**Files:**
- Modify: `frontend-next/src/components/chat-panel.test.tsx`
- Modify: `frontend-next/src/components/chat-panel.tsx`

**Interfaces:**
- Consumes: `ChatPanel` props `{ messages, loading, onSubmit, onStop }`.
- Produces: chat UI rendered via AI Elements `Conversation`, `Message`, `MessageResponse`, and `PromptInput`.

- [ ] **Step 1: Add failing behavior tests**

Add tests that assert:

```tsx
expect(screen.getByTestId("ai-elements-conversation")).toBeVisible();
expect(screen.getAllByTestId("ai-elements-message")).toHaveLength(2);
expect(screen.getByTestId("ai-elements-prompt-input")).toBeVisible();
```

Also assert that sending a message still calls `onSubmit("...")` and loading mode exposes a `停止生成` button.

- [ ] **Step 2: Run test to verify RED**

Run: `cd frontend-next && bun run test src/components/chat-panel.test.tsx`

Expected: FAIL because the current `ChatPanel` does not expose the AI Elements structure.

- [ ] **Step 3: Migrate ChatPanel**

Use AI Elements components:

```tsx
import {
  Conversation,
  ConversationContent,
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
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
} from "@/components/ai-elements/prompt-input";
```

Keep tool pills as small inline status rows because AI Elements does not provide a direct tool-progress component for the existing custom `ChatPart`.

- [ ] **Step 4: Run ChatPanel tests**

Run: `cd frontend-next && bun run test src/components/chat-panel.test.tsx`

Expected: PASS.

### Task 3: Test and Migrate TripArtifact

**Files:**
- Modify: `frontend-next/src/components/trip-chat-app.test.tsx`
- Modify: `frontend-next/src/components/trip-artifact.tsx`
- Modify: `frontend-next/src/components/trip-chat-app.tsx`

**Interfaces:**
- Consumes: `TripUiState`, `onClose`, `onSelectDay`, `onSelectPoi`.
- Produces: right-side workspace using AI Elements `Artifact`.

- [ ] **Step 1: Add failing artifact tests**

In `trip-chat-app.test.tsx`, assert:

```tsx
expect(screen.getByTestId("ai-elements-artifact")).toBeVisible();
expect(screen.getByRole("heading", { name: "行程地图" })).toBeVisible();
expect(screen.getByText("1 天路线")).toBeVisible();
expect(screen.getByText("陈家祠")).toBeVisible();
```

- [ ] **Step 2: Run test to verify RED**

Run: `cd frontend-next && bun run test src/components/trip-chat-app.test.tsx`

Expected: FAIL because current right panel is not composed with AI Elements Artifact.

- [ ] **Step 3: Migrate TripArtifact**

Use AI Elements components:

```tsx
import {
  Artifact,
  ArtifactAction,
  ArtifactActions,
  ArtifactClose,
  ArtifactContent,
  ArtifactDescription,
  ArtifactHeader,
  ArtifactTitle,
} from "@/components/ai-elements/artifact";
```

Keep `AmapView`, budget summary, day tabs, and route item callbacks. Use CSS/Tailwind classes for a smooth slide/fade workspace.

- [ ] **Step 4: Run artifact tests**

Run: `cd frontend-next && bun run test src/components/trip-chat-app.test.tsx`

Expected: PASS.

### Task 4: Verify and Document

**Files:**
- Create: `docs/20260702_ai_elements_artifact_ui/README.md`
- Modify: `docs/README.md`

**Interfaces:**
- Produces: required project change record.

- [ ] **Step 1: Run focused and full verification**

Run:

```bash
cd frontend-next && bun run test
cd frontend-next && bun run build
```

Expected: both commands exit 0.

- [ ] **Step 2: Write change record**

Create `docs/20260702_ai_elements_artifact_ui/README.md` with task goal, changed files, details, test results, and design decisions.

- [ ] **Step 3: Update docs index**

Append the new record to `docs/README.md`.
