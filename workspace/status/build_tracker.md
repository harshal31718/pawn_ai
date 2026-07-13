# PAWN — Build Tracker

Source of truth for *what to build* is the relevant phase plan file in `workspace/plan/` or `workspace/implemented_phases/`.
This file tracks *where we are*. Update it after every step — mark `[x]` only when
tests pass and the step's demo works.

The Claude Code instance inside `/PAWN` uses this file to know what to build next.
Agents should read this before starting any work.

Legend: `[ ]` not started · `[~]` in progress · `[x]` done & verified

---

## Current Status

**Active phases (merged track):** Phase A — Chat Agent Refinement (tools, router, orchestrator, subagents) — **started 2026-07-13, A.1/A.2 in progress this session** — + Phase M — Memory Scoping (all coding done M.1–M.7, 2026-07-13; only M.7's live verification checklist remains, pending with the user) + Phase D — Production Deployment (D.8 fully complete, migrated to the permanent free-tier instance, `pawn-temp` terminated) + Plan: Drive-Mandatory Storage (Phases 1-4 all DONE) + imageLab perf/quality follow-ups (2026-07-05) + Phase 3 — WebCrypto Encryption (not started, deliberately deferred)
**Active step:** **Phase A — Chat Agent Refinement, A.1/A.2 (native tool calling + tool layer).** Plan refined and re-verified against as-built Phase M code 2026-07-13 (`workspace/plan/plan_chat_agent_refinement.md`), registered in this tracker, work started same day. Phase M done (2026-07-13) — memory scoping (standalone chats + projects + scoped RAG) shipped on `dev`; swapped the dead `text-embedding-004` embedding model for `gemini-embedding-2` (768-dim) while wrapping up M.6. M.7's live checklist (real Drive-linked stack + user) is the only open Phase M item — see the M.7 entry below. Prior: D.8 fully complete (2026-07-05). The retry loop succeeded 2026-07-04 (attempt 183); PAWN migrated data-preserving onto the new free-tier `pawn` instance (`144.24.119.184`), DuckDNS repointed, fresh TLS cert issued, `pawn-temp` (the paid bridge) terminated after user sign-off. One real bug found+fixed: `docker-compose.prod.yml`'s CPU limits assumed 2 vCPUs (true of `pawn-temp`'s x86 hyperthreaded core), broke on Ampere A1's 1 real vCPU — rescaled `1.5/1.0/0.5` → `0.6/0.3/0.1`. Full migration record in `workspace/status/dev_log.md`'s 2026-07-05 entry.

**Follow-up round (2026-07-05):** fixed three real imageLab issues found while auditing the "FLUX perf"/"SDXL quality" deferred items — SDXL's `/generate/connect` warmup was needlessly reinstalling pip deps every "Connect" click (FLUX's template already skipped this; SDXL's didn't — ~1-2 min wasted per connect, `generate.py`'s own comment already flagged it); FLUX's session + cold notebooks used a blanket `pip install -U` on every ephemeral session start (forces a full upgrade-resolve even when Kaggle's image already ships a compatible version) — replaced with a `diffusers>=0.30.0` floor (the version that added `FluxPipeline`) and no forced upgrade on the others; `AdvancedParams.tsx`'s inference-steps slider had one flat default (20) shared across models — undercuts SDXL's real default (30) and overshoots FLUX.1-schnell's (4) if a user enables the slider without moving it — now model-aware via `initialAdvanced(modelId)`. Confirmed via code reading that current_state.md's older "~820s/image, no optimization chosen" framing was stale — Phase W's warm-session mechanism already made every Generate click auto-start-or-reuse a session (`ImageGenerator.tsx`'s `handleGenerate`), so the only remaining cold-start cost is the one-time per-session model load, not a per-image cost. Orphaned Kaggle kernel `pawn-image-flux-1-schnell` cleanup: pending — needs the user's own Kaggle account access (BYOK credentials, not something this Claude Code session can decrypt/reach on its own).

Full `deployment.md` §7 verification checklist passed on `pawn-temp`: HTTPS health, no CSP violations, full Google OAuth round-trip (Drive-linked — the one path untestable locally), BYOK chat streaming, and a real Kaggle SDXL image generation through the PostgREST rendezvous. Enma re-verified healthy throughout (health endpoint + all 4 containers "Up (healthy)" both before and after every VM-side action).

**4 real bugs found and fixed during this first live deploy** (all now captured in `deployment.md` so the eventual migration doesn't repeat them):
1. Oracle's stock Ubuntu image's **host iptables only allows SSH (22)** for new connections by default — the OCI Security List permits 80/443, but the host itself still rejected everything else. Fixed with an explicit `iptables -I INPUT` rule + `netfilter-persistent save`.
2. `client_max_body_size` on the `/pgrst/` Nginx location defaulted to 1MB — the warm Kaggle kernel's PATCH write-back of a finished base64 image (routinely 1-3MB) was silently getting **413**'d, leaving every image-gen job stuck at "running" forever with no visible error. Fixed: `client_max_body_size 20m;`.
3. `get_session_status()` declared a warm session dead after only **300s (5 min)** in `starting`/`installing`/`loading_model`, even when the Kaggle kernel was still legitimately cold-starting (SDXL deps install + multi-GB weight download/load ran past 8 minutes live). Raised to a named constant `IMAGE_SESSION_STARTUP_TIMEOUT_SECONDS = 900`.
4. **CSP `img-src` gap**: `default-src 'self'` does not implicitly permit the `data:` scheme, and no `img-src` directive was set — every Image Lab thumbnail/lightbox (`<img src="data:image/...;base64,...">`) was silently blocked by the browser. Fixed in both `SecurityHeadersMiddleware` (backend-proxied routes) and the static frontend's own Nginx `location /` block (which doesn't inherit headers from proxied routes, so needs its own copy of the same policy — also missing the CSP/security headers entirely at first, fixed same pass).

**Also found and fixed:** `scripts/promote-to-main.sh` was silently dying before its final `git commit` on *every* real run (both actual promotions so far needed manual completion) — a `while read` loop reading from a pipe always exits 1 on EOF regardless of what it processed, and under `set -e` with no `|| true` guard that killed the script right after doc-stripping, every time. Fixed and verified against a throwaway clone.

`plan_drive_mandatory.md` Phases 1-4 all done (closed 2026-07-04 — code-reviewer + security-auditor gap closed, 4 WARN fixes applied, 152 tests green). Deployment plan simplified to prod-only (no VM staging; `dev` stays local-only, shares one Google OAuth client with prod, separate DB/secrets per environment). Phase 3 P3-1 encryption FOUNDATION complete but unwired (deferred, see `implemented_phases/phase_8_encryption.md`).

**Also fixed 2026-07-04: the permissive `pawn_anon` RLS gap.** `/pgrst/` is a public, unauthenticated PostgREST endpoint — previously any caller on the internet, no PAWN account needed, could read/write any user's `image_sessions`/`image_jobs` rows (including other users' generated images). Fixed by wiring up the existing (previously inert) `session_token`: both warm-session Kaggle notebook templates now send it as an `X-Session-Token` header on every PostgREST call, and new RLS policies in `postgres/schema.sql` require it to match before permitting SELECT/UPDATE. Live-migrated onto `pawn-temp`'s running Postgres, promoted `dev`→`main`, redeployed. Verified: `curl` with no/wrong token → `[]`; correct token → only that session's own rows; user confirmed a real session-start + generation still works end-to-end. This closes the item that was blocking ever flipping the OAuth consent screen from Testing to public.
**Last completed:** First live production deploy (D.8), verified end-to-end on the temporary bridge instance, 2026-07-04.
**Branch:** dev (merges → main)
**Plans:** `workspace/implemented_phases/phase_8_encryption.md`, `workspace/plan/plan_deployment.md`

> All prior phases (MU, W, imageLab A.0/A.1, Phase 6 UI) are merged and live on main.
> imageLab Milestones A.0/A.1 are tracked in `workspace/implemented_phases/phase_5_kaggle_image.md`.

---

## Phase A — Chat Agent Refinement (tools, router, orchestrator, subagents)
*Plan reference: `workspace/plan/plan_chat_agent_refinement.md`*
*Branch: dev*

Replaces the hand-rolled ReAct JSON action protocol with native OpenAI-compatible
tool/function calling, adds internet access (`web_search`/`fetch_url`), replaces
whole-doc injection with scoped `doc_search` **[Phase M]**, adds a heuristic-first
model router with per-role levels, rebuilds the LangGraph orchestrator around a
plan → tool-loop → final flow with budgets/iteration caps, adds three fixed preset
subagents (researcher/summarizer/coder, strictly sequential), and persists the full
agent trace. Prescriptive plan — implement exactly as written; `[Phase M]` tags were
re-verified against the as-built Phase M code on 2026-07-13.

- [x] **A.1 — Native tool calling in the provider layer** ✓ (2026-07-13)
  `llm_core.py` gains `chat_complete(url, model, messages, headers, tools=None,
  tool_choice="auto") -> dict` (non-streaming, same provider detection/wire format as
  `stream_llm`, which stays untouched; raises a clear `ProviderError` on a malformed
  200 response instead of a raw `KeyError`). `normalize.py` gains `chat_complete(model_id,
  messages, resolver, rate_limiter, user_id=None, tools=None) -> dict` wrapping it with
  the same two-level failover as `chat_stream` (new `_complete_one_model` helper,
  endpoint-level then cross-model via `fallback_models`); imported aliased as
  `_chat_complete_llm` to avoid shadowing normalize's own `chat_complete`. Registry
  `ModelEntry` gains `supports_tools: bool = True` (`schemas.py`); set on all entries in
  `data/registry/models.json` and `app/registry/seed.py`'s `INITIAL_MODELS`.
  `resolver.pick_model_by_capability` gains `require_tools: bool = False` filter.
  New `tests/test_chat_complete.py` (8 tests: tool_calls parsing, no-tools passthrough,
  malformed-response error, 429 handling, normalize success + cross-model 429 failover,
  require_tools filter positive/negative). 235 backend tests green (up from 227) via
  `docker compose exec backend pytest`. code-reviewer PASS (1 WARN fixed: malformed-
  response `KeyError`/`IndexError` now wrapped in a clear `ProviderError`; 3 NOTEs
  accepted as pre-existing patterns — broad `except Exception` mirrors `_stream_one_model`,
  `supports_tools` on embedding entries is semantically inert but harmless, `seed.py`'s
  `INITIAL_MODELS` has pre-existing drift from `data/registry/models.json` — both files
  still got the field, drift itself out of scope). build-validator PASS (all 7 plan
  criteria verified, confirmed `chat_stream`/`stream_llm` diff-clean, no route/agent
  imports `llm_core` directly). No security-auditor run (pure plumbing, no
  secrets/config/auth touched).
  Demo: `test_llm_core_chat_complete_parses_tool_calls` — a mocked model response with
  a `tool_calls` list round-trips through `chat_complete` into the parsed message dict. ✓
- [x] **A.2 — Tool layer** ✓ (2026-07-13)
  New `agent/tools/` package: `base.py` (`ToolSpec`/`ToolContext` dataclasses exactly
  as specced), `registry.py` (`get_tools(ctx)` — this session only assembles the two
  always-on tools, `calculator`/`get_datetime`; `web_search` (A.3) and
  `search_memory`/`doc_search` (A.4) conditional gating is explicitly deferred to those
  steps, documented in the module docstring), `execute.py` (`run_tool` wraps every
  handler in `asyncio.wait_for(..., TOOL_TIMEOUT_SECONDS)`; any exception/timeout →
  `"TOOL_ERROR: ..."`, never raises into the graph — verified by a dedicated
  never-raises test). `constants.py` gains `TOOL_TIMEOUT_SECONDS = 20`. `calculator.py`:
  hand-rolled whitelist-only AST evaluator (`Constant`/`BinOp`/`UnaryOp` only — no
  `Name`/`Call`/`Attribute`/`Subscript`/comprehensions/`Lambda`/etc., never `eval()`/
  `exec()`), plus `_MAX_POW_EXPONENT=1000` and `_MAX_EXPRESSION_LENGTH=200` bounds and
  an `asyncio.to_thread` offload — added after code-reviewer's first pass found a
  CRITICAL (an unbounded `**` exponent is a valid-grammar resource-exhaustion DoS the
  timeout alone can't preempt, since the computation is synchronous and never yields
  control back to the event loop). `get_datetime.py` returns current UTC in ISO 8601;
  the plan's "+ user-local ISO strings" wording is not implemented — no user-timezone
  field exists anywhere in the app today, so there's nothing to convert against
  (documented gap, not silently dropped).
  New `tests/test_agent_tools.py` (20 tests: registry assembly, run_tool
  success/timeout/exception/never-raises, calculator correctness + adversarial
  sandbox-escape rejections + oversized-exponent/overlong-expression rejections +
  static no-eval/exec source scan, get_datetime UTC format). 265 backend tests green
  (up from 235) via `docker compose exec backend pytest`. code-reviewer: 1st pass FAIL
  (1 CRITICAL — the calculator DoS above); fixed (exponent/length bounds +
  `asyncio.to_thread`); re-verified PASS via independent static trace confirming the
  bound check runs strictly before `operator.pow` on every recursion level. No
  security-auditor run (per plan, mandatory only for A.3's SSRF surface in A.9; A.2
  touches no secrets/config/auth — the calculator's safety was the security-relevant
  surface here and got the equivalent scrutiny via two code-reviewer passes).
  build-validator PASS (all plan criteria verified against the diff + a live
  `docker compose exec backend pytest` run; the A.3/A.4 tool-gating scope cut and the
  get_datetime user-local gap both explicitly called out as accepted, not silent).
- [x] **A.3 — Internet access: `web_search` + `fetch_url`** ✓ (2026-07-13)
  `key_store.VALID_PROVIDERS` gains `tavily`/`brave` (same AES-GCM BYOK storage as LLM
  keys); `ApiKeysSection.tsx` gains a "Search (optional)" group with both rows.
  `agent/tools/web_search.py`: Tavily `POST` (preferred) / Brave `GET` fallback,
  `WEB_SEARCH_MAX_RESULTS=5`, numbered `title — url — snippet` observations.
  `agent/tools/fetch_url.py`: `httpx` GET + `trafilatura` extraction, truncated to
  `FETCH_MAX_CHARS=8000`. SSRF guard (`guard_url`): scheme allowlist (http/https),
  hostname resolved via `asyncio` loop.getaddrinfo, rejects private/loopback/
  link-local/reserved/multicast/unspecified ranges (`ipaddress` stdlib) — including an
  IPv4-mapped-IPv6 unmap-and-recheck step (`::ffff:127.0.0.1`-style bypass, found by
  code-reviewer's first pass and fixed) — BEFORE every request; redirects followed
  manually (`follow_redirects=False`) with the guard re-applied on every hop, bounded
  at `max_redirects=3`. `registry.py`: `fetch_url` always-on (safety is the guard, not
  a key); `web_search` added only when a Tavily or Brave key is configured.
  `events.py` gains `citation_event(url, title)` (not yet called — the execute loop
  that would emit it is A.6, correctly out of scope this session). Frontend:
  `client.ts` `onCitation` callback + dispatch; `ChatPage.tsx` appends de-duped
  citations onto the assistant message; `Message.tsx` renders source chips
  (favicon-less, `title` text, opens in new tab, filtered to `http(s)://` hrefs only —
  a proactive fix for a citation-XSS-adjacent finding even though citations aren't
  live yet). New `tests/test_agent_tools_search.py` (21 tests: provider-mocked
  Tavily/Brave + preference order, key-missing → `TOOL_ERROR`/tool-absent, and a full
  SSRF matrix — scheme, loopback literal, localhost hostname, `10.x`, `169.254.169.254`
  metadata IP, DNS-failure, IPv4-mapped-IPv6 ×2, redirect-to-private, max-redirects).
  One now-stale A.2 registry test loosened (hardcoded exact toolset → subset check,
  since A.3 legitimately adds `fetch_url`/conditionally `web_search`). 286 backend
  tests green (up from 265); `tsc --noEmit` + `npm run build` clean.
  code-reviewer: PASS with 2 WARN fixed (IPv4-mapped-IPv6 SSRF bypass; citation `href`
  scheme filter added proactively) + 2 NOTE deferred (synchronous `trafilatura.extract`
  not offloaded to a thread — low priority until large pages are common; hardcoded
  Tavily/Brave URLs — consistent with how provider URLs are handled elsewhere, not a
  `data/registry` violation). **security-auditor (mandatory per plan) PASS** — 0
  CRITICAL; explicit verdict on the DNS-rebinding TOCTOU (guard re-resolves the
  hostname, httpx independently re-resolves it again at connect time — the plan
  specifies hostname re-checking, not IP-pinning): accepted as a documented,
  non-blocking residual given this is a personal BYOK tool, not multi-tenant infra —
  revisit with IP-pinning if ever deployed against a network with sensitive internal
  services. One NOTE (no raw-response byte cap before `trafilatura.extract`, only
  post-extraction truncation — future hardening, non-blocking). build-validator PASS
  (all plan criteria verified against the diff + live `pytest`/`tsc`/`vite build` runs).
- [ ] **A.4 — `doc_search` (replaces whole-doc injection) [Phase M]**
  Upload path chunks + indexes into scoped RAG with `kind='document'`; `chat.py`'s
  whole-doc injection deleted; `tools/doc_search.py` / `tools/search_memory.py`.
- [ ] **A.5 — Model router**
  New `core/router.py`: heuristic-first `classify()`, LLM fallback tier, `ROLE_LEVELS`,
  user model-pick override for the final answer.
- [ ] **A.6 — Orchestrator: graph v2**
  `agent/graph.py` rebuilt: `classify` → `direct_answer` | `plan` → `execute` (tool
  loop, budgeted) → `final`. Old ReAct nodes/parser deleted.
- [ ] **A.7 — Preset subagents**
  `agent/subagents.py`: `researcher`/`summarizer`/`coder`, sequential delegation via
  `delegate_<name>` tools, shared token budget, no nested delegation.
- [ ] **A.8 — Trace persistence + frontend**
  `trace` field on persisted assistant messages **[Phase M layout]**; `TraceView.tsx`;
  streaming activity block + auto-collapse summary row; citation chips.
- [ ] **A.9 — Tests, review, live verify**
  Full backend suite + frontend build gates; code-reviewer + mandatory security-auditor
  (SSRF guard, search-key handling); live verification checklist (plan §A.9).

---

## Phase M — Memory Scoping (Standalone Chats, Projects, Scoped RAG)
*Plan reference: `workspace/plan/plan_memory_scoping.md`*
*Branch: dev*

Drops the always-cross-chat memory tier for strict isolation: standalone chats get
their own chat-scoped RAG, projects get project-scoped RAG shared across their chats,
and nothing crosses a scope boundary. Prescriptive plan — implement exactly as written.

- [x] **M.1 — Schema + migration file** ✓ (2026-07-13)
  `postgres/schema.sql` + `postgres/migrations/2026-07_memory_scoping.sql` (drop old
  functions, drop+recreate `memory_chunks` with `scope_type`/`scope_id`/`kind`/`doc_id`,
  new `match_scoped_chunks`/`search_scoped_chunks` functions); applied to local dev
  Postgres, live-verified. `memory/index.py` `add_chunk(user_id, scope_type, scope_id,
  conv_id, chunk_id, msg_index, text, embedding)` upsert on `(user_id, chunk_id)`.
  165 backend tests green. code-reviewer PASS (0 CRITICAL). **Known transitional gap
  (accepted, closes in M.3/M.4):** `retrieve.py`/`summarize.py`'s `add_chunk` call site
  still reference the pre-M.1 shape, fail soft — see `dev_log.md` 2026-07-13.
  Demo: psql shows new table + functions; old functions gone. ✓

- [x] **M.2 — Drive storage layer: new layout + projects** ✓ (2026-07-13)
  `storage/drive.py` gains `move_item`. `storage/conversations_drive.py` retargeted to
  `PAWN/conversations/chats/`; project-aware `_locate_conv_folder`; per-chat
  `rag_chunks.jsonl` helpers. New `storage/projects_drive.py` (create/list/rename/delete
  project, list_project_chats, move_chat). Automatic one-time Drive migration (legacy
  `conversations/<id>/` → `conversations/chats/<id>/`), layout-inferred, no flag file.
  `tests/fake_drive.py` extended (`move_item`); new `test_projects_drive.py` (15 tests).
  180 backend tests green. code-reviewer found + fixed 1 CRITICAL (id()-keyed migration
  cache → instance-attribute flag); re-review PASS. No routes yet — pure storage layer,
  wired up by M.3 (indexer)/M.5 (projects API) next.
  Demo: create project via curl → Drive shows `projects/<id>/project.json`; old chats
  appear under `chats/`. ✓ (verified directly against storage layer + FakeDrive; curl-level
  demo deferred to M.5 once routes/projects.py exists)

- [x] **M.3 — Chunker + write path (indexing every turn)** ✓ (2026-07-13)
  `memory/chunker.py` (`chunk_turn`, fixed-size overlap chunks). `memory/indexer.py`:
  `resolve_scope` (in-process cache, `SCOPE_CACHE_TTL_SECONDS`, Drive-folder-derived),
  `index_turn_task` (Drive write first, Postgres second — Drive failure aborts with
  zero PG writes), `rebuild_index`. `chat.py` schedules `index_turn_task` from the
  existing persist-turn block; stateless chats never indexed. Conversation delete
  also deletes that chat's PG rows. `summarize.py`'s stale `add_chunk` call now routes
  through `index_turn_task`, closing the last M.1/M.2 transitional gap. 19 new/changed
  tests; 199 backend tests green (up from 180). code-reviewer PASS (0 CRITICAL; 2 WARN
  addressed with clarifying comments — see `dev_log.md`). One real bug (project scope
  id-vs-name confusion) caught by tests before review, fixed. No security-auditor run
  (touches no secrets/config/auth).
  Demo: send messages → chat's `rag_chunks.jsonl` grows; PG rows carry correct scope. ✓

- [x] **M.4 — Retrieval rewrite + agent wiring** ✓ (2026-07-13)
  `memory/retrieve.py` scoped signature `retrieve(query, user_id, scope_type, scope_id,
  top_k=MEMORY_TOP_K)`, queries `match_scoped_chunks`/`search_scoped_chunks`. `agent/graph.py`:
  `load_context_node` no longer always-retrieves (now a no-op); `search_memory_node` is
  the sole retrieval call site, using scoped retrieval, guarded so stateless chats never
  query Postgres. `AgentState` gains `scope_type`/`scope_id`, resolved once per request in
  `chat.py` via M.3's `resolve_scope`. `memory_hit_event` payload gains additive
  `scope`/`source_conv_id`; frontend shows a scope badge on project-sourced hits
  (`types.ts`/`client.ts`/`ChatPage.tsx`/`Message.tsx`). 203 backend tests green (up from
  199), incl. the core cross-scope-miss isolation test and a project-scope-sharing test;
  `npm run build` clean. code-reviewer PASS (0 CRITICAL, 1 trivial NOTE fixed). No
  security-auditor run (touches no secrets/config/auth).
  Demo: topic in standalone chat A NOT retrievable from chat B; two chats in one
  project see each other's content. ✓ (proven by test_retrieve_cross_scope_miss_isolation_guarantee
  and test_retrieve_project_scope_shared_across_member_chats; live-stack curl demo
  deferred to M.7's live verification checklist since there's no projects HTTP API
  until M.5)

- [x] **M.5 — Projects backend API + two-way chat moves** ✓ (2026-07-13)
  New `routes/projects.py` (CRUD + move in/out, cascade delete). Drive relocate always
  before the Postgres scope update; scope cache evicted on both moves; both idempotent;
  409 on moving into a second project while already in one. New `memory/locks.py`
  (`get_conv_lock`) — per-`(user, conv)` asyncio lock shared by M.3's `index_turn_task`,
  both move endpoints, and cascade delete (holds every contained chat's lock). 219
  backend tests green (up from 203). code-reviewer PASS (1 WARN fixed: cascade delete
  now lock-coordinated, closing an orphan-Postgres-row race). security-auditor PASS
  (0 findings, run proactively given the destructive cascade-delete + data-relocation
  surface — see `dev_log.md`).
  Demo: curl move a chat in → chunks retrievable from a sibling; move it out →
  sibling retrieval no longer surfaces them; delete project → chats + chunks gone. ✓
  (verified via test_projects.py's move-in/move-out/cascade-delete tests against
  FakeDrive + mocked Postgres; live curl demo against a real stack deferred to M.7's
  live verification checklist per the plan's own step order)

- [x] **M.6 — Frontend: projects UI + move flows** ✓ (2026-07-13)
  `types.ts`/`client.ts` additions (`Project`, `ConversationMeta.project_id`,
  `getProjects`/`createProject`/`renameProject`/`deleteProject`/`moveChatToProject`/
  `removeChatFromProject`/`rebuildMemory`/`clearMemory`); `useConversationStore`
  gains `projects` + the four move/CRUD mutators, `syncQueue`'s op union extended
  with `createProject`/`renameProject`/`deleteProject`/`moveChat` exactly as named
  in the plan; `ProjectSection.tsx`/`ProjectRow.tsx` (split out of `Sidebar.tsx`
  per frontend.md's 150-line rule) + `KebabMenu.tsx` (shared one-level submenu
  component) + `ConfirmDialog.tsx` (shared blocking dialog); all three required
  confirm dialogs (add-to-project, remove-from-project, delete-project listing
  contained chats) plus a fourth for the destructive "Clear memory" action (added
  during review — the plan's M.6 text specifies "confirm dialog" for clear but the
  first pass wired it directly to the kebab click); new routes `/project/:projectId`
  + `/project/:projectId/chat/:id`; new `routes/memory.py` (`POST /memory/rebuild`,
  `POST /memory/clear`, both user+scope-checked, 404 on unknown scope) surfaced via
  "Memory ▸" submenus on both chat and project kebabs (not Settings, per plan).
  New-chat-in-project: no dedicated backend "create inside project" endpoint exists
  (M.5 only has move in/out on an existing chat) — implemented as lazy-create +
  immediate `moveChat` op instead, documented inline in `useConversationStore.ts`.
  Gate: `tsc --noEmit` zero errors, `npm run build` clean, 227 backend tests green
  (via `docker compose exec backend pytest`).
  code-reviewer (build-step skill): 1 CRITICAL fixed — `syncQueue.ts`'s `moveChat`
  coalescing recomputed `fromProjectId` from the (already self-mutated) store ref on
  every re-enqueue instead of only the first time, so a rapid double
  remove-from-project could silently drop the backend call entirely (UI shows
  removed, project chunks never actually get unscoped — an isolation leak). Fixed:
  `fromProjectId` now resolved once per queue entry, preserved across coalesces.
  1 WARN fixed (the missing Clear-memory confirm dialog, above). 2 NOTEs deferred
  (pre-existing bare `except Exception` swallowing in `conversations_drive.py`'s
  Drive-folder lookups, relied on by `memory.py` for 404 resolution; `memory.py`'s
  Postgres delete has no try/except unlike `conversations.py`'s sibling
  `_delete_chunks` pattern — low severity, it's a derived/rebuildable index).
  No security-auditor run (no secrets/config/auth touched, same call as M.4).
  Demo: create project in sidebar → two chats inside share retrieval (memory_hit
  badge shows source chat) → add/remove a standalone chat → siblings gain/lose
  access → delete project (dialog lists chats) → everything gone. Not yet run
  against a real stack — deferred to M.7's live checklist per the plan's own step
  order (same pattern as M.4/M.5's demo notes).

- [~] **M.7 — Tests, review, live verify** (automatable parts done 2026-07-13;
  live checklist NOT yet run — needs the user + a real Drive-linked stack)
  Done: full backend suite green (227 tests via `docker compose exec backend
  pytest`); frontend `tsc`/`npm run build` clean; code-reviewer run via build-step
  skill on M.6 (see above); no security-auditor needed (M.4/M.5/M.6 touch no
  secrets/config/auth). `current_state.md` + `dev_log.md` updated.
  **Still pending — live verification checklist (needs the user, a real Drive
  account, and the docker compose stack up), plan §M.7 items 1–7 plus the
  embedding-swap re-embed check from the M.1 gap fix:**
  1. Legacy Drive tree migrates cleanly; old chats load from `chats/`.
  2. Standalone chat A content NOT retrievable in chat B (the isolation guarantee).
  3. Long standalone chat (40+ msgs) recalls an early detail via its own RAG when
     the agent decides to search.
  4. Two chats in one project share retrieval both directions; a chat outside sees
     none.
  5. Add standalone chat to project → siblings retrieve its history; its new turns
     index into project scope. Remove it → siblings lose access; its new turns
     index into chat scope again.
  6. Delete chat → its PG chunks gone. Delete project → all chats, Drive folders,
     and PG rows gone.
  7. Truncate PG `memory_chunks` manually → `POST /memory/rebuild` restores
     retrieval from Drive files alone.
  8. (Embedding-fix gap, not in the original plan) Any real chats indexed while
     `text-embedding-004` was dead have chunk rows with no/broken embeddings —
     `POST /memory/rebuild` per affected scope re-embeds them via
     `gemini-embedding-2` from the Drive `rag_chunks.jsonl` source of truth. Not
     run against real Drive data yet.
  M.7 gets marked `[x]` only after the user confirms these live.

---

## Phase 1 — Foundation
*Plan reference: `workspace/implemented_phases/phase_1_0_foundation.md`*

- [x] **Step 1 — Create the repo**
  Folder structure, `.gitignore`, first commit. Demo: `git log` shows one commit.

- [x] **Step 2 — Claude Code config**
  `.claude/` wired: CLAUDE.md, rules, agents, skills, settings.json with hook.
  Demo: `claude` in the repo; rules load; hook blocks secret touches.

- [x] **Step 2.5 — Docker scaffolding**
  `constants.py`, `config.py`, `docker-compose.yml`, secrets pattern.
  Demo: `docker compose config` validates.

- [x] **Step 3 — Chat UI**
  React + Vite + TS + Tailwind. Components: ChatWindow, MessageInput, Message.
  Demo: type a message; it appears as a bubble.

- [x] **Step 4 — FastAPI backend**
  Health check, middleware stack (security headers, timeout, gzip).
  Demo: `curl http://localhost:8000/health` → `{"status":"ok"}`.

- [x] **Step 5 — Connect frontend to backend**
  `api/client.ts`, health check on mount.
  Demo: console logs `{status: ok}` from live backend.

- [x] **Step 6 — First real AI response**
  `llm_core.py` minimal, Gemini 2.5 Flash via OAI-compat endpoint.
  Demo: type "hello", get a real Gemini reply streaming.

- [x] **Step 7 — Typed SSE events**
  `events.py` builder functions. All event types wired. `StreamChatCallbacks` object in client.ts.
  Demo: Network tab shows `{"type": "token", "delta": "..."}`. 6 tests passing.

- [x] **Step 8 — Conversation history**
  Full message array forwarded per request.
  Test: `test_chat_forwards_full_history` verifies all turns reach the LLM. 7 tests passing.

- [x] **Step 9 — Multi-provider (normalize.py)**
  `core/normalize.py` with 6-provider PROVIDERS map (Groq, Cerebras, Gemini, HuggingFace, GitHub, OpenRouter).
  `chat.py` routes through normalize; accepts `provider` field in request.
  Groq secret added. 12 tests passing.

- [x] **Step 10 — Model switcher UI**
  Hardcoded dropdown, provider sent per message.
  Demo: switch mid-conversation, context intact.

- [x] **Step 11 — Basic RAG**
  `POST /upload`, whole-doc injection, attach button in UI.
  Demo: upload a doc, ask about it — AI answers from it.

---

## Phase 1.5 — Memory & Agent
*Plan reference: `workspace/implemented_phases/phase_1_5_memory_agent.md`*

- [x] **Step 12 — Multi-chat persistence**
  Backend source of truth. `data/conversations/<uuid>/`. CRUD endpoints. Sidebar UI.
  Demo: two chats with independent history, survive restarts. Auto-title fires.

- [x] **Step 13 — Complete typed SSE events**
  All event types dispatched and routed in `streamChat`. Frontend callbacks wired.
  Demo: all event types appear in Network tab; UI handles each.

- [x] **Step 14 — Per-chat memory summaries**
  Rolling `summary.md` per conversation. Threshold-triggered summarization.
  Demo: 30-message chat coherent; `summary.md` written to disk.

- [x] **Step 15 — RAG over memory**
  `data/memory/index.json`. `text-embedding-004` embed interface. Brute-force cosine.
  Demo: fact from chat A surfaces in chat B via retrieval.

- [x] **Step 16 — LangGraph agent**
  `StateGraph` with 5 nodes. JSON/ReAct protocol. Trace panel in UI.
  Demo: complex question → trace shows plan/retrieve/draft/critique/answer.

---

## Phase 1.6 — Rate-Limit Resilience
*Plan reference: `workspace/implemented_phases/phase_1_6_rate_limit.md`*
*Branch: `dev/rate-limit-resilience`*

- [x] **Step R1 — Registry foundation**
  `models.json` + `endpoints.json` seeded. `loader.py`. `GET /registry/models`.
  New secrets: huggingface, github, openrouter.
  Demo: `GET /registry/models` returns the full catalog.

- [x] **Step R2 — Rate limiter**
  `EndpointRateLimiter`: rolling windows, 90% threshold, cooldowns, dead-host.
  Demo: unit tests show endpoint flips unavailable at ≥90% and recovers.

- [x] **Step R3 — Resolver + normalize contract change**
  `Resolver.pick(model_id)`. `normalize.chat_stream(model_id, messages)`.
  `ChatRequest` takes `model_id` only. Agent swaps to `PURPOSE_TO_LEVEL`.
  Demo: force priority-1 past 90% → next endpoint serves reply; `provider_switch` emitted.

- [x] **Step R4 — Frontend wiring**
  `ModelSwitcher` fetches from API. `provider_switch` inline notice. Provider badge.
  Demo: dropdown shows Fast/Balanced/Research groups; failover notice appears.

- [x] **Step R5 — UI visual overhaul + LAN access**
  CSS variable theme system + FOUC-prevention script in `index.html`. `InteractiveGridBackground` canvas. Floating pill header islands (title toggle left, ModelSwitcher + dark mode right); gradient overlays `h-16`. Smart scroll. `TracePanel.tsx` deleted — trace inlined in `Message.tsx` as unified metadata row + collapsible step cards. `react-markdown` for assistant. Auto-resize pill→card input. `Sidebar` mini `w-12`, click-column expand, flicker-free transitions, profile avatar, neutral delete. Registry `providers` field. LAN IP in CORS + `VITE_API_URL`.
  Demo: dark/light persists on reload (no flash); long message collapses; agent trace auto-collapses after stream; grid reacts to mouse.

- [x] **Merge Phase 1.6 → main**

---

## Phase MU — Multi-User / Auth / BYOK / Drive
*Plan reference: `~/.claude/plans/what-i-want-1-mutable-waffle.md`*
*Branch: dev*

Architecture:
- App data (profiles, sessions, BYOK keys, memory embeddings) → Supabase free tier (pgvector)
- User data (conversations, uploads) → user's own Google Drive
- Auth: Google OAuth2 (includes drive.file scope)
- BYOK: keys encrypted AES-256-GCM at rest; backend proxies all LLM calls (no CORS exposure)

- [x] **MA-1** — Supabase client + AES-GCM crypto + new secrets wired ✓
  `backend/app/db/supabase_client.py`, `backend/app/core/crypto.py`, 6 new secrets,
  updated `config.py`, `requirements.txt`, `docker-compose.yml`, `secrets/*.example`
  NOTE: supabase_url / supabase_service_key / google_client_id / google_client_secret
  contain PLACEHOLDER values — user must fill with real values before MA-2 routes work.
  encryption_secret and jwt_secret are pre-generated with real random values.

- [x] **MA-2** — Google OAuth2 + auth routes + JWT ✓
  `backend/app/core/jwt_utils.py`, `backend/app/routes/auth.py` (login/callback/me/logout),
  registered in main.py. /auth/* routes public (no middleware yet).

- [x] **MA-3** — Auth middleware + route scoping ✓
  `backend/app/middleware/auth.py` (AuthMiddleware, JWT Bearer, public /health /auth/*),
  `backend/tests/conftest.py` (bypass_auth fixture for tests),
  storage/conversations.py and documents.py scoped by user_id,
  routes/conversations.py, routes/upload.py, routes/chat.py pass user_id through,
  LangGraph thread_id namespaced as {user_id}:{conv_id}. 47 tests passing.
  `backend/app/routes/auth.py` (login/callback/me/logout), `backend/app/core/jwt_utils.py`

- [x] **MA-4** — Frontend auth UI + 429 back-off timer ✓
  `frontend/src/contexts/AuthContext.tsx` (AuthProvider, useAuth, OAuth callback handler),
  `frontend/src/pages/LoginPage.tsx` (Google sign-in button with inline SVG logo),
  `frontend/src/api/client.ts` (authHeaders() on all requests, onRateLimit callback, 401 auto-reload),
  `frontend/src/App.tsx` (AuthProvider wrapper, AuthGate, 429 countdown banner, useAuth for displayName),
  `backend/app/events.py` (rate_limit_event + code field on error_event).
  Build passes (tsc + vite). 47 backend tests passing.
  `AuthContext.tsx`, `LoginPage.tsx`, JWT header injection in `client.ts`, rate-limit countdown UI

- [x] **DD-1** — Drive storage layer ✓
  `backend/app/storage/drive.py` (DriveStorage: root/folder CRUD, upload/download text,
  list, delete, find; auto token refresh + Supabase persistence callback),
  `backend/app/core/drive_factory.py` (get_drive_for_user — exception-safe, returns None
  when Supabase unavailable / no tokens / decrypt fails → callers fall back to local FS).

- [x] **DD-2** — Conversations → Google Drive ✓
  `backend/app/storage/conversations_drive.py` (same interface, drive as first param;
  folder structure PAWN/conversations/{conv_id}/meta.json|messages.jsonl|summary.md).
  Routes wired: routes/conversations.py + routes/chat.py + memory/summarize.py all try
  get_drive_for_user(user_id) first, fall back to local filesystem when None.

- [x] **DD-3** — Uploads → Google Drive ✓
  `backend/app/storage/documents_drive.py` (PAWN/uploads/{doc_id}.txt).
  Routes wired: routes/upload.py + routes/chat.py use drive when available, else local.
  47 tests passing (tests hit local fallback since no real Supabase).

- [x] **SM-1** — Memory → Supabase pgvector ✓
  `memory/index.py` add_chunk(user_id, conv_id, text, embedding) → Supabase insert (exception-safe).
  `memory/retrieve.py` retrieve(query, user_id, active_conv_id, top_k) → pgvector + FTS via RPC,
  RRF fusion in Python, graceful degradation (FTS-only if embed fails, [] if Supabase down).
  AgentState gains user_id; graph.py retrieve calls + chat.py inputs pass it through.
  summarize.py indexes summaries with user_id. Removed sqlite-vec dep.
  `supabase/schema.sql` created (tables + match_memory_chunks/search_memory_chunks RPCs).
  test_rag.py rewritten to mock Supabase. 47 tests passing.
  NOTE: user must run supabase/schema.sql in their Supabase project before memory works live.

- [x] **BK-1** — BYOK key store + /keys routes ✓
  `backend/app/core/key_store.py` (set_key/get_key/list_providers/delete_key, AES-GCM,
  exception-safe reads, VALID_PROVIDERS set). `backend/app/routes/keys.py`
  (GET /keys → providers only, PUT /keys/{provider}, DELETE /keys/{provider}; key values
  never returned). Registered in main.py. test_keys.py (7 tests).

- [x] **BK-2** — Resolver + normalize per-user key lookup ✓
  `resolver.pick(model_id, user_id=None)`: user BYOK key (key_store.get_key) preferred,
  falls back to shared Docker secret; keyed endpoints first, falls back to all available
  if none keyed (preserves test/dev path). `normalize.chat_stream(..., user_id=None)`
  forwards to pick. graph.py AgentState.user_id threaded into agent/ask_model/final nodes
  + their pick/chat_stream calls. chat.py generate_title + error fallback pass user_id.
  DummyResolver.pick signatures updated. 54 tests passing.

- [x] **BK-3** — Frontend settings panel ✓
  `frontend/src/components/ApiKeysSection.tsx` (BYOK: per-provider password input, Save/Remove,
  "Configured" badge, getKeys/setKey/deleteKey; key values never re-displayed).
  Integrated into existing `SettingsPage.tsx` (new API Keys section + Profile shows real email
  + Sign out button; removed now-implemented "Connected Accounts" from Future list).
  `Sidebar.tsx` profile card shows real email (gear icon already wired pre-MA-4).
  `App.tsx` passes user.email + logout; client.ts getKeys() unwraps {providers}.
  Fixed pre-existing unused-var build errors (useCallback, isAuthenticated).
  Frontend build passes (tsc + vite). 54 backend tests passing.

---

## Manual Setup (user action) — DONE: login working end-to-end ✓

Completed by user on 2026-06-27. Google OAuth2 → JWT → app login verified working.

1. **Supabase**: created free project; ran `supabase/schema.sql`; filled
   `secrets/supabase_url` + `secrets/supabase_service_key` (new-style `sb_secret_...` key).
2. **Google Cloud OAuth2**: created Web client; redirect URI
   `http://localhost:8001/auth/callback`; Drive API enabled; consent screen in Testing with
   test user added; filled `secrets/google_client_id` + `secrets/google_client_secret`.
3. `encryption_secret` + `jwt_secret` were already real (MA-1).

### Setup-time code fixes (must be committed)

- **PKCE disabled** (`autogenerate_code_verifier=False` in `routes/auth.py:_build_flow`): the flow
  is stateless (separate Flow objects in /login and /callback) so a per-request code_verifier
  can't survive; google-auth-oauthlib auto-PKCE caused "invalid_grant: Missing code verifier".
  Safe because this is a confidential client (has client_secret).
- **`OAUTHLIB_RELAX_TOKEN_SCOPE=1`** set at import in `routes/auth.py`: Google reorders/drops scopes
  (e.g. drive.file under granular consent), and oauthlib errors on any scope change. Relaxed so
  exchange completes; missing drive.file → app falls back to local filesystem storage.
- **Naive-UTC expiry fix** (`storage/drive.py` __init__): Supabase returns `expires_at` as tz-aware
  `timestamptz`, but google-auth compares expiry against a naive UTC now() → TypeError crashed every
  chat request. Now converted to naive UTC. This was the "conversations save but no reply" bug.

### Verified live (2026-06-27) ✓

- [x] Google OAuth login → JWT → app.
- [x] Conversations saving to user's Google Drive (`PAWN/conversations/`).
- [x] BYOK Google key (Settings → API Keys) → LLM reply streams back ("Hello there friend.").

### Still to verify (optional, before/after merge)

- [ ] Memory: fact from chat A surfaces in chat B (needs Supabase pgvector + embeddings).
- [ ] Second Google account → empty chat list (isolation).

### Next: commit setup fixes + merge dev → main

---

## Phase W — Warm Sessions + Job Tracking (imageLab)
*Plan reference: `workspace/implemented_phases/phase_5_kaggle_image.md`*
*Branch: imageLab (merges → dev)*

Goal: keep one Kaggle container **warm** so repeat images are fast (user-set timer + image cap), and
make every generation a **durable, server-tracked job** (fixes the double-submit / lost-result bug)
surfaced in a **Generations monitor panel**. Architecture: **Supabase job-queue rendezvous** — a
persistent kernel loads the model once, then loops polling Supabase for prompts and writes images
back. Image Lab only (chat composer deferred to Milestone B). Targets the top deferred item
(FLUX ~820 s/image).

- [x] **W.0 — Prove the persistent loop (CPU, no model)** ⚠️ first / load-bearing ✓
  `image_sessions` + `image_jobs` schema; `kaggle_templates/session_poc/` CPU echo notebook;
  `core/image_session.py` (`start_session`/`get_session_status`/`stop_session`/`submit_session_job`/`get_job`)
  pushing via the non-blocking `kaggle.deploy_kernel`; session routes (`/generate/session/*`,
  `/generate/job/{id}`); new `supabase_anon_key` secret (public — service key never injected);
  minimal `SessionPocPanel` Lab control. 117 backend tests green (24 new); `npm run build` clean.
  code-reviewer + security-auditor PASS (0 critical). RLS/scoped-JWT deferred to W.1 (documented).
  **LIVE-VERIFIED (2026-06-29):** Lab → Start warm session → kernel reached Warm with a live
  countdown + fresh heartbeat, 2 echo jobs round-tripped through Supabase (ECHO: "really" rendered).
  Supabase's new sb_publishable_* key enforces RLS → added a permissive anon policy on the two
  tables (commit 043a7f3). The persistent-loop assumption is PROVEN.

- [x] **W.1 — Warm session backend + FLUX persistent notebook + unified job tracking** ✓
  `image_flux_session/notebook.ipynb` (load FLUX once → Supabase serve-loop); session manager made
  registry-driven (FLUX→GPU serve-loop, SDXL→CPU echo) + `extend_session`; **cold one-shot path
  retrofitted to a durable background job** (`POST /generate` → `{job_id}`, GC-safe fire-and-forget
  worker behind the per-`(user,model)` lock, de-dup); `GET /generate/jobs` (+ `/job/{id}` from W.0);
  constants (job poll, cold-job reap wall-clock); `reap_stale_jobs`. Frontend: `runGenerate`/poll
  contract, `extendSession`/`listJobs` helpers, `SessionPocPanel` renders PNG (FLUX) or echo (SDXL).
  132 backend tests (new `test_image_jobs.py`); `npm run build` clean. code-reviewer PASS (CRITICAL
  create_task-GC fixed) + security-auditor PASS (service key never injected).
  **Deferred (documented):** `supabase_jwt_secret` + scoped per-session JWT — the new Supabase
  `sb_publishable_*` platform deprecates legacy HS256-secret minting; permissive-anon RLS policy
  (W.0) kept for the single-user trial; **scoped JWT is MANDATORY before multi-user**. SDXL real
  serve-loop is a follow-up.
  **Live verify pending:** Image Lab → FLUX → Start warm session → first image ~10 min, later in
  **seconds**; Extend/Stop work; cold Generate still returns an image (now job-polled).

- [x] **W.2 — Image Lab UI (session controls + Generations monitor panel)** ✓
  Job-driven `ImageGenerator` (submit → poll job id, inline render); **server-derived button state**
  (parent lifts a shared `listJobs` poll → disabled while a model has a queued/running job → no
  duplicate submit, survives refresh; + a local submitting guard for the click→response window);
  new `components/GenerationsPanel.tsx` (all jobs across models/sessions, status chips, lazy
  thumbnails + View lightbox + Download); new `components/SessionBar.tsx` (duration/cap picker, live
  countdown, Extend +30, Stop, "session ended" CTA; re-attaches on refresh); `SessionPocPanel`
  deleted (superseded). `npm run build` clean; 132 backend tests green. code-reviewer PASS (0 critical;
  WARN fixes applied: double-submit guard, gated countdown ticker, mime-derived download filename).
  **Deferred (documented):** frontend unit tests (project has none — gate is `npm run build`);
  GenerationsPanel lazy-image fan-out capped at 30 (fine for trial).
  **Live verify pending:** full warm-FLUX flow + monitor panel; refresh mid-generate → job
  re-attaches in the panel + button stays disabled (the double-submit bug, visibly fixed).

- [x] **W.3 — Real SDXL warm serve-loop (image generation, not echo)** ✓
  *Plan: `workspace/implemented_phases/phase_5_kaggle_image.md`.* Added `kaggle_templates/image_sdxl_session/notebook.ipynb`
  (mirrors the FLUX serve-loop; loads SDXL once via `AutoPipelineForText2Image` → serve loop → PNG,
  `via kaggle:sdxl-session`). SDXL registry entry repointed to it (GPU + dataset, slug `pawn-sdxl-session`);
  dropped the unused CPU-POC imports. SDXL session test asserts the GPU push; added a session-slug↔title
  invariant test. No frontend change (already MIME-aware). 134 backend tests green; anon-key-only
  injection still verified for sdxl. **Live verify pending:** SDXL → Start warm session → `Warm` in
  ~1–2 min → Generate returns an image in seconds.

---

- [x] **W.4 — Session startup observability**
  Notebooks patch `installing` → `loading_model` → `ready` at phase boundaries.
  `_LIVE_STATUSES` extended. `SessionBar` shows phase-specific messages ("Waiting for GPU…" / "Installing…" / "Loading model…"). No schema changes.

- [x] **W.5 — Independent per-model panels**
  Tab switcher removed from `ImageLabPage`. All models rendered simultaneously as stacked `ModelPanel` components — each owns its own jobs poll, `SessionBar`, `ImageGenerator`, and `GenerationsPanel`. No cross-model job mixing.

- [x] **W.6 — Session liveness + cold-vs-warm routing fixes**
  `IMAGE_SESSION_HEARTBEAT_STALE_SECONDS`: 30 → 90. `create_cold_job` blocks when warm session is live. Kaggle GPU limit error surfaced as actionable message. `SessionBar` confirm dialog before re-Start.

---

## Phase 6 — UI Routing + Global Polish (imageLab branch)
*Plan reference: `workspace/implemented_phases/phase_6_ui.md`*

- [x] **Phase 6 UI — URL-based routing refactor**
  `react-router-dom` installed. `AppContext.tsx` lifts cross-route state (theme, models, prefs).
  `Layout.tsx` owns Sidebar + Outlet + global dark mode toggle (visible on all routes).
  `ChatPage.tsx` extracts chat logic; URL ↔ store sync via `useParams` + `useEffect`.
  `SettingsPageWrapper` / `ImageLabPageWrapper` thin pages replace direct component rendering.
  `App.tsx` down to 44 lines. `Sidebar.tsx` uses `useNavigate`/`useLocation` internally.
  tsc zero errors; `npm run build` clean.

- [x] **Settings page layout redesign**
  Restructured settings page to 3 responsive vertical columns for desktop viewports. Refined responsiveness of BYOK API key inputs and vertical Kaggle input fields; grouped bubble color presets into horizontally scrollable carousels with aligned horizontal start offsets and chevron scroll buttons.
- [x] **Settings page layout polish & API keys row alignment**
  Reverted global theme toggle to a single animated micro-interaction button. Refactored Settings Page columns (Appearance & Defaults) to stack controls, preventing boundary overflow on narrow column sizes. Corrected sliding theme selector background alignment calculation in ThemeToggle.tsx to handle gaps. Made detailed theme switcher responsive (hiding labels and adjusting padding on medium columns/viewports). Refactored Profile card rows (Display Name, Email, Actions) to stack vertically to avoid overflow. Restructured ApiKeysSection.tsx cards into separate rows for Title, Description, Status (Configured badge and Remove button placed at opposite corners with flex-wrap justification), and Inputs, converting credentials guide descriptions to interactive helper icons that toggle info boxes when clicked/tapped. Reduced outer spacing and card paddings (p-4 to p-3, gap-6 to gap-4, px-6 to px-4) across the Settings page. tsc zero errors; npm run build clean.

---

## Phase D — Production Deployment (Self-Hosted Postgres Migration + Oracle VPS)
*Plan reference: `workspace/plan/plan_deployment.md`*
*Branch: dev (merges → main)*

Drop Supabase for a self-hosted Postgres+pgvector database, fix the three
hardcoded-localhost prod blockers, and write a full `deployment.md` runbook
for PAWN as a second, isolated app on the existing Oracle Cloud Always-Free
ARM VM that already hosts Enma (same account — see plan for the reversed
decision and coexistence rules).

- [x] **D.1 — Kill hardcoded localhost values (CORS, OAuth redirect, CSP)**
  `backend/app/config.py` gains `CORS_ORIGINS`/`FRONTEND_URL`/`OAUTH_REDIRECT_URI`/
  `CSP_CONNECT_SRC` env-var-backed constants (defaults = today's localhost values).
  `main.py` CORS built from `CORS_ORIGINS` (comma-split, wildcard `*` guarded
  against — raises at startup). `routes/auth.py` `_FRONTEND_URL`/`_REDIRECT_URI`
  now read from config. `middleware/security.py` CSP `connect-src` reads
  `CSP_CONNECT_SRC`. New `backend/tests/test_deployment_config.py` (6 tests:
  defaults, env override, CORS allow/reject, wildcard guard). 148 backend tests
  green. code-reviewer PASS (2 WARN fixed: test-pollution in reload teardown,
  CSP format comment). security-auditor PASS (1 WARN fixed: `*` wildcard guard
  added to CORS_ORIGINS parsing).
- [x] **D.2 — Fix frontend build-time API URL**
  `frontend/.env.example` port fixed 8000 → 8001 (matches actual dev backend
  port). New committed `frontend/.env.production` with
  `VITE_API_URL=https://pawnai.duckdns.org` — confirmed embedded correctly in
  the production build bundle. `npm run build` clean. code-reviewer PASS (1
  NOTE, pre-existing/out of scope). No security audit needed (no
  secrets/auth/uploads touched).
- [x] **D.3+D.4 — Migrate Supabase → self-hosted Postgres+pgvector, and Kaggle
  rendezvous → self-hosted PostgREST** (done together — dropping the Supabase
  secrets in D.3 breaks D.4's Kaggle-payload code otherwise, so both were
  implemented and committed as one change)
  New `backend/app/db/postgres_client.py` (psycopg3 sync client — deliberately
  chosen over asyncpg to avoid a ~20-file async ripple across every
  `run_in_threadpool` call site; `fetchone`/`fetchall`/`execute` helpers plus a
  `transaction()` context manager for atomic read-then-write sequences).
  Rewrote all Supabase `.table()/.rpc()` calls to parameterized SQL in
  `routes/auth.py`, `core/key_store.py`, `core/drive_factory.py`,
  `memory/index.py`, `memory/retrieve.py` (SQL-function calls need explicit
  `::vector`/`::int` casts — found via live-Postgres testing), and
  `core/image_session.py` (full rewrite: session/job CRUD to SQL, `str()`
  wrapping at API boundaries for psycopg's native `uuid.UUID` returns, a
  `_parse_ts` fix for native `datetime` returns, `Json(...)` wrapping for
  jsonb columns; `start_session`/`extend_session`/`submit_session_job` now use
  `transaction()` to close read-then-write race windows). `config.py`:
  `SUPABASE_URL/SERVICE_KEY/ANON_KEY` → `POSTGRES_DSN` (secret) +
  `POSTGREST_PUBLIC_URL` (non-secret, D.4). `postgres/schema.sql` (directory
  renamed from `supabase/` — no longer accurate once Supabase was dropped):
  added
  `pgcrypto` extension (was missing, breaks `gen_random_uuid()`), folded in
  `image_jobs.params jsonb` (previously only in a separate manual-apply file
  that never got auto-mounted — a CRITICAL bug caught by code review before
  merge), added a `pawn_anon` role (NOLOGIN, idempotent `DO` block) with
  `GRANT select/insert/update` on `image_sessions`/`image_jobs` only, RLS
  policies retargeted from Supabase's `anon` to `pawn_anon` (same
  single-user-trial permissive posture as before — scoped JWT still
  deferred, unchanged decision from Phase W). New
  `postgres/init_pawn_anon.sh` sets `pawn_anon`'s password from the
  `postgrest_anon_password` secret via injection-safe `psql -v`/`:'var'`
  substitution (a `.sql` file can't read a secret file). `docker-compose.yml`:
  new `postgres` (pgvector image, healthcheck, named volume
  `pawn_postgres_data`, host port 5433 not 5432 — avoids colliding with a
  sibling project's Postgres) and `postgrest` (internal only, no host port)
  services. `requirements.txt`: dropped `supabase`, added `psycopg[binary]` +
  `pgvector`. Secrets: dropped 3 supabase secrets, added `postgres_password`/
  `postgres_dsn`/`postgrest_anon_password`/`postgrest_db_uri` (`.example`
  files + real generated local-dev values). All 3 Kaggle session notebooks
  (`session_poc`, `image_flux_session`, `image_sdxl_session`) updated: payload
  now carries `postgrest_url` instead of `supabase_url`/`anon_key`; headers
  drop `apikey`/`Authorization` (anonymous PostgREST requests get `pawn_anon`
  automatically via `PGRST_DB_ANON_ROLE`). Also fixed an unrelated pre-existing
  bug: `frontend/.dockerignore` was missing, so the frontend Docker build
  context pulled in local `node_modules` (a broken symlink there crashed
  BuildKit) — added it.
  148 backend tests green (rewrote `conftest.py`, `test_rag.py`,
  `test_image_session.py`, `test_image_jobs.py`, `test_keys_kaggle.py` to mock
  the new SQL functions instead of a chained Supabase-client fake).
  `npm run build` clean (unaffected, backend-only migration).
  code-reviewer FAIL→PASS (1 CRITICAL fixed: missing `image_jobs.params`
  column; 2 WARN fixed: read-then-write races now wrapped in `transaction()`,
  stale "Supabase" wording in docstrings/comments cleaned up).
  security-auditor PASS (fixed 2 WARN: stale unreferenced local Supabase
  secret files deleted, raw OAuth exception no longer leaked to the client in
  `auth.py`'s `/callback`).
  **Live-verified** (not just mocks): brought up real `postgres`+`postgrest`+
  `backend`+`frontend` containers from an empty volume — schema/role init
  scripts ran cleanly, PostgREST connected and served both anonymous reads
  *and* writes to `image_sessions` as `pawn_anon` (correctly denied DELETE,
  matching its grants), backend `/health` and frontend both responded. This is
  ahead of D.6's dry-run requirement, not a replacement for it — D.6 still
  needs a full BYOK + memory-retrieval + Kaggle-job pass.
- [x] **D.5 — Clean-`main` mechanism** (`scripts/promote-to-main.sh`; abandoned
  `.gitattributes merge=ours` after sandbox test proved it broken for
  modify/delete — see plan_deployment.md D.5). Proven against a repo clone;
  first real run deferred to D.8. `dev`→`main` must always use the script.
- [x] **D.6 — Pre-deploy test gate** — pytest 152 green, `npm run build` clean,
  all 3 compose configs valid, and **live-verified the Drive-less 412 path** on
  the running backend (`/conversations` + `/crypto/salt` with a no-Drive JWT →
  412 `not_configured`, not 500). Only the Drive-LINKED happy path remains
  (needs a real Google token) — covered by the D.8 staging verify (§8).
- [x] **D.6b — DROPPED (2026-07-04, no VM staging environment).** Decision
  reversed: `dev` stays local-only (never deployed to the VM); only `main`
  goes to prod (`pawnai.duckdns.org`). D.6's local pre-deploy gate substitutes
  for a dedicated staging box — acceptable given PAWN currently has no public
  user base (Google OAuth consent screen is Testing-mode, allowlist only).
  Local dev and prod now **share the same Google OAuth client** (both
  `localhost` and `pawnai.duckdns.org` redirect URIs registered) and the same
  Google account(s) for login; database/secrets stay **separate** per
  environment (own local Postgres for dev, own Postgres+secrets on the VM for
  prod) so a bad local test can't touch real prod data. See
  `plan_deployment.md` decision 8 for full rationale/tradeoffs (accepted:
  local dev is x86, the VM is ARM64, so ARM-specific issues surface at the
  real prod deploy, not a disposable staging box).
- [x] **D.7 — `deployment.md` + prod compose** — root `deployment.md`
  **rewritten prod-only 2026-07-04** (originally a two-env staging-first
  runbook; the staging section is now fully removed, not just marked stale —
  single-environment, `main`→`/opt/pawn`→`pawnai.duckdns.org` only, shared
  Google OAuth client with local dev per the D.6b decision above),
  `docker-compose.prod.yml` (parameterized, `config`-validated AND
  live-boot-tested locally: fresh-volume schema init, backend `/health`,
  PostgREST anon rendezvous 200 / denied-table 401), `.env.prod.example`/
  `.env.staging.example` (staging example now unused, harmless to keep),
  `.gitignore` for the real env files. Real-VM run behind Nginx/TLS/OAuth
  done in D.8 below (4 fixes found live folded back into this file).
- [x] **D.8 — First live deploy + full verify checklist** — **done 2026-07-04,
  on a temporary bridge instance.** The intended free-tier Ampere A1 instance
  hit "out of host capacity" in `ap-mumbai-1` at request time (Enma was
  successfully resized 4/24 → 3/18 to free the quota, verified healthy —
  that half of the plan holds); PAWN went live instead on `pawn-temp`
  (paid `VM.Standard.E5.Flex`, 1 OCPU/6GB, ~$46/mo, bridging until free
  capacity opens — a retry loop keeps polling). Full verify checklist
  passed: HTTPS health, no CSP violations, Google OAuth + Drive-linked
  round-trip, BYOK chat, real Kaggle SDXL generation via `/pgrst/`. Enma
  reconfirmed healthy throughout. 4 real bugs found+fixed live (host
  iptables blocking 80/443, `/pgrst/` 413 on image write-back, warm-session
  startup timeout too short, CSP missing `img-src data:`) — see "Active
  step" above for details; all 4 now folded into `deployment.md` so the
  pending migration to the permanent free instance won't repeat them.
- [x] **D.8 migration — moved off `pawn-temp` onto the permanent free-tier
  instance** — **done 2026-07-05.** Retry loop succeeded (attempt 183);
  data-preserving migration to `pawn` (`144.24.119.184`) verified end-to-end
  (matching DB row counts, HTTPS health, login/chat/load confirmed live by
  the user); DuckDNS repointed; fresh Let's Encrypt cert issued; `pawn-temp`
  terminated after a final local safety backup. One bug found+fixed:
  `docker-compose.prod.yml` CPU limits assumed 2 vCPUs, broke on Ampere A1's
  1 real vCPU — rescaled. See `dev_log.md` 2026-07-05 for the full record.

---

## Plan: Drive-Mandatory Storage (Remove Local-Storage Fallback)
*Plan reference: `workspace/plan/plan_drive_mandatory.md`*
*Branch: dev (merges → main). Reference/last-stable commit: `9350664`
(marked in `workspace/stable_commits.md`).*

Triggered by a passphrase-gate 500 caused by a Drive-scope gap in
`routes/crypto.py`'s error handling. Rather than patch just that route, the
local-filesystem fallback pattern is being removed everywhere — Google Drive
becomes the only storage backend for conversations, uploads, memory-summary
indexing, and the encryption salt. Sequenced before D.5-D.8; folds D.5/D.6 in
as Phase 3.

- [x] **Phase 1 — Backend: remove local-storage fallback, Drive mandatory**
  `core/drive_factory.py` gains `require_drive_for_user()` (raises
  `NotConfiguredError`, HTTP 412, when Drive isn't linked) and `call_drive()`
  (translates ANY Drive-operation failure — API error, insufficient OAuth
  scope, revoked grant — into the same clear error, not a raw 500). Every
  `if drive: ... else: local_storage...` branch removed from `routes/crypto.py`,
  `routes/conversations.py`, `routes/upload.py`, `routes/chat.py`,
  `memory/summarize.py`. Background tasks (`auto_title_background_task`,
  `summarize_conversation_task`) fail soft (log + return) rather than raising,
  since there's no HTTP response to attach the error to. `chat.py` only
  requires Drive when a request actually needs storage (`conversation_id` or
  `doc_id` present) — pure stateless chat still works without Drive linked.
  Deleted now-dead `backend/app/storage/conversations.py` and
  `backend/app/storage/documents.py`.
- [x] **Phase 2 — Tests: mock Drive as available everywhere it's implicitly relied on**
  New `backend/tests/fake_drive.py` (in-memory `FakeDriveStorage` running the
  real `conversations_drive.py`/`documents_drive.py` logic). Rewrote
  `test_conversations.py`, `test_upload.py`, `test_summarize.py`,
  `test_rag.py`, `test_crypto.py`; added 412-error-path tests.
  **Manually verified live** (full docker compose stack) per user request —
  automated pytest run was skipped this pass; re-run before D.6.
  **Related fixes found during manual testing:** removed the unwired Phase 3
  passphrase gate from the auth flow (`App.tsx`, deleted
  `PassphraseGate.tsx`) — it blocked the whole app for a feature that never
  got its encrypt/decrypt-on-write wiring done, pure friction with no
  benefit. Renamed `supabase/` → `postgres/` (schema.sql + init_pawn_anon.sh)
  — stale, misleading name once Supabase was dropped in D.3/D.4; updated
  `docker-compose.yml`'s mounts and all doc references; verified a fresh
  Postgres volume still bootstraps correctly from the renamed files.
- [x] **Phase 3 — Fold in D.5 + D.6** — D.5 done (`scripts/promote-to-main.sh`,
  replacing the abandoned `merge=ours`); D.6 gate done (pytest 152 + build clean
  + compose configs valid + live Drive-less 412 verified). Drive-linked happy
  path deferred to D.8 staging verify.
- [x] **Phase 4 — Review, docs, commit** — code-reviewer + security-auditor ran
  on the full combined Phase 1-3 diff (this had never actually happened for
  Phase 1+2 despite the plan calling for it — closed that gap). Both PASS, 0
  critical. 4 WARN-level findings fixed: stale "Drive is optional/local
  fallback" comment in `routes/auth.py` corrected to match the actual
  Drive-mandatory architecture; `drive_factory.py`'s `_build_drive_for_user`
  and `/auth/drive/status` were silently swallowing exceptions with no
  logging (inconsistent with every other fail-soft path in this same plan) —
  added stderr logging to both; `routes/upload.py` and `routes/chat.py`'s SSE
  catch-all were returning raw exception text to the client — genericized to
  fixed messages with server-side stderr logging instead. 152 backend tests
  still green after the fixes. `plan_deployment.md` D.1-D.7 checkboxes synced
  to `[x]` (previously out of sync with this file). D.5/D.6/D.7 build-validator
  checks (deleted storage files, no leftover local-storage branches, compose
  config valid) independently re-verified. This also folded in the
  D.6b/no-staging simplification decision (see above) and its OAuth/DB
  sharing model between local dev and prod.
- [x] **Follow-up — "Connect Google Drive" control in Settings** — backend
  `GET /auth/drive/status` (real Drive-call check, not token-existence) +
  `ApiKeysSection` Drive row (first in the card, Connected/Not-connected badge,
  Connect/Reconnect → existing `login()` OAuth). Closes the UX loop the
  Drive-mandatory 412 message pointed at. 157 backend tests, build clean.

---

## Working Agreement

- Auto mode: implement steps sequentially, update tracker after every step.
- Tests must pass before marking `[x]`. No exceptions.
- Update this file and `workspace/current_state.md` after every step.
- If blocked (user action needed), document in plan file and move to next implementable step.
