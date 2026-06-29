# PAWN — Current State

Last updated: 2026-06-29
Active step: Phase W CODE COMPLETE (W.0–W.3) — live-verify warm SDXL + FLUX sessions, then merge imageLab → dev. Scoped per-session JWT deferred (mandatory before multi-user). Plans: `workspace/plan/plan_v5_warm_session.md`, `plan_v6_sdxl_warm_session.md`.
Phase: imageLab branch — Phase W (warm/persistent Kaggle sessions + durable job tracking). Targets the top deferred item: FLUX ~820s/image. Milestone A.1 (multi-model SDXL/FLUX) is live; Phase MU code complete on dev/main.

> **Phase W goal:** keep one Kaggle container warm so repeat images are fast (user-set timer + image
> cap), via a Supabase job-queue rendezvous; and make every generation a durable, server-tracked job
> shown in a Generations monitor panel — which also fixes the reported double-submit / lost-result
> bug (refresh/tab-switch loses the in-flight result and re-enables the button). Image Lab only.

---

## What's Built

- Step 1: repo directory structure — `backend/app/`, `backend/tests/`, `frontend/src/`, `.gitignore`, `.dockerignore`, `secrets/.gitkeep`
- Step 2: `.claude/` config — CLAUDE.md, AGENTS.md, rules (4), agents (5), skills/build-step, settings.json with hooks
- Step 2.5: Docker scaffolding — `docker-compose.yml`, `constants.py`, `config.py`, secrets-as-files pattern, `backend/Dockerfile`, `backend/requirements.txt`, `frontend/Dockerfile`, 5 `secrets/*.example` files
- Step 3: Static chat UI — React + Vite 8 + TypeScript + Tailwind v4; `ChatWindow`, `MessageInput`, `Message` components; `types.ts`; messages echo locally; `npm run build` passes clean
- Step 4: FastAPI backend — `main.py` with full middleware stack (GZip, Timeout, SecurityHeaders, CORS), `exceptions.py` (ProviderError, NoEndpointError + handlers), `middleware/security.py`, `middleware/timeout.py`; `GET /health` → `{"status":"ok"}`; 2 tests passing
- Step 5: Frontend ↔ backend connected — `src/api/client.ts` with `healthCheck()` (VITE_API_URL, res.ok check), `App.tsx` calls it on mount with `.then(console.log).catch(console.error)`; `.env` gitignored; `npm run build` passes
- Step 6: First real AI response — Gemini 2.5 streaming and `llm_core.py` integration.
- Step 7: Typed SSE events — `backend/app/events.py` (7 builder functions: token, done, error, provider_switch, step, memory_hit, model_call); `routes/chat.py` uses events module, emits typed JSON, adds `X-Accel-Buffering: no` header; `frontend/src/api/client.ts` refactored to `StreamChatCallbacks` object with `switch(type)` dispatch; 6 tests passing
- Step 8: Conversation history — Backend forwards full chat history array to upstream models; verified with history routing tests.
- Step 9: Multi-provider support — `backend/app/core/normalize.py` handles model/provider normalization. Added support for Groq and Cerebras.
- Step 10: Model switcher UI — Grouped provider/model switcher component integrated in React frontend.
- Step 11: Document upload — `backend/app/routes/upload.py` accepts PDF/TXT files, extracts text via `pdfplumber`, and stores it in-memory to inject as system message context in `/chat`. Added attachment UI in the input field.
- Step 12: Multi-chat persistence — Built disk-based conversation serialization (`meta.json` + append-only `messages.jsonl`), REST backend CRUD endpoints, auto-titling background tasks, and a dual-pane layout in React featuring inline renaming and thread deletion.
- Step 13: Complete typed SSE events — Wired `onStep`, `onMemoryHit`, `onModelCall`, and `onProviderSwitch` callbacks in `App.tsx` and updated `types.ts` message interfaces to store active trace sequences dynamically.
- Step 14: Per-chat memory summaries — Built context memory window truncation (saving last 10 messages only in active upstream calls), system prompt prepending of rolling context summaries, and enqueued `summarize_conversation_task` on threshold triggers.
- Step 15: RAG over memory — Integrated hybrid vector-keyword retrieval with `sqlite-vec` (sqlite database with virtual `vec0` + standard metadata table + `FTS5` table + triggers). Linked embeddings to Gemini's `text-embedding-004` (Ollama fallback). Wired retrieval and SSE memory_hit event streams into `/chat`.
- Step 16: LangGraph agent — Replaced single-shot flow with a 5-node StateGraph (load_context, agent, search_memory, ask_model, final). Uses ReAct JSON parser and capability-level purpose routing. Built collapsible frontend TracePanel showing steps, memory hits, and model calls dynamically.
- Step R1: Registry foundation — Created Pydantic ModelEntry and EndpointEntry schemas, database files models.json and endpoints.json seeding, loaded them via loaders module and returned catalogue dynamically on GET /registry/models. Added HuggingFace, GitHub Models, and OpenRouter secret keys.
- Step R2: Rate limiter — Implemented in-memory EndpointRateLimiter tracking rolling RPM/TPM usage, 90% soft-wall blocks, cooldown durations, and dead-host detection.
- Step R3: Resolver + normalize contract change — Implemented Resolver picking optimal active endpoints, simplified normalize.chat_stream signature to accept canonical model_id, routed Agent graph nodes using capability routing, and added provider mapping fallbacks for backward compatibility.
- Step R4: Frontend wiring — Integrated dynamic models dropdown from GET /registry/models, custom animated failover notices inline in chat, and provider badge indicators under assistant message bubbles.
- Hotfix: Port/CORS configuration — `docker-compose.yml` pinned backend to `8001:8000` and frontend to `5174:5173` (range bindings caused backend to land on port 8001 while `VITE_API_URL` still pointed to 8000, a different host service). `VITE_API_URL` updated to `http://localhost:8001`. CORS `allow_origins` extended to include `http://localhost:5174`. `frontend/.env` created for local dev.
- Step R5: UI visual overhaul + LAN access — CSS variable theme system (`@theme`/`:root`/`.dark`) with FOUC-prevention blocking script in `index.html`; `InteractiveGridBackground` animated canvas (184 lines); floating pill header islands with dark mode toggle; top gradient overlays trimmed to `h-16 via-theme-bg/25`; floating bottom input; `ChatWindow` smart scroll; `TracePanel.tsx` deleted — trace logic absorbed into `Message.tsx` as unified metadata row (provider left, "Agent Execution N steps" toggle right) with inline step/memory/model_call cards; `react-markdown` for assistant responses; collapsible long user messages; `MessageInput` auto-resize pill→card morph; `Sidebar` mini-sidebar `w-12`, click-to-expand column, fixed-width flicker-free transition, profile avatar, neutral delete colors, no close-on-thread-switch; registry `ModelResponse` extended with `providers` field; LAN IP `10.95.144.153` added to CORS + `VITE_API_URL`.

