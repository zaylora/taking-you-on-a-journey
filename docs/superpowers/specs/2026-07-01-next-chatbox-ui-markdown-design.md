# Next Chatbox UI And Markdown Design

## Goal

Update `frontend-next` so the chat experience matches the Vercel AI Chatbot video style from `https://chatbot.ai-sdk.dev/docs`, supports continuous multi-message conversations, and renders assistant Markdown.

## Scope

- Restyle only the `frontend-next` chat surface.
- Preserve the existing FastAPI SSE endpoint, LangGraph `thread_id` flow, and route artifact/map behavior.
- Add a forward-compatible `messages` request field containing the current visible chat history. The backend can ignore it today because LangGraph already uses `thread_id` for true conversation memory.
- Render assistant text with a mature Markdown dependency (`react-markdown` plus `remark-gfm`), not a hand-written parser.

## UI Design

The chat panel becomes a dark Vercel-style workbench:

- A compact top toolbar with square icon buttons and a model selector visual.
- A centered message column with user messages as right-aligned white pills.
- Assistant messages are left-aligned, mostly unframed, with a small sparkle avatar and action icons under text.
- Tool progress remains visible as small dark chips.
- The composer is a large floating rounded rectangle near the bottom, with an attachment icon on the left and a circular send/stop button on the right.

## Data Flow

`TripChatApp` keeps local reducer state as it does now. On submit it snapshots existing `state.messages`, appends the new user message for the UI, then calls `fetchTripChatStream` with:

- `message`: current user input
- `threadId`: current backend thread id
- `messages`: serialized prior visible messages plus the current user message

`fetchTripChatStream` posts `messages` as an additional JSON field. The existing `message` and `thread_id` fields remain unchanged.

## Markdown

Assistant text parts render through `ReactMarkdown` with `remarkGfm`. Links open in a new tab with `rel="noreferrer"`. Markdown styling stays inside the chat component via Tailwind prose-like selectors so global CSS remains small.

User messages keep plain text rendering to avoid surprising user-entered Markdown formatting.

## Testing

- Unit test `fetchTripChatStream` request body includes serialized `messages` while preserving the existing backend contract.
- Component test renders assistant Markdown as headings/strong/list/link elements.
- Component test verifies multiple local messages are shown together.
- Run `bun run test`, `bun run lint`, and `bun run build`.

