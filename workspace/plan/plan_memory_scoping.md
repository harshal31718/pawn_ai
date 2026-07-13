# Plan: Memory Scoping — Standalone Chats, Projects, and Scoped RAG

*Branch: dev. Status: planned 2026-07-13 (v3 final — supersedes v1 two-tier
global-facts and v2 shared-project-file designs; moves revised to two-way same day).
Not started.*
*Tracker: register as Phase M in `workspace/status/build_tracker.md` when work begins.*

> **This plan is prescriptive.** All design decisions are final and locked with the
> user. Implement exactly as written — do not substitute alternative designs, add
> options, or re-open decisions. If something written here turns out to be impossible
> or contradicts the codebase, stop and ask the user; do not improvise a different
> model. Where the plan names a constant, file, route, or semantic, use exactly that.

---

## 1. Problem

Today's memory system has exactly one behavior: whole-conversation 150-word summaries in
`memory_chunks`, retrievable from **every other chat** of the user (`retrieve()` passes
`exclude_conv_id` = the active chat, i.e. it reads *only other* chats). Consequences:

1. **No isolation** — anything discussed in chat A leaks into chat B via its summary.
2. **No in-chat recall** — the active chat cannot RAG its own history; long chats rely on
   the lossy rolling `summary.md` + last-10-message context window.
3. **No grouping** — no way to have a set of related chats that share knowledge.
4. **No management or provenance** — nothing can be viewed, cleared, or rebuilt.

## 2. Decisions (locked 2026-07-13)