### Phase MU — Multi-User / Auth / BYOK / Drive (all code steps complete; awaiting manual Supabase/OAuth setup)

- MA-1: Supabase client (`db/supabase_client.py`) + AES-256-GCM crypto (`core/crypto.py`); 6 new secrets in `config.py`, `docker-compose.yml`, `secrets/*.example`; `requirements.txt` adds supabase, cryptography, google-auth-oauthlib, google-api-python-client, PyJWT.
- MA-2: Google OAuth2 — `core/jwt_utils.py` (HS256, 7-day), `routes/auth.py` (login/callback/me/logout). Callback upserts user, stores AES-GCM-encrypted Drive tokens, redirects to frontend with JWT.
- MA-3: `middleware/auth.py` (Bearer JWT → `request.state.user_id`; public `/health` `/auth/*`); storage scoped by user_id; LangGraph thread_id namespaced `{user_id}:{conv_id}`; `tests/conftest.py` bypass_auth fixture.
- MA-4: Frontend auth — `contexts/AuthContext.tsx`, `pages/LoginPage.tsx`, `App.tsx` AuthGate/AuthProvider, `client.ts` Bearer headers + 401 auto-reload; 429 rate-limit countdown banner; `events.rate_limit_event` + error `code` field.
- DD-1/2/3: Google Drive storage — `storage/drive.py` (DriveStorage), `core/drive_factory.py` (exception-safe `get_drive_for_user` → None → local fallback), `storage/conversations_drive.py`, `storage/documents_drive.py`. Routes (`conversations.py`, `upload.py`, `chat.py`) + `summarize.py` use Drive when available, else local filesystem.
- SM-1: Memory → Supabase pgvector — `memory/index.py` add_chunk → Supabase insert; `memory/retrieve.py` pgvector + FTS via RPC (`match_memory_chunks`/`search_memory_chunks`) with RRF fusion; AgentState.user_id threaded through graph + chat; `supabase/schema.sql`; removed `sqlite-vec`.
- BK-1: BYOK — `core/key_store.py` (AES-GCM encrypt, exception-safe reads), `routes/keys.py` (GET/PUT/DELETE; key values never returned).
- BK-2: `resolver.pick(model_id, user_id=None)` prefers user BYOK key over shared secret (keyed endpoints first, falls back to all if none keyed); `normalize.chat_stream(..., user_id=None)`; graph nodes + chat.py thread user_id.
- BK-3: `components/ApiKeysSection.tsx` (per-provider BYOK manage) integrated into `SettingsPage.tsx`; Profile shows real email + Sign out; Sidebar shows real email.
- BK-4: BYOK-only key resolution — `resolver` no longer falls back to shared `secrets/*` provider keys; `pick()` returns only endpoints with the user's BYOK key and raises a clear "configure your key in Settings" error otherwise. Embeddings (`memory/embed.py`) use the user's `google` BYOK key (`user_id` threaded through `retrieve`/`summarize`). Shared provider secret files retained but unused (deletable later).

