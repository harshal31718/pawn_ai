# Phase F-11 — Chat Input/Output Formats (Attach Image + Forced-SDXL Session)

**Status:** DONE 2026-07-16 (backend + frontend both built and live-verified
against the real stack; one infra blocker and one pre-existing frontend gap
found along the way, both documented in §7 below — neither blocks this
plan's own code). **Branch:** `dev`. **Folder:** `workspace/plan/chat/`
**Date:** 2026-07-16, from the user's request. Framed as: what formats can chat
**take in** (text, PDF, and now image) and what formats it can **give out**
(text, and image generation — made reliable and cross-platform this pass).

## 1. Why this plan exists

Two related, user-requested changes to chat's I/O surface:

1. **Input:** the composer's single "attach PDF" button becomes a `+` icon
   that opens a small menu with two choices — **Attach PDF** (unchanged) and
   **Attach image** (new — send the image to a vision-capable model along
   with the user's text, and reply from what it sees; not RAG-indexed, not
   image generation).
2. **Output:** chat-triggered image generation (F-1's `generate_image` tool,
   `implemented_phases/phase_13_chat_feature_fixes.md`) is tightened:
   **always SDXL, always a 30-minute warm session** (never a cold one-shot,
   never model-hallucinated), and that session must be the same session
   Image Lab shows — one shared source of truth, not two.

This also closes the live bug found this session: a fallback model
(`deepseek-r1` via HuggingFace) emitted a malformed textual tool-call instead
of a real one, and the LLM was free to pick `flux` instead of `sdxl` — both
symptoms of `generate_image` giving the model too much room to fail.

## 2. Current state (verified against code, 2026-07-16)

### Input (PDF attach — unchanged reference)
- `MessageInput.tsx:165-188` — a plain upload button (paperclip-style SVG,
  `id="upload-button"`) triggers a hidden `<input type="file"
  accept=".pdf,.txt">` (`:100-107`). Props: `onUpload?: (file: File) => void`,
  `isUploading?`, `attachment?: {name: string} | null`, `onRemoveAttachment?`.
- `ChatPage.tsx`'s `handleUpload` (`:423-441`): lazily creates/promotes a
  draft conversation if needed, calls `uploadDoc(file, convId)`, then
  `setAttachedDoc({id, name})`.
- Backend `routes/upload.py` (118 lines): accepts only `.pdf`/`.txt` by
  content-type/extension (400 otherwise, `:52-59`); text extracted via
  `pdfplumber` off-thread, stored via `documents_drive.store_doc`, indexed
  in the background (`index_document_task`) into the conversation's RAG
  scope. Retrieved later only via the `doc_search` agent tool — **this
  entire pipeline stays exactly as-is.**
- No `+` icon exists yet in `components/icons/index.tsx` (11 icons today,
  none named Plus). `KebabMenu.tsx` (this session's portal rewrite) is the
  right dropdown primitive to reuse — but it positions itself
  below-right of the trigger with no viewport flip (`top: rect.bottom + 4`,
  unconditional). A composer button sits near the bottom of the viewport,
  so reusing `KebabMenu` unmodified would render the menu partly/fully
  off-screen — it needs the same up/down-flip logic `ModelSwitcher.tsx`
  gained this session after an identical live bug.

### Input (image attach — does not exist yet)
- No multimodal support anywhere in the LLM plumbing: `grep` for
  `image_url|multimodal` across `backend/app` hits only `resolver.py`
  (`require_vision` filter) and `registry/schemas.py` (`supports_vision`
  flag). `llm_core.py`/`normalize.py`'s `chat_stream`/`chat_complete`/
  `chat_stream_with_tools` all still build plain-string `content` only.
  This is the exact gap `plan_vision_prompt_enhancement.md` §2/§3.1
  already documents (currently scoped to imageLab's img2img case) — this
  plan reuses that gap analysis rather than re-deriving it, and is the
  second consumer of that same shared plumbing once it's built.
- **5 active vision-capable models today** (`supports_vision: true` in
  `data/registry/models.json`): `gemini-2.5-flash` (google),
  `gemini-2.5-flash-lite` (google), `llama-4-scout` (groq),
  `gemma-4-31b` (cerebras), `gemini-2.5-pro` (google). A real, usable pool
  spanning 3 providers — `resolver.pick_model_by_capability(level,
  require_vision=True)` already filters to these.

### Output (image generation — F-1, needs tightening)
- `agent/tools/generate_image.py` (70 lines): `GENERATE_IMAGE_PARAMETERS`'s
  `model` field is an **enum `["sdxl", "flux"]`**, optional — the LLM can
  and (per the live bug) does sometimes pick `flux` or malform the call
  entirely. `DEFAULT_IMAGE_MODEL` ("sdxl") is only the fallback when the
  arg is omitted, not a hard constraint.
- Warm-vs-cold decision (`:31-49`): checks `image_session.get_session_status`
  first; if alive → `submit_session_job` (warm); **else falls straight to
  `create_cold_job` + `spawn_cold_job_bg`** (a cold one-shot, no session at
  all). **There is no code path today that starts a NEW warm session from
  chat** — it only ever reuses an existing one or falls back to cold.
- **Cross-platform visibility is already automatic, confirmed — no Image
  Lab code changes needed for this plan:**
  - `image_session.start_session` (`:118-192`) is keyed purely by
    `(user_id, model)` in Postgres `image_sessions`, evicting any prior
    live session for that exact pair first (`:151-158`). No "started via
    chat" vs "started via Image Lab" distinction exists anywhere in the
    schema.
  - `ImageGenerator.tsx` (Image Lab's own UI) polls `getSessionStatus(model)`
    every 3s on mount — a chat-started `sdxl` session shows up there on the
    very next poll tick, with zero Image Lab-side changes.
  - `GET /generate/jobs?model=` returns every job for that model regardless
    of entry point — a chat-triggered generation's prompt + image appears
    in Image Lab's own job list identically, already.
  - Real decision this plan must make explicitly (not automatic):
    `start_session`'s `max_images` cap. imageLab's own UI lets a user set
    one; chat has no such input. **Default: uncapped (`None`)** — rely on
    the 30-minute timer alone to bound cost, simplest choice, matches
    "always 30 min" as the one stated constraint.
  - **User's requirement confirmed satisfied by this same mechanism (both
    directions):** (1) start a session in Image Lab, then trigger
    `generate_image` from chat → chat's `get_session_status(user_id,
    "sdxl")` check finds that same live session and queues onto it via
    `submit_session_job`, no new session started. (2) start a session from
    chat, then open Image Lab → `ImageGenerator.tsx`'s poll picks up the
    identical row on its next tick, session bar shows it running, and any
    further images queued from *either* surface land in the *same*
    `image_jobs` rows (`GET /generate/jobs?model=sdxl` returns all of them
    regardless of origin) — so the Generations tab/history is inherently
    one global queue per `(user_id, model)`, not two synced copies. Chat and
    Image Lab stay separate components with their own settings/UI (chat
    never gains Image Lab's param controls, Image Lab never gains chat's
    agent loop) — only the session/job *data* is shared, which it already
    is by construction (one Postgres table, no per-origin partitioning
    anywhere in the schema). No new sync code needed; this section is
    reconfirming the design, not proposing new plumbing.

### Related bug (found live this session, root-caused, folds into this plan)
- `deepseek-r1`'s active endpoint (`ep-deepseek-r1-huggingface`, provider
  `huggingface`, `router.huggingface.co/v1`) is registered `supports_tools:
  true`, but that inference route doesn't reliably turn DeepSeek-R1's own
  special tool-call tokens into a real structured `tool_calls` API field —
  it leaked out as raw visible text instead of triggering `generate_image`
  (see the live trace: `17 steps · 0 tool calls · 0 sources`, reply
  containing literal `<|tool_calls_begin|>...` text). This is a **registry
  data accuracy bug**, not a graph/dispatch bug.

## 3. Proposed design

### 3.1 Shared multimodal plumbing (prerequisite for the image-attach path)

Build `plan_vision_prompt_enhancement.md` §3.1 now, as the shared foundation
both this plan's "Attach image" Q&A and that plan's img2img enhancer will
use:
- `llm_core.chat_complete` (and `chat_stream`, needed here since replies
  stream) accept messages whose `content` is either a plain string
  (unchanged) or a list of OAI-style content parts (`text`/`image_url`) —
  passthrough only, no provider-specific translation (every provider here
  already speaks the OAI-compatible wire format).
- `normalize.chat_stream`/`chat_complete` — no signature change beyond what
  already exists; multimodal content just flows through `messages`.
- No new registry fields needed — `supports_vision` already exists.

### 3.2 Backend — "Attach image" turn (vision Q&A, not full agentic tool use)

Deliberately **not** routed through the full tool-calling orchestrator this
pass — classify/plan/execute all assume plain-string content today, and
threading multimodal through every node is bigger than this plan's scope.
Instead, an image-attached turn takes a **direct vision-answer path**,
structurally a sibling to `direct_answer_node`:

- `routes/chat.py`: when the request carries an attached image (new
  optional field, e.g. `image_b64`/`image_mime` on `ChatRequest`, mirroring
  how `init_image_b64` works in `routes/generate.py`), skip `classify_node`
  entirely and call a new `vision_answer_node` (or a branch inside
  `direct_answer_node` gated on "has image").
- Model pick: `resolver.pick_model_by_capability(ROLE_LEVELS["direct_answer"]
  or similar, require_vision=True, user_id=user_id)` — reuses the existing
  filter, no new resolver code.
- Build one multimodal user message: `content: [{"type": "text", "text":
  <user's prompt>}, {"type": "image_url", "image_url": {"url":
  "data:<mime>;base64,<...>"}}]`, prepended with the conversation's existing
  text history (unchanged, plain strings) so context isn't lost.
- Stream the reply exactly like `direct_answer_node` does today (same SSE
  `token` events); persist it as a normal assistant message.
- **Image bytes are NOT persisted to Drive/history** — used for this one
  completion call only, then discarded. Reloading the chat later shows the
  text exchange, not a re-viewable thumbnail. This is an explicit scope cut,
  not an oversight — flagged in §5 as an open question if the user wants a
  persisted thumbnail later (that needs its own storage design, closer to
  how `image_jobs.image_b64` works, and is meaningfully more work).
- Failure/no-vision-model-available: fall back to a plain `TOOL_ERROR`-style
  system message ("no vision-capable model available — configure a Google/
  Groq/Cerebras key") rather than silently dropping the image, mirroring
  the tool layer's own never-silently-fail convention.

### 3.3 Frontend — `+` icon composer menu

- New `PlusIcon` in `components/icons/index.tsx` (none exists today).
- `MessageInput.tsx`: replace the current visible upload button with the
  `+` icon; wire it to `KebabMenu` with two items:
  - **Attach PDF** — calls the existing `onUpload` handler, unchanged
    end-to-end (same hidden `<input accept=".pdf,.txt">`, same
    `uploadDoc`/`doc_search` pipeline).
  - **Attach image** — calls a new `onUploadImage?: (file: File) => void`
    prop, backed by a second hidden `<input accept="image/*">`, wired in
    `ChatPage.tsx` to a new `handleUploadImage` that stores the file
    client-side (not uploaded until Send, since there's no separate
    "attach now, ask later" step needed — the image only matters together
    with whatever the user types next) and sends it alongside the next
    `/chat` request as base64.
- **`KebabMenu.tsx` gets the same up/down viewport-flip + height-cap logic
  `ModelSwitcher.tsx` already has** (computed from the trigger's
  `getBoundingClientRect()` on open) — a real, shared fix, not
  composer-specific, since any future kebab near the bottom of a short
  viewport hits the identical problem.
- Attachment chip (`:118-141` today, doc-specific) gains an image variant —
  small thumbnail preview instead of a filename+file-icon row, with the
  same remove-attachment affordance.

### 3.4 Backend — `generate_image` forced-SDXL + forced-session rewrite

- `GENERATE_IMAGE_PARAMETERS`: **drop the `model` field entirely** — the
  tool schema only exposes `prompt`. The handler hardcodes `model = "sdxl"`,
  full stop. No LLM-controlled model choice, closing the exact hallucination
  bug found live.
- Warm/cold decision rewritten: check `get_session_status(user_id, "sdxl")`
  first as today; if alive (including `starting`/`installing`/
  `loading_model` — `submit_session_job` already queues correctly during
  those), `submit_session_job`. **If no session exists at all, call
  `image_session.start_session(user_id, "sdxl", duration_minutes=30,
  max_images=None)` first, then `submit_session_job` against the new
  session_id** — replacing the `create_cold_job`/`spawn_cold_job_bg` cold
  path entirely for this tool. Chat-triggered generation never runs cold
  again.
- Tool observation text updated to say a session was started/reused (e.g.
  "Started a 30-minute image session and queued your image (job_id=...)."),
  so the model's own follow-up prose reflects what actually happened.
- No Image Lab-side changes needed — §2's cross-platform-visibility
  analysis confirmed this is automatic via the shared `(user_id, model)`
  Postgres row and existing polling.

### 3.5 Registry fix — `deepseek-r1`'s HuggingFace endpoint

- `data/registry/models.json`: this is model-level `supports_tools`, but the
  actual defect is endpoint-specific (HuggingFace's router passthrough for
  this raw model, not the model itself — OpenRouter's `deepseek/deepseek-r1
  :free` endpoint is currently inactive so can't be verified either way).
  Given `EndpointEntry` has no per-endpoint tools-capability field today,
  the pragmatic fix is either (a) flip `deepseek-r1`'s model-level
  `supports_tools` to `false` (loses tool access for this model entirely,
  simplest, matches today's schema), or (b) add a new
  `EndpointEntry.supports_tools: bool = True` field so only the
  HuggingFace endpoint is excluded while a future working endpoint (e.g.
  OpenRouter's, once reactivated) could still serve tool-calling requests
  for this model. **Recommend (a) for this pass** — (b) is a real schema
  extension better scoped to a `registry-refresh` session that can verify
  every endpoint's actual tool-calling fidelity, not guessed here.

## 4. Tests (for the build-step session)

- `llm_core`/`normalize`: multimodal content-part passthrough (string vs.
  list `content`, both directions), one test per changed function.
- `vision_answer_node` (or equivalent): picks a vision-capable model,
  builds correct multimodal message shape, streams token events; no
  vision-capable model configured → graceful system-message fallback, not
  a crash.
- `generate_image.py`: `model` param removed from schema/handler (existing
  tests already assert `GENERATE_IMAGE_TOOL.parameters["required"] ==
  ["prompt"]` — extend to assert `"model"` is no longer in `properties`);
  no-session-exists path now calls `start_session(..., "sdxl", 30, None)`
  then `submit_session_job`, never `create_cold_job`; existing warm-session
  and dedup tests updated for the new call shape.
- Frontend: none currently exist for `KebabMenu`/`MessageInput`
  (no frontend test infra runs in this repo yet, confirmed absent this
  session) — rely on `tsc`/`build` + live Chrome verification, consistent
  with how F-9/F-10's UI work was gated this session.

## 5. Open questions before/while building

1. **Persisted image thumbnails on reload** — explicitly cut from this
   pass (§3.2); confirm that's acceptable, or it becomes its own follow-up
   needing real storage design (mirroring `image_jobs.image_b64`).
2. **Which `ROLE_LEVELS` entry the vision-answer path uses** — a new
   `vision_answer` role level, or reuse an existing one (`direct_answer`
   levels aren't vision-filtered today)? Needs a explicit level added to
   `constants.py` either way.
3. **Registry fix scope** — (a) blunt model-level `supports_tools: false`
   now, vs (b) a proper per-endpoint field for a future `registry-refresh`
   pass. Plan recommends (a) for now; confirm before building.

## 6. Suggested build order

1. §3.1 multimodal plumbing (prerequisite for everything in §3.2).
2. §3.5 registry fix (independent, smallest, unblocks nothing else but
   cheap and directly related to the bug that motivated this plan).
3. §3.4 `generate_image` forced-SDXL + forced-session rewrite (independent
   of §3.1/3.2, addresses the user's output-format ask directly).
4. §3.2 backend vision-answer path (needs §3.1).
5. §3.3 frontend `+`/kebab/attach-image composer UI (needs §3.2's new
   request field to actually send anywhere) + the `KebabMenu` viewport-flip
   fix (independent, can land anytime).

## 7. DONE (2026-07-16)

**§3.1 multimodal plumbing — turned out to be a non-change.** Checked
`llm_core.py`/`normalize.py` directly: every function (`chat_complete`,
`stream_llm`, `chat_stream_with_tools`) already treats `messages` opaquely,
forwarding whatever `content` shape it's given straight into the JSON
payload — no provider-specific translation, no type assumptions. A
multimodal `content: [{"type":"text",...},{"type":"image_url",...}]` list
already passes through cleanly with zero code changes. This closes the
prerequisite gap `plan_vision_prompt_enhancement.md` §2 originally
identified — it's now satisfied for both this plan's use case and that
plan's img2img enhancer, whenever it's picked up.

**§3.5 registry fix** — `deepseek-r1`'s `supports_tools` flipped to `false`
in both `data/registry/models.json` and `app/registry/seed.py`'s test
fixture (its only active endpoint, HuggingFace's router passthrough,
doesn't reliably turn its tool-call tokens into a real `tool_calls` field).

**§3.4 `generate_image` rewrite** — `GENERATE_IMAGE_PARAMETERS` now exposes
only `prompt`; the handler hardcodes `sdxl` and always ends up on a warm
session (`get_session_status` → reuse if alive, else
`start_session(user_id, "sdxl", 30, None)` → `submit_session_job`) — the old
`create_cold_job`/`spawn_cold_job_bg` cold-one-shot path is gone from this
tool entirely. 6 tests rewritten in `test_agent_tools_image.py`.

**§3.2 vision-answer path** — built as a branch inside `direct_answer_node`
rather than a new graph node: `classify_node` short-circuits to
light/no-agent the instant `state["has_image"]` is set (skips the
text-heuristic router entirely, since it assumes plain-string content), and
`direct_answer_node` then picks a vision-capable model
(`pick_model_by_capability(ROLE_LEVELS["vision_answer"]="balanced",
require_vision=True)`) and builds one fresh multimodal message (history
stays plain-string; only the latest user turn becomes
`[text, image_url]`) rather than mutating `state["messages"]` — so raw image
bytes never reach any other node and are never persisted. New
`ChatRequest.image_b64`/`image_mime` fields thread through
`routes/chat.py` → `AgentState`. No vision-capable model configured →
graceful apology reply, not a crash. 4 new tests in `test_agent.py`.

**§3.3 frontend composer UI** — new `PlusIcon`/`ImageIcon`; `KebabMenu.tsx`
gained `icon`/`buttonClassName` override props (so the composer's `+` button
can look like the toolbar's other buttons instead of the small "⋮" row
style) **and** the same up/down viewport-flip logic `ModelSwitcher.tsx`
already had, fixing a menu-renders-off-screen bug this same fix would
otherwise have introduced for a bottom-of-viewport trigger. `MessageInput.tsx`'s
old single upload button is now a `KebabMenu` with "Attach PDF" (unchanged)
and "Attach image" (new `onUploadImage` prop). `ChatPage.tsx`: image attach
is client-side only (no backend call at attach time — `FileReader` straight
to a data URI, held in state), captured and cleared the moment `handleSend`
fires (one-turn-only, unlike the doc attachment which lingers all
conversation since `doc_id` is otherwise inert) and threaded into
`streamChat`'s new optional `image` param.

**Real router gap found and fixed while live-testing this pass (not in the
original plan, found necessary to make generate_image usable at all):**
`core/router.py`'s heuristic classifier had no keyword trigger for image-
generation requests — "generate an image of X" is short, has no URL, no
heavy keyword, so it classified light+`needs_agent=False`, and
`direct_answer_node`'s fast path has **no tools bound at all**. Without a
fix, `generate_image` could never be invoked no matter how well everything
else worked. Added `_IMAGE_GEN_KEYWORDS` (mirrors the existing
`_TIME_SENSITIVE_KEYWORDS`/`has_search_key` pattern), gated on
`has_kaggle_creds` so it only forces agent routing when the tool would
actually be available. 2 new tests in `test_router.py`.

**Second live bug found and fixed after this doc was first written: closing-
synthesis hallucination.** Live-testing "its not working" (user report,
screenshot) showed a follow-up chat turn where `generate_image` was called
successfully but the model's own reply fabricated a fake image link — first
seen as a made-up `imgur.com` URL, then (after an initial fix attempt) as a
markdown `![image](sandbox:/mnt/data/...)` reference to a file that doesn't
exist. Root cause: nothing in `working_messages` tells the model it can't
see/link/embed the real generated image, so the very next model turn
"helpfully" invents one. Two fix attempts:
1. First attempt added a system nudge (`_IMAGE_GEN_SYNTHESIS_NUDGE`) but only
   ahead of the heavy-turn closing-synthesis call — missed the case where
   `generate_image` is invoked on a **light**-agentic turn (short prompt, no
   heavy keyword), where the model's own next loop iteration inside
   `execute_node`'s tool loop *is* the final user-facing answer, with no
   separate closing-synthesis call to gate.
2. Real fix: the nudge is now appended to `working_messages` immediately
   after the `generate_image` tool observation is recorded, inside the tool
   loop itself (`execute_node`, right after the "tool" role message is
   appended) — covers both the light-turn inline-continuation path and the
   heavy-turn closing-synthesis path with a single insertion point, since
   both read from the same `working_messages` list. The old heavy-only
   insertion (right before the closing-synthesis call) was removed as
   redundant. `_used_image_gen_tool` is kept (still exercised directly by
   `test_used_image_gen_tool_true_when_present`/`_false_when_absent`) even
   though `execute_node` itself no longer calls it.
Live-reverified after the fix: "generate an image of a dog playing fetch" in
a fresh chat now correctly replies "I'm generating the image now. It will
appear automatically in the chat once it's ready." — no fabricated URL,
markdown, or file path. Full backend suite green (475).

Full backend suite green (472); `tsc --noEmit` + `npm run build` clean.

**Live-verified end to end via Chrome, with one real infra blocker and one
real pre-existing frontend gap found along the way (both out of this plan's
scope, documented for the user):**
- Asking "can you generate an image of a person eating an apple" in a fresh
  chat correctly triggered `generate_image` (previously it silently didn't,
  per the router gap above), which started a real 30-minute SDXL session
  and queued a real job — confirmed via a direct API fetch of the persisted
  trace (`observation`: "Started a 30-minute SDXL image session and queued
  your image (job_id=...)").
- **Cross-platform sharing confirmed live, not just by code inspection:**
  the exact prompt from the chat-triggered job appeared in Image Lab's own
  Generations list under the SDXL model, with zero Image Lab-side changes.
- **Infra blocker (needs the user, not a code bug):** the actual image
  render failed — the real Kaggle kernel logged
  `NameResolutionError: ...trycloudflare.com` — the cloudflared tunnel
  behind `POSTGREST_PUBLIC_URL` has gone stale/rotated (quick tunnels get a
  new random subdomain on every restart). Needs the user to restart their
  tunnel and update the backend's `POSTGREST_PUBLIC_URL` if the subdomain
  changed, then retry.
- **Pre-existing frontend gap found (not caused by this plan, not fixed
  this pass):** `ImageJobChip`/the tool-call preview didn't render for the
  freshly-created chat above even after a true hard reload — traced to
  `useConversationStore`'s local cache being served instead of a fresh
  `fetchConversation()` fetch, for a chat created+completed within the same
  browser session. The cached copy was built from the live SSE trace
  (which never carries an `observation` field — that's only ever attached
  server-side in the persisted document), so it shows the tool-call args
  instead of the result on reload. Confirmed via a direct API fetch that
  the server's own persisted `observation` field is correct and complete —
  this is a client-side cache-precedence bug, would affect any tool call
  viewed again in the same session, not something specific to
  `generate_image`. Flagged as a follow-up, not fixed in this pass (out of
  F-11's stated scope).
