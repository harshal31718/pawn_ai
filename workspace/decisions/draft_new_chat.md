# Decision: Draft "New Chat" — no persistence until the first message

Status: Implemented (2026-06-28). Part of Phase MU Drive-latency hardening (PERF-2a).

## Why

With Drive-backed storage, eagerly creating a conversation on every "New Chat" click was wrong:
it wrote empty `meta.json`/`messages.jsonl` to Drive for chats that may never be used, made the
button feel slow, and (under the earlier optimistic impl) could produce duplicate empty chats.

## Behavior (contract)

1. Clicking **New Chat** shows the existing new-chat welcome page in the chat area; the active
   conversation points at a client-generated *draft* id.
2. **Nothing** is created on Drive / Supabase / local, and no background sync op is enqueued, until
   the first message is actually sent.
3. At most **one** draft exists at a time — repeat New Chat clicks just re-focus the existing draft.
   No duplicate empty chats.
4. There is never more than one "New Chat" in flight.
5. The sidebar shows **no row** for an unsaved draft (nothing highlighted). The titled row appears
   only after the first message is sent.
6. The Drive conversation is created **only on the first real message**.

## Where the logic lives

- Frontend draft state + lifecycle: `frontend/src/store/useConversationStore.ts`
  - `createConversation()` — opens/reuses the single frontend-only draft (`draftConvId`); sets it
    active with an empty in-memory message buffer; does NOT add to `conversations`, does NOT enqueue.
  - `promoteDraft(id)` — called from `App.tsx` `handleSend` at first send; adds the conversation meta
    to the list (sidebar row appears) and clears the draft. No `create` op is enqueued.
  - The persist effect excludes `draftConvId` from the localStorage cache, so an unsent draft is never
    cached (and is gone after reload — expected, nothing to save).
- First send wiring: `frontend/src/App.tsx` `handleSend` → `promoteDraft(convId)` before streaming.
- Backend materialization: `backend/app/routes/chat.py` lazy-creates the conversation (with the
  client-owned id) when its meta is missing, so the first streamed message persists it on Drive.
  `_create_with_id` writes `meta.json`; the existing append/auto-title/summarize tail then runs.

## Notes / consequences

- The `create` `SyncOp` in `frontend/src/store/syncQueue.ts` is now **unused** (kept defensively).
- An unsent draft does not survive a page reload; on reload with zero conversations the store
  bootstrap opens a fresh draft (still no Drive file).
- Deleting the last real conversation falls back to a draft (welcome page), not a persisted chat.