### Phase MU — Drive-latency perf hardening (2026-06-28)

- PERF-1: Stop blocking the event loop — all synchronous Drive (`googleapiclient`) + Supabase (`supabase-py`) calls moved off the async loop via `run_in_threadpool` / `asyncio.to_thread` across `chat.py`, `conversations.py`, `upload.py`, `memory/summarize.py`, `memory/retrieve.py`. `storage/drive.py` gains a 20 s socket timeout (`AuthorizedHttp` + `httplib2`), a re-entrant lock (the instance is now shared), and a file-ID cache so reads go by ID (`get_media`, strongly consistent) instead of eventually-consistent name queries. `core/drive_factory.py` caches `DriveStorage` per user (TTL + `evict_user`, evicted on Drive re-link). `core/key_store.py` caches decrypted keys + `prefetch()` (warmed once per chat off-loop).
- PERF-2: Instant conversation UX (optimistic UI + client cache + fail-proof sync) — the client is now the source of truth.
  - Client-owned conversation UUIDs (`crypto.randomUUID`); backend `POST /conversations` accepts an `id` (idempotent `_create`), and `/chat` lazy-creates the conversation when missing instead of 404 (so the first message always materializes it).
  - New frontend store layer: `src/store/conversationCache.ts` (localStorage list+messages cache, debounced save, LRU + ~4 MB cap, corruption-safe, `mergeServerMeta` reconciliation), `src/store/syncQueue.ts` (persisted retry queue: create/rename/delete with backoff, 404-as-success, drains on `online`, survives reloads), `src/store/useConversationStore.ts` (single owner of list/messages/active selection), `src/store/ids.ts`.
  - `App.tsx` rewired to the store: new-chat/switch/delete/rename are instant and optimistic; messages are keyed by conversation (a stream writes to its captured conv even after switching away); the post-send full-list refetch is replaced by a local `commitTurn` + one quiet, debounced title-only merge (fixes glitchy/disappearing messages). `Sidebar.tsx` shows pending-sync dots + an offline banner.