| # | Decision | Choice |
|---|---|---|
| 1 | Container model | **Two container types**: standalone chats and projects (a project holds multiple chats). |
| 2 | Standalone chat memory | Rolling `summary.md` (unchanged, fast path) **+ its own chat-level RAG** over its full message history. Retrieval never crosses into any other chat. |
| 3 | Project memory | Each chat inside a project keeps its own rolling `summary.md`. RAG is **project-scoped**: retrieval from any chat in the project searches across the chunks of *all* chats in that project. Nothing outside the project can reach it. |
| 4 | Global tier | **Dropped — full isolation.** No cross-boundary memory of any kind. A new standalone chat or new project starts with zero knowledge of the user. |
| 5 | Retrieval trigger | **Agent-driven**: the LangGraph `search_memory` node decides when the rolling summary + window is insufficient and queries the scoped RAG. Not always-injected. |
| 6 | RAG storage | **Drive = source of truth, Postgres = queryable index.** Chunk text persists to per-chat `rag_chunks.jsonl` files on the user's Drive. Postgres `memory_chunks` (text + embedding + scope) is a derived, rebuildable index — retrieval only ever hits Postgres. |
| 7 | RAG file granularity | **Per-chat files always — no shared project file.** The "project RAG" is a *logical* scope in Postgres (`scope_type='project'`), not a physical merged file. Fixes the unbounded full-file-rewrite cost Drive's no-append forces, and makes move-in a pure folder relocate. (v3; replaces v2's shared `project_rag_chunks.jsonl`.) |
| 8 | Chat moves | **Two-way: standalone ↔ project.** (Revised same-day: one-way was chosen when the design had a merged project rag file; decision #7's per-chat files make move-out clean — relocate folder + PG scope update, chunks fully re-scope.) Move-out dialog notes the one honest caveat: knowledge *already used* by sibling chats' replies while shared stays in those chats; only this chat's own chunks un-share. |
| 9 | Delete project | **Cascade: deletes all chats inside it** (Drive folders + PG chunks). Warning dialog listing the chats carries the weight. |
| 10 | Existing data | **Wipe `memory_chunks`** (drop/recreate). Existing Drive conversations migrate into the new `chats/` folder via a one-time migration. |

## 3. Drive folder structure (target)

```
PAWN/
  conversations/
    chats/
      <conv_id>/
        meta.json            # name, timestamps (existing format)
        messages.jsonl       # existing
        summary.md           # rolling summary (existing)
        rag_chunks.jsonl     # NEW — chunk source of truth for this chat
    projects/
      <project_id>/
        project.json         # NEW — {id, name, created_at, updated_at}
        <conv_id>/
          meta.json
          messages.jsonl
          summary.md
          rag_chunks.jsonl   # per-chat, same as standalone (decision #7)
  uploads/                   # unchanged (out of scope, see §8)
```

- **Folder naming: `<id>` only, never `<name>_<id>`.** Display names live in
  `meta.json` / `project.json`. Renames must never relocate Drive folders (slow,
  failure-prone, invalidates the drive_factory file-ID cache).
- **Which scope a chat belongs to is encoded purely by folder placement** — under
  `chats/` = standalone; under `projects/<pid>/` = that project. No membership table.
- **jsonl rewrite caveat (bounded, accepted):** Drive has no partial append — a flush
  rewrites the whole file. With per-chat files the rewrite is bounded by one chat's own
  history (same growth class as the existing `messages.jsonl` limitation), not the whole
  project. If a single monster chat ever hurts, shard that file by count — deferred.

`rag_chunks.jsonl` record format (one JSON object per line):

```json
{"chunk_id": "<uuid>", "conv_id": "<chat id>", "msg_index": 42,
 "text": "...", "created_at": "2026-07-13T..."}
```

No embeddings on Drive (derived, model-versioned, 10× bloat); rebuild re-embeds from
these files.

## 4. Postgres schema (index layer)

`memory_chunks` redefined (wipe + recreate):

```sql
create table if not exists memory_chunks (
  id         bigserial primary key,
  chunk_id   uuid not null,              -- matches the Drive record; idempotency key
  user_id    text references users(user_id) on delete cascade,
  scope_type text not null,              -- 'chat' | 'project'
  scope_id   text not null,              -- conv_id when 'chat', project_id when 'project'
  conv_id    text not null,              -- originating chat (provenance; = scope_id for 'chat')
  kind       text not null default 'message',  -- 'message' | 'document' (documents used by
                                               -- plan_chat_agent_refinement.md's doc_search;
                                               -- Phase M itself only writes 'message')
  doc_id     text,                       -- set only when kind='document' (ditto)
  msg_index  int,
  text       text not null,
  embedding  vector(768),
  fts_doc    tsvector generated always as (to_tsvector('english', text)) stored,
  created_at timestamptz default now(),
  unique (user_id, chunk_id)
);
-- ivfflat (embedding), gin (fts_doc), btree (user_id, scope_type, scope_id)
```

SQL functions replace the current pair (which will be dropped):

```
match_scoped_chunks(query_embedding, match_user_id, match_scope_type, match_scope_id, match_kind, match_count)
search_scoped_chunks(query_text,     match_user_id, match_scope_type, match_scope_id, match_kind, match_count)
```

Both filter `WHERE user_id = ... AND scope_type = ... AND scope_id = ...` — equality, the
**inverse** of today's exclude filter — plus `AND (match_kind IS NULL OR kind = match_kind)`.
No query can ever reach another scope. Phase M callers always pass
`match_kind = 'message'`; the `kind`/`doc_id` machinery is inert until
`plan_chat_agent_refinement.md` (a follow-on plan) adds document indexing.

**No `projects` table in Postgres.** Project metadata lives on Drive (`project.json` +
folder placement), matching how conversations already work. Postgres only sees
`scope_id` strings — clean "user data on Drive, app data in Postgres" split.

**Migration reality check:** `postgres/schema.sql` only auto-runs on a *fresh* volume.
Local dev and prod both have initialized volumes → ship
`postgres/migrations/2026-07_memory_scoping.sql` (drop old functions, drop+recreate
`memory_chunks`, create new functions) and document manual apply
(`docker compose exec postgres psql ...`) in `deployment.md`'s upgrade notes. Forgetting
this on prod = retrieval silently broken.

---

## 5. Implementation steps

### M.1 — Schema + migration file

- Update `postgres/schema.sql` (table + functions as §4); write
  `postgres/migrations/2026-07_memory_scoping.sql`; apply to local dev Postgres.
- `memory/index.py` → `add_chunk(user_id, scope_type, scope_id, conv_id, chunk_id,
  msg_index, text, embedding)`; upsert on `(user_id, chunk_id)` (idempotent re-index).
- Tests: insert/upsert idempotency (mock `fetchone`).
- *Demo:* psql shows new table + functions; old functions gone.

### M.2 — Drive storage layer: new layout + projects

- **New DriveStorage primitive (prerequisite — does not exist today):**
  `storage/drive.py` gains `move_item(item_id, new_parent_id, old_parent_id)` →
  `files().update(fileId=..., addParents=new, removeParents=old, fields="id, parents")`.
  Follow the existing method conventions (lock, file-ID cache invalidation for moved
  items, socket timeout). Mirror it in `tests/fake_drive.py`. Every move/migration
  below uses this primitive.
- `storage/conversations_drive.py`: `_convs_folder()` retargeted to
  `PAWN/conversations/chats/`; new project-aware folder resolution for
  `projects/<pid>/<conv_id>/`; per-chat rag jsonl helpers (`load_rag_chunks`,
  `append_rag_chunks` — full-file rewrite, batched per turn). All existing call sites
  updated (routes/conversations, routes/chat, memory/summarize).
- New `storage/projects_drive.py`: `create_project` (folder + `project.json`),
  `list_projects`, `rename_project` (json rewrite only, no folder move),
  `delete_project` (cascade: recursively deletes the project folder and everything in
  it — build on the existing `delete_folder_by_name`/`delete_file` primitives),
  `list_project_chats`, and `move_chat(conv_id, from_parent_id, to_parent_id)` (thin
  wrapper over `drive.move_item`, used for BOTH move-in and move-out).
- **One-time Drive migration (locked: automatic)**: move every existing
  `PAWN/conversations/<conv_id>/` → `PAWN/conversations/chats/<conv_id>/`. Runs
  automatically on the first authenticated request per user (detect legacy layout →
  migrate each folder via Drive parent update → log per folder to stderr), with a
  legacy read-fallback until the migration completes. Migration state is inferred from
  layout (no flag file): a conversation found at the legacy path is migrated on access.
- Tests: extend `tests/fake_drive.py` with folder-move + recursive delete; project CRUD
  tests; migration test (legacy tree in FakeDrive → migrated tree).
- *Demo:* create project via curl → Drive shows `projects/<id>/project.json`; old chats
  appear under `chats/`.

### M.3 — Chunker + write path (indexing every turn)

- New `memory/chunker.py`: split a committed turn (user msg + assistant reply) into
  chunks carrying `msg_index`. Constants in `app/constants.py`:
  `MEMORY_CHUNK_TOKENS = 400`, `MEMORY_CHUNK_OVERLAP_TOKENS = 50` (token counts
  approximated as `len(text) // 4` — no tokenizer dependency).
- New `memory/indexer.py` → `index_turn_task(user_id, conv_id, scope, turn_msgs)`
  (background task scheduled from `chat.py`'s existing persist-turn block — the
  `if req.conversation_id and success ...` branch that already schedules
  `auto_title_background_task`/`summarize_conversation_task`). **Stateless chats
  (`conversation_id=None`) are never indexed** — no conversation, no memory, matching
  their existing no-persistence semantics.
  Task behavior:
  chunk → append records to **the chat's own** `rag_chunks.jsonl` → embed each chunk
  (existing BYOK `embed()`) → `add_chunk` PG rows with the chat's *current scope*
  (`('chat', conv_id)` standalone; `('project', pid)` inside a project). Order matters:
  **Drive write first** (source of truth), PG second; PG failure is recoverable by
  rebuild, Drive failure aborts (no orphan index rows).
- Scope resolution `resolve_scope(user_id, conv_id) -> (scope_type, scope_id)` — from
  folder placement, cached in-process with `SCOPE_CACHE_TTL_SECONDS = 300`
  (`app/constants.py`); cache entry explicitly evicted on any move.
- **Rebuild path**: `rebuild_index(user_id, scope_type, scope_id)` — delete scope's PG
  rows, re-read the relevant `rag_chunks.jsonl` file(s) (for a project: every chat's
  file under the project folder), re-embed, re-insert. Used after moves, disasters,
  embed-model change. HTTP surface defined in M.6's `routes/memory.py`.
- **Cleanup**: `DELETE /conversations/{id}` also deletes that chat's PG rows
  (`where user_id=%s and conv_id=%s` — works in both scopes via provenance). Today
  conversation delete leaves Postgres untouched — pre-existing gap, closed here.
- Tests: chunker unit tests; indexer with FakeDrive + mocked embed/PG (never real API
  calls); Drive-fails → no PG rows; delete-cleans-chunks.
- *Demo:* send messages → chat's `rag_chunks.jsonl` grows; PG rows carry correct scope.

### M.4 — Retrieval rewrite + agent wiring

- `memory/retrieve.py` → `retrieve(query, user_id, scope_type, scope_id, top_k)` with
  `MEMORY_TOP_K = 4` in `app/constants.py`:
  hybrid pgvector + FTS via the new scoped SQL functions, RRF fusion (existing logic
  kept), **within one scope only**. The old cross-chat behavior (Step 15's "fact from
  chat A surfaces in chat B") is deliberately removed for standalone chats and becomes
  project-only.
- `agent/graph.py` — **two retrieval call sites exist today; the plan changes both**:
  1. `load_context_node` currently ALWAYS calls `retrieve()` at graph start
     (always-injected). Per decision #5 this retrieval is **removed** —
     `load_context_node` no longer touches memory; `retrieved_memory` starts `[]` and
     is populated only by `search_memory_node`. (The rolling summary remains the
     always-present context, unchanged.)
  2. `search_memory_node` switches from `retrieve(query, user_id,
     active_conv_id=...)` (exclude semantics) to the new scoped signature.
  `AgentState` gains `scope_type`/`scope_id` (resolved once per request in `chat.py`;
  for stateless chats scope is `None` and `search_memory` returns `[]` without querying).
  The agent prompt's `search_memory` action description updated: reach for RAG when the
  summary window lacks the answer ("not forgetting anything" = agent's escape hatch,
  not a per-turn tax).
- `events.memory_hit_event(summary, scope, source_conv_id)` — payload becomes
  `{"type": "memory_hit", "summary": ..., "scope": "chat"|"project",
  "source_conv_id": ...}` (existing `summary` key kept, new keys additive);
  `client.ts` types + `Message.tsx` metadata cards show a scope badge (for project hits,
  which chat it came from).
- Tests: `test_rag.py` rewritten — same-scope hit, **cross-scope miss (the isolation
  guarantee, the core test of this plan)**, agent scope threading. `test_agent.py`
  patches `app.memory.retrieve.retrieve` in two places — update those mocks to the new
  signature and to `load_context_node` no longer retrieving.
- *Demo:* topic in standalone chat A NOT retrievable from chat B; two chats in one
  project see each other's content.

### M.5 — Projects backend API + two-way chat moves

- New `routes/projects.py` (registered in `main.py`, own test file per testing rules):
  - `POST /projects` (client-generated id, idempotent — mirror conversations pattern)
  - `GET /projects` (list with names + chat counts)
  - `PATCH /projects/{id}` (rename)
  - `DELETE /projects/{id}` — **cascade**: recursively deletes the project folder on
    Drive (all chats included) + `delete from memory_chunks where user_id=%s and
    scope_type='project' and scope_id=%s`. Frontend confirm dialog enumerates the chats
    being destroyed (decision #9).
  - `POST /projects/{id}/chats/{conv_id}` — move in.
  - `DELETE /projects/{id}/chats/{conv_id}` — move out (back to standalone).
- **Move semantics — symmetric, and cheap thanks to per-chat files (decision #7):**
  - *In:* relocate the chat folder `chats/<id>` → `projects/<pid>/<id>` (single Drive
    metadata call), then PG `update memory_chunks set scope_type='project',
    scope_id=%s where user_id=%s and conv_id=%s`.
  - *Out:* relocate `projects/<pid>/<id>` → `chats/<id>`, then PG `update ... set
    scope_type='chat', scope_id=conv_id where user_id=%s and conv_id=%s`. Sibling chats
    immediately lose retrieval access to this chat's chunks.
  - No re-embedding (embeddings are scope-independent), no jsonl reading/merging/
    rewriting in either direction. Scope cache invalidated on both.
- **Failure recovery**: two steps across two systems, Drive first. If the PG update
  fails after the folder moved, `rebuild_index` on the affected scope(s) repairs from
  Drive. Invariant stated in code comments: *Drive layout is authoritative; Postgres is
  always regenerable from it.* Both moves idempotent (re-running converges).
- Locking: per-`(user, conv)` asyncio lock (one shared helper, e.g.
  `memory/locks.py`) acquired by BOTH move operations AND M.3's `index_turn_task` —
  a turn being indexed mid-move must either finish under the old scope before the
  move proceeds or index under the new scope after it; never interleave.
- Tests: `test_projects.py` — CRUD; move-in and move-out (FakeDrive placement + PG
  scope updates both directions); idempotency; **post-move-out isolation** (sibling
  retrieval returns nothing from the departed chat); cascade delete removes folders +
  PG rows; moved chat's new turns index into its current scope.
- *Demo:* curl move a chat in → chunks retrievable from a sibling; move it out →
  sibling retrieval no longer surfaces them; delete project → chats + chunks gone.

### M.6 — Frontend: projects UI + move flows

UI inspiration: ChatGPT/Claude projects — sidebar sections, expandable project groups,
"New chat in project", project page listing its chats.

- `types.ts`: `Project {id, name, created_at, chat_count?}`; `ConversationMeta` gains
  `project_id?: string`.
- `client.ts`: `getProjects/createProject/renameProject/deleteProject/
  moveChatToProject/removeChatFromProject` helpers (no inline fetch anywhere else, per
  frontend rules).
- Store: `useConversationStore` remains the single owner — it gains a `projects` list
  and `ConversationMeta.project_id` for the mapping (no separate project store; one
  source of truth, mirroring how conversations already work); `conversationCache`
  persists both; `syncQueue`'s op union (currently `'create' | 'rename' | 'delete'`,
  keyed by `convId`) is extended with exactly four new kinds:
  `'createProject' | 'renameProject' | 'deleteProject' | 'moveChat'` (`moveChat`
  carries `convId` + `projectId: string | null`, null = move out to standalone). Same
  behaviors as existing ops: optimistic UI, backoff retry, 404-as-success. Moves are
  optimistic in the sidebar; dialogs (below) are blocking.
- `Sidebar.tsx` (will exceed 150 lines — split into `components/ProjectSection.tsx`
  (the collapsible projects block) and `components/ProjectRow.tsx` (one project +
  its expanded chat list) per frontend rules): **Projects** section
  (collapsible rows, chevron-expand showing contained chats, + new-chat-inside, kebab:
  rename/delete) above the flat **Chats** list. Standalone chat kebab gains
  "Add to project ▸" submenu; chats inside projects gain "Remove from project".
  Mini-sidebar keeps a projects icon.
- **Dialogs (blocking, explicit confirm):**
  1. Add-to-project (informational): "This chat's history becomes part of the project's
     shared memory — other chats in the project can use it."
  2. Remove-from-project (informational): "This chat's memory leaves the project. Note:
     anything other chats already wrote using this chat's info stays in those chats."
  3. Delete-project (destructive): lists contained chat names; "Deletes the project
     **and all N chats inside it**, including their memory. This cannot be undone."
- Routing (existing routes are `/chat` and `/chat/:id` — keep the `:id` param name):
  add `/project/:projectId` (project page: name header, chat list, new-chat button)
  and `/project/:projectId/chat/:id`; `/chat/:id` stays for standalone. `ChatPage`
  resolves scope from the route params.
- New-chat flow: the draft-chat mechanism (PERF-2a) gains an optional target project —
  a draft promoted inside a project materializes under `projects/<pid>/` directly (born
  in project scope, no move needed).
- Memory management surface (small — no global tier): new `routes/memory.py`
  (registered in `main.py`, own test file) with exactly two endpoints, both
  user-scoped, body `{"scope_type": "chat"|"project", "scope_id": "..."}`:
  `POST /memory/rebuild` (calls M.3's `rebuild_index`) and `POST /memory/clear`
  (deletes the scope's PG rows AND the corresponding `rag_chunks.jsonl` file(s) on
  Drive — both layers, so cleared memory cannot resurrect via rebuild).
  **UI placement — NOT in Settings** (a Settings card would need its own scope
  picker; the scope is already implicit in the sidebar): each chat kebab and each
  project kebab gains a "Memory ▸" submenu with "Clear memory" (confirm dialog) and
  "Rebuild memory index". Full chunk browser deferred.
- Gate: `tsc` zero errors, `npm run build` clean.
- *Demo:* create project in sidebar → two chats inside share retrieval (memory_hit badge
  shows source chat) → add a standalone chat → its history retrievable by siblings →
  remove it → siblings lose access → delete project (dialog lists chats) → everything
  gone. Refresh mid-flow: optimistic state reconciles.

### M.7 — Tests, review, live verify

- Full backend suite green (pytest; provider + Drive + PG all mocked per testing rules).
- code-reviewer + security-auditor via the `build-step` skill (new route module touching
  user-scoped data).
- Live verification checklist (real stack, real Drive):
  1. Legacy Drive tree migrates cleanly; old chats load from `chats/`.
  2. Standalone chat A content NOT retrievable in chat B (the isolation guarantee).
  3. Long standalone chat (40+ msgs) recalls an early detail via its own RAG when the
     agent decides to search.
  4. Two chats in one project share retrieval both directions; a chat outside sees none.
  5. Add standalone chat to project → siblings retrieve its history; its new turns
     index into project scope. Remove it → siblings can no longer retrieve any of its
     chunks; its new turns index into chat scope again.
  6. Delete chat → its PG chunks gone. Delete project → all chats, Drive folders, and
     PG rows gone.
  7. Truncate PG `memory_chunks` manually → `POST /memory/rebuild` restores retrieval
     from Drive files alone.
- Update `workspace/current_state.md` + `workspace/status/dev_log.md` (absolute rule #6).

---

## 6. Suggested step order & sizing

M.1 → M.2 → M.3 → M.4 ship isolation + in-chat RAG and are independently verifiable
(standalone chats fully working before projects exist). M.5 → M.6 add projects on top.
M.5 shrank substantially in v3 (each move = one Drive call + one SQL update, symmetric;
cascade delete = recursive folder delete + one SQL delete). M.6 is now the biggest step
(largest frontend diff since PERF-2). Each step = one `build-step` skill invocation.

## 7. Risks

- [Certain] **Prod migration is manual** (initialized volume) — must be an explicit
  deploy step or prod retrieval silently breaks against missing SQL functions.
- [Certain] **Cascade delete is destructive by design** — the confirm dialog is the only
  guard; there is no undo and no trash. Worth stating in the dialog that Drive's own
  trash *may* allow manual recovery of message files, but PG chunks are gone.
- [Likely] **jsonl full-rewrite growth is now per-chat** (bounded; same class as
  `messages.jsonl`'s existing limitation). A single very long chat is the remaining
  worst case; shard-by-count is the escape hatch, deferred.
- [Likely] **BYOK embed quota**: per-turn chunk embedding multiplies embed calls vs
  today's one-per-summary. Fail-soft (chat never blocks on indexing), but Gemini
  free-tier limits may throttle index freshness.
- [Certain] **Cold-start UX**: with the global tier dropped, no chat knows anything
  about the user at start — accepted deliberately (decision #4); revisit only as a new
  plan if it stings.
- [Likely] **Move-out un-shares chunks, not absorbed knowledge**: replies other chats
  wrote while a chat was shared remain in those chats (and in their indexed chunks).
  Stated in the remove-from-project dialog; not fixable by any data operation.
- [Guessing] ivfflat `lists=10` fine at current scale; revisit / switch to HNSW past
  ~10k chunks per user.

## 8. Explicitly out of scope (documented deferrals)

- Uploaded documents (`doc_id`) scoping — uploads stay global in `PAWN/uploads/` for
  Phase M; document indexing/scoping is handled by the follow-on
  `plan_chat_agent_refinement.md` (the schema's `kind`/`doc_id` columns are
  pre-provisioned for it here to avoid a second migration).
- Project-level rolling summary (summary-of-summaries for whole-project context).
- Per-chat "incognito" (no-indexing) toggle.
- Chunk browser UI (view/edit individual memories).
- Re-introduction of any global/user-facts tier.

## 9. Open items

None. All decisions locked with the user 2026-07-13 (including migration mode:
automatic, see M.2). Any deviation an implementer believes necessary must go back to
the user first.