- PERF-2a: Draft "New Chat" — clicking New Chat opens a frontend-only draft (welcome page, no sidebar row); nothing is created on Drive/Supabase/local and no sync op is enqueued until the first message is sent (`promoteDraft` + the chat route's lazy-create materialize it). At most one draft → no duplicate/empty chats. See `workspace/decisions/draft_new_chat.md`.

### imageLab — Milestone A.0: Kaggle SDXL image generation (2026-06-28)

- Image-gen pipeline working end-to-end: prompt → push template notebook to the user's Kaggle account → SDXL run on a **T4 GPU** → `out.png` fetched and returned as base64 (`core/generate.py`, `core/kaggle.py`, `routes/generate.py`, `kaggle_templates/image_gen/notebook.ipynb`, `components/ImageLabPage.tsx`). Verified live (~127s/image).
- **T4 fix:** the push body must send the GPU type as `machineShape` (not `accelerator`, which Kaggle ignores → default P100). Valid values: `NvidiaTeslaT4`, `NvidiaTeslaP100`, `Tpu1VmV38`.
- **Deploy auto-queue:** since a Kaggle push always starts a run, the deploy warmup leaves the slug busy; `run_kernel` now waits for it to free up (`_wait_until_idle`, bounded by `KAGGLE_BUSY_WAIT_TIMEOUT_SECONDS = 300`) instead of erroring "Kaggle is busy".

### imageLab — Milestone A.1: multi-model switch + FLUX.1-schnell LIVE (2026-06-29)

- One registry (`core/image_models.py`) drives SDXL + FLUX through the same `generate_image(user_id, prompt, model)` / `connect_kaggle(user_id, model)` path; model id threaded UI → `client.ts` → route → dispatch. Per-`(user, model)` lock keeps models independent. Unknown model → 400.
- **FLUX.1-schnell verified live** — prompt → image via `kaggle:harshaldodke7/pawn-image-flux` in **~820s**. Notebook `image_flux/`: bf16, `device_map="balanced"` across 2× T4, VAE tiling, 4 steps / guidance 0 / 1024², 900s timeout.
- **Bring-up bugs fixed (2026-06-29):**
  1. **Kaggle title↔slug invariant** — Kaggle derives a notebook's slug from its title; FLUX's title slugified to `pawn-image-flux-1-schnell` ≠ our `pawn-image-flux` slug → generate pushes 409'd `"title already in use"` forever, no run started. `_kernel_title` now derives the title from the slug (SDXL only worked by coincidence). Regression test guards all models.
  2. **Non-blocking deploy** — `deploy_kernel` no longer waits 300s on a busy slug (that blocked `/generate/connect` → 502 and starved the threadpool, coupling SDXL ↔ FLUX). Single push; HTTP 409 = already deployed.
  3. **Warmup skips heavy install** — FLUX cell-1 short-circuits on `prompt == "warmup"` so deploy is near-instant and doesn't hold the slug busy.
  4. **Persisted deploy state + per-model UI isolation** — deploy state survives refresh (localStorage); connector/generator keyed per model id so a running FLUX no longer disables SDXL's Generate button.
- **Known perf issue (deferred, next focus):** ~820s/image — every push spins a fresh Kaggle container, so `pip install` + 34 GB dataset mount + 12B model load run on **every** generate (4-step inference itself is fast). Optimization not yet chosen (warm/persistent kernel, pre-baked deps, weight caching, kept-alive session).

### imageLab — Phase W / W.0: persistent Kaggle loop proof (CPU echo) + Supabase rendezvous (2026-06-29)

- **Proves the load-bearing warm-session assumption** with no GPU/model: a batch-pushed Kaggle kernel runs a long-lived internet loop and rendezvous with PAWN through Supabase. `supabase/schema.sql` gains `image_sessions` + `image_jobs`; `kaggle_templates/session_poc/notebook.ipynb` is a CPU echo kernel (PATCH `ready` → loop: heartbeat, echo any pending job's prompt into `image_b64`, honor stop/timer/cap, exit).
- `core/image_session.py`: `start_session` (evict prior live → insert row → inject **public anon key** + url payload → non-blocking `kaggle.deploy_kernel`, CPU/internet/no-dataset; fails early 412 if Supabase unconfigured), `get_session_status` (alive = status + fresh heartbeat + before expiry), `stop_session` (cooperative), `submit_session_job` (alive-guarded queued row), `get_job`. Blocking calls off-loaded via `run_in_threadpool`.
- Routes (`routes/generate.py`): `POST /generate/session/start|job|stop`, `GET /generate/session/status`, `GET /generate/job/{id}` (session start reuses the per-`(user,model)` lock).
- New `supabase_anon_key` secret (PUBLIC) via `config.read_secret` + docker-compose `secrets:` + committed `.example`; **the Supabase service key is never injected into the notebook** (verified by test). Constants: poll 3s / heartbeat-stale 30s / max-duration 120 min.
- Frontend: `client.ts` session/job helpers (typed `SessionStatus`/`JobResult`); minimal `components/SessionPocPanel.tsx` (duration/cap picker, live countdown, submit echo job + poll, Stop) under the active model in `ImageLabPage`.
- **Security/review:** security-auditor + code-reviewer PASS (0 critical). **Deferred to W.1 (documented):** RLS policies + scoped per-session JWT (RLS off for the single-user trial → anon key has full table access; `session_token` is inert until then).

### imageLab — Phase W / W.1: warm FLUX serve-loop + unified durable job layer (2026-06-29)

- **Warm FLUX session**: `kaggle_templates/image_flux_session/notebook.ipynb` loads FLUX once (bf16, `device_map="balanced"` across 2× T4, VAE tiling), PATCHes `status='ready'`, then serves a Supabase work-loop — fast repeat images while warm. Session manager is now **registry-driven**: `ImageModel` gains `session_template`/`session_slug`/`session_gpu` (FLUX→real GPU serve-loop `pawn-flux-session`; SDXL→cheap CPU echo POC). `extend_session` (capped) added; routes `POST /generate/session/extend`.
- **Unified durable job layer (the lost-result / double-submit bug fix)**: `POST /generate {image}` is now **non-blocking** → `create_cold_job` (de-duped per `(user, model)`: a queued/running job returns the same id, no duplicate) → returns `{job_id, status:"queued"}`; a **GC-safe** fire-and-forget worker (`_spawn_bg` holds a strong task ref) runs `run_cold_job` behind the per-`(user,model)` lock (`generate.generate_image` round-trip → writes result onto the row, never raises). `GET /generate/jobs` (metadata only, no image bytes) + `reap_stale_jobs` (cold job stuck `running` past 20 min → `error`). Constants: `IMAGE_JOB_POLL_INTERVAL_SECONDS`, `COLD_JOB_MAX_WALLCLOCK_SECONDS`.
- Frontend (minimal for W.1; full panel is W.2): `runGenerate` returns `{job_id}`; `runKaggleImage` now **submits + polls `getJob`** so cold Generate keeps working on the new contract; `extendSession`/`listJobs` helpers; `JobResult` gains `done_at`/`has_image`/`session_id`. `SessionPocPanel` renders a **PNG for FLUX**, echo text for SDXL.
- **Review:** code-reviewer PASS (fixed a CRITICAL — `asyncio.create_task` kept only a weak ref → a GC mid-run could drop the worker; now strong-ref'd via `_spawn_bg`); security-auditor PASS (service key never injected; cold-job error truncated to 300 chars).
- **Deferred (documented):** `supabase_jwt_secret` + scoped per-session JWT — Supabase's new `sb_publishable_*` platform deprecates legacy HS256-secret minting, so the **permissive-anon RLS policy (W.0) is kept for the single-user trial**; the scoped JWT is **mandatory before multi-user**. A real SDXL serve-loop is a follow-up.

### imageLab — Phase W / W.2: Image Lab UI (session controls + Generations monitor) (2026-06-29)

- **Job-driven generator** (`components/ImageLabPage.tsx` `ImageGenerator`): submit → poll `getJob` → inline render. **Server-derived button state** — the parent lifts a shared `listJobs` poll (all models) and disables Generate while that model has a `queued`/`running` job, so a refresh or second tab can't fire a duplicate (a local `submitting` flag also closes the click→response window). Generate routes to `submitSessionJob` when a warm session is live (fast), else cold `runGenerate`.
- **`components/GenerationsPanel.tsx`** (new): collapsible monitor of every job across models/sessions, newest first — model badge, prompt, status chip (spinner while running), relative time; done image jobs lazily fetch their PNG via `getJob` for a thumbnail + View lightbox + Download. Server-backed → results survive refresh/tab-switch (a navigated-away result reappears here — the lost-result bug, now visibly fixed).
- **`components/SessionBar.tsx`** (new): warm-session lifecycle for a model — duration (30/60/120) + optional image cap, Start, live countdown, **Extend +30**, **Stop**, "session ended" CTA; re-attaches to a live session on mount via `getSessionStatus`. Reports the live session up to the generator. `SessionPocPanel` (W.0/W.1 stand-in) deleted.
- **Review:** code-reviewer PASS (0 critical). WARN fixes applied: double-submit guard (`submitting`), gated the 1s countdown ticker, mime-derived download filename. Deferred (documented): frontend unit tests (the project has none — its gate is `npm run build`); GenerationsPanel lazy-image fan-out is bounded by the 30-job list cap.

Test/build status: **132 backend tests passing**; frontend `npm run build` passes clean. **Phase W is code-complete (W.0/W.1/W.2).** Pending: live W.1/W.2 end-to-end (warm FLUX first image ~10 min then seconds; refresh-mid-generate re-attach), then merge imageLab → dev. W.0 loop already live-verified. Manual browser verification of the optimistic + draft flow under slow Drive still pending.

---

## What's Working

- [x] Docker stack running (validated compose configuration)
- [x] Backend health check
- [x] Frontend serving
- [x] Gemini streaming
- [x] Cerebras streaming
- [x] Model switcher
- [x] Document upload (Basic RAG context injection)
- [x] Conversation persistence
- [x] Memory RAG
- [x] LangGraph agent
- [x] Rate-limit failover
- [x] Google OAuth2 login + JWT sessions (code complete; needs OAuth credentials)
- [x] Auth middleware + per-user data scoping
- [x] Google Drive storage (code complete; needs Drive-linked login)
- [x] AES-256-GCM encryption (Drive tokens + BYOK keys)
- [x] Memory → Supabase pgvector (code complete; needs Supabase schema run)
- [x] BYOK per-user keys + settings UI
- [x] 429 rate-limit countdown UI
- [x] End-to-end verified live — OAuth login + Drive-backed conversations + BYOK LLM reply (2026-06-27)
- [x] Kaggle SDXL image generation (imageLab, Milestone A.0) — T4 GPU, deploy auto-queue; verified live (2026-06-28)
- [x] Kaggle FLUX.1-schnell image generation (imageLab, Milestone A.1) — 2× T4 bf16 shard, model-switch UI; verified live ~820s/image (2026-06-29). Perf optimization deferred.
- [x] Warm-session loop proof (imageLab, Phase W / W.0) — CPU echo kernel + Supabase rendezvous; **LIVE-VERIFIED 2026-06-29** (kernel reached Warm, live countdown + heartbeat, 2 echo jobs round-tripped). The persistent-loop assumption is proven. Note: new sb_publishable_* keys enforce RLS → permissive anon policy added on the two tables.
- [x] Warm FLUX serve-loop + durable job layer (imageLab, Phase W / W.1) — non-blocking job-tracked generate (de-dup, GC-safe worker), `extend_session`, `GET /generate/jobs`, FLUX persistent notebook; 132 tests green (2026-06-29). Live warm-FLUX run pending. Scoped per-session JWT deferred (mandatory before multi-user).
- [x] Image Lab UI (imageLab, Phase W / W.2) — job-driven generator with server-derived button state (no duplicate submit, survives refresh), `GenerationsPanel` monitor (thumbnails/lightbox/download), `SessionBar` (countdown/Extend/Stop); `npm run build` clean (2026-06-29). Live end-to-end verification pending.
- [x] Real SDXL warm serve-loop (imageLab, Phase W / W.3) — SDXL warm sessions now generate images (load once via `AutoPipelineForText2Image` → serve loop → PNG, `via kaggle:sdxl-session`) instead of echo text; registry repointed to `image_sdxl_session` notebook (GPU, slug `pawn-sdxl-session`); 134 tests green (2026-06-29). Both SDXL + FLUX warm sessions are real now. Live verify pending.

---

## Key File Locations

- Backend entry: `backend/app/main.py`
- Provider routing: `backend/app/core/normalize.py`
- LLM core: `backend/app/core/llm_core.py`
- SSE events: `backend/app/events.py`
- Frontend API client: `frontend/src/api/client.ts`
- Model Switcher UI: `frontend/src/components/ModelSwitcher.tsx`
- App layout: `frontend/src/App.tsx`
- Constants (all paths): `backend/app/constants.py`
- Config (secrets): `backend/app/config.py`

---

## Known Issues / Deferred Items

- **Manual setup required before live use** (see build_tracker.md):
  1. Create Supabase free project; run `supabase/schema.sql`; fill `secrets/supabase_url` + `secrets/supabase_service_key`.
  2. Create Google Cloud OAuth2 Web client; redirect URI `http://localhost:8001/auth/callback`; enable Drive API; fill `secrets/google_client_id` + `secrets/google_client_secret`.
  3. `encryption_secret` + `jwt_secret` already generated (MA-1).
- Until Supabase is configured, `get_drive_for_user()` returns None (→ local filesystem storage) and memory retrieve/add gracefully no-op. Tests rely on this fallback.
- Drive `append_messages` rewrites the whole `messages.jsonl` per call (Drive has no partial append) — fine at normal scale, inefficient for very long chats.
- `memory_chunks` ivfflat index uses `lists = 10` — tune up as data grows.
- Client conversation cache is per-browser. Cross-device divergence is reconciled only via `mergeServerMeta` on next load (last-write-wins on title); genuine multi-device editing is not synced live.
- Reasoning `trace[]` is not persisted to the client cache (final message text only) — traces disappear on reload.
- localStorage cache keeps message arrays for the 30 most-recent conversations (LRU, ~4 MB cap); older conversations re-fetch their messages from Drive on next open.
- **imageLab:** `machineShape: NvidiaTeslaT4` always provisions a **2× T4 (2×16 GB)** box — treated as a hard rule (the FLUX A.1 plan shards across both cards). The earlier note that dual-T4 was "unreachable" (issue #821) is retired. SDXL image quality is not yet tuned (steps/guidance/resolution defaults). First Generate after a deploy holds the HTTP request open through the warmup wait (per-user lock already serializes this).
- **imageLab FLUX perf (top deferred item):** ~820s/image. Each generate spins a fresh Kaggle container → `pip install` + 34 GB dataset mount + 12B model load repeat every run (4-step inference is fast). No optimization chosen yet — candidates: warm/persistent kernel, pre-baked deps in the dataset image, weight caching, kept-alive session. The Generate button's "~1-2 min" label is stale for FLUX (~14 min).
- **imageLab orphan kernel:** the old mismatched FLUX title created a stray `pawn-image-flux-1-schnell` notebook on Kaggle (now unused — title is derived from the slug). Safe to delete manually.

---

## Agents to Update This File

After every completed step, update:
1. "Last updated" date
2. "Active step" to the next step
3. Add new items to "What's Built"
4. Check off items in "What's Working"
5. Add any deferred issues
