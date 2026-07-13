# PAWN — Development Log

One dated entry per step. Each entry is a brief record of what was built,
what decisions were made, and any issues encountered.
This becomes your interview script and project history.

---

### [2026-07-13] — Phase A starts: A.1 native tool calling in the provider layer

Registered Phase A (`plan_chat_agent_refinement.md`) in `build_tracker.md`
(A.1–A.9, all `[ ]`). This session: A.1 only.

`llm_core.py` gains `chat_complete(url, model, messages, headers, tools=None,
tool_choice="auto") -> dict` — a non-streaming sibling to `stream_llm` (untouched),
same provider detection/wire format, used for agent-internal calls (plan, tool
decisions) — never the final streamed answer. `normalize.py` gains its own
`chat_complete(model_id, messages, resolver, rate_limiter, user_id=None,
tools=None) -> dict`, mirroring `chat_stream`'s two-level failover (endpoint-level
then cross-model) via a new `_complete_one_model` helper; imported llm_core's
version aliased as `_chat_complete_llm` to avoid shadowing normalize's own function
name. Registry `ModelEntry.supports_tools: bool = True` (schemas.py), set explicitly
on every entry in `data/registry/models.json` and `seed.py`'s `INITIAL_MODELS`.
`resolver.pick_model_by_capability` gains `require_tools: bool = False`.

**One real gotcha, not a code bug:** local `python -m pytest` hung indefinitely on
`test_chat.py`'s first streaming test — reproduced even on a clean `git stash`, so
it predates this session's changes and isn't caused by anything here. The project's
own testing convention (`docker compose exec backend pytest`) is the one that
actually works; used that throughout. Also discovered the backend Docker image
needs an explicit `docker compose build backend` before `exec pytest` picks up new
source — only `./backend/data` is bind-mounted in `docker-compose.yml`, not
`app/`/`tests/`, so a stale image silently runs old code (caught this the first
run: it reported the pre-A.1 227-test count instead of the new 234/235).

code-reviewer PASS: 1 WARN fixed (`llm_core.chat_complete`'s
`data["choices"][0]["message"]` now wrapped in try/except → a clear
`ProviderError(kind="upstream_error")` on a malformed response instead of a raw
`KeyError` leaking through as the failover's final error message); 3 NOTEs accepted
as out of scope (a broad `except Exception` in `_complete_one_model` mirrors the
pre-existing pattern in `_stream_one_model`, not new; `supports_tools` on the two
embedding-type registry entries is semantically inert but harmless; `seed.py`'s
`INITIAL_MODELS` has pre-existing drift from `data/registry/models.json` —
missing `gemini-embedding-2`, different `active` flags on 2 models — inert in
practice since `seed_registry()` only writes when the data files don't already
exist, out of scope for this step). build-validator PASS (all 7 plan criteria
verified against the diff + a live `docker compose exec backend pytest` run).
No security-auditor run — pure plumbing, no secrets/config/auth/uploads touched.
235 backend tests green (up from 227; +7 new, +1 added during the WARN fix).

Next: A.2 (tool layer — `agent/tools/` package: `base.py`, `registry.py`,
`execute.py`, `calculator`, `get_datetime`).

---

### [2026-07-13] — Phase A / A.2: tool layer, plus a real DoS bug caught by review

New `backend/app/agent/tools/` package: `base.py` (`ToolSpec`/`ToolContext`),
`registry.py` (`get_tools(ctx)` — this session only wires the two always-on tools;
`web_search`'s search-key gating and `search_memory`/`doc_search`'s scope gating are
explicitly deferred to A.3/A.4, since those tools don't exist yet — documented in the
module docstring rather than guessed at), `execute.py` (`run_tool` wraps every handler
in `asyncio.wait_for(TOOL_TIMEOUT_SECONDS=20)`, converts any exception/timeout into a
`"TOOL_ERROR: ..."` string, never raises into the graph), `calculator.py`,
`get_datetime.py` (UTC ISO 8601 only — no user-local variant, since nothing in PAWN
tracks a user's timezone anywhere yet; a real gap against the plan's literal wording,
called out rather than silently dropped, deferred until there's an actual timezone
source to convert against).

**Real bug caught by code review, not by the first test pass.** The calculator's AST
evaluator is a genuine whitelist (only `Constant`/`BinOp`/`UnaryOp` node types reach
`_eval_node`'s recursion — no `Name`/`Call`/`Attribute`/`Subscript`/comprehensions/
`Lambda`, so classic sandbox-escape payloads like `__import__('os').system(...)`,
`(1).__class__`, or `[x for x in ...]` all hit the trailing `raise ValueError`
structurally, not via string-matching). But a **valid** expression under that grammar
— an unbounded `**` exponent, e.g. `99999999999999 ** 99999999999999` — is itself a
resource-exhaustion vector: `_calculator_handler` called `safe_eval_arithmetic`
synchronously inside an `async def`, so the computation never yields control back to
the event loop, meaning `run_tool`'s `asyncio.wait_for` timeout literally cannot
preempt it once it starts (a single crafted expression could block every concurrent
request on this single-worker backend). code-reviewer's first pass caught this and
correctly graded it CRITICAL despite the tool layer not being wired into the live
graph yet — "ships as-is otherwise" was the right call. Fixed three ways: (1)
`_eval_node`'s `ast.Pow` branch now checks `abs(exponent) > _MAX_POW_EXPONENT` (1000)
*before* calling `operator.pow`, confirmed by hand-tracing recursive `**` chains that
the check fires strictly pre-compute at every level, not just the outermost; (2)
`safe_eval_arithmetic` rejects expressions over `_MAX_EXPRESSION_LENGTH` (200 chars)
before `ast.parse`, incidentally bounding recursion depth too; (3)
`_calculator_handler` now offloads via `asyncio.to_thread` as defense-in-depth, so the
timeout stays meaningful even against a future bound-check oversight. Re-verified by a
second, skeptical code-reviewer pass (explicitly asked to confirm the fix rather than
take it on faith) — confirmed the exponent check precedes the `pow` call on every
recursion level, the bounds are generous for real use (`2**1000` and even a
14000-digit base raised to 1000 both compute in negligible time) yet tight enough to
block the original PoC, and no other resource-exhaustion vector was missed.

New `tests/test_agent_tools.py` (20 tests): registry assembly, `run_tool`
success/timeout/exception/never-raises, calculator correctness + the adversarial
sandbox-escape cases above + oversized-exponent/overlong-expression regression tests
+ a static `\beval\(`/`\bexec\(` source-scan (regexed to dodge false-positiving on the
module's own `safe_eval_arithmetic`/`_eval_node` names), get_datetime UTC format.
265 backend tests green (up from 235). build-validator PASS (both the A.3/A.4
tool-gating scope cut and the get_datetime user-local gap explicitly flagged as
accepted, not silently passed over). No security-auditor run — per the plan, that's
mandatory only for A.3's SSRF surface (in A.9); A.2 touches no secrets/config/auth,
and the calculator's actual security-relevant surface (the sandbox + the DoS bug
above) got two independent code-reviewer passes instead.

Next: A.3 (BYOK search keys + `web_search`/`fetch_url` tools + SSRF guard +
citations).

---

### [2026-07-13] — Phase A / A.3: internet access, with the mandatory security audit

BYOK: `key_store.VALID_PROVIDERS` gains `tavily`/`brave` (same AES-GCM storage as LLM
provider keys — no new storage mechanism needed). `ApiKeysSection.tsx` gets a
"Search (optional)" group, same `ProviderRow` UX as the LLM key rows.

`agent/tools/web_search.py`: Tavily `POST` preferred, Brave `GET` fallback,
`WEB_SEARCH_MAX_RESULTS=5`, numbered `title — url — snippet` observations. No key →
absent from the toolset, no error surfaced (per the locked decision).

`agent/tools/fetch_url.py`: the security-relevant piece of this step. `guard_url()`
implements the plan's exact spec — scheme allowlist (http/https only), hostname
resolved via `asyncio`'s `loop.getaddrinfo` (not blocking `socket.getaddrinfo`
directly), every resolved IP checked against private/loopback/link-local/reserved/
multicast/unspecified ranges via the `ipaddress` stdlib, called before every request
including each redirect hop (`follow_redirects=False`, manual redirect loop,
`max_redirects=3`). `trafilatura.extract` for readable-text extraction, truncated to
`FETCH_MAX_CHARS=8000`.

**Two real gaps found by code review, both fixed before the security audit:**
1. IPv4-mapped IPv6 addresses (`::ffff:127.0.0.1`, `::ffff:169.254.169.254`) are a
   known SSRF-filter bypass — Python's `IPv6Address.is_private`/`is_loopback` don't
   inspect the embedded IPv4 payload. Fixed: `_is_blocked_ip` now unmaps and
   re-checks. Two regression tests added.
2. Forward-looking: citation chips (`Message.tsx`) rendered `href={c.url}` with no
   scheme validation. Citations aren't live yet (nothing calls `citation_event` until
   A.6), so this was flagged as "not yet reachable, fix before A.6 wires it up" —
   fixed proactively anyway since it was cheap: hrefs are now filtered to
   `^https?:\/\//i` before rendering.

**Mandatory security-auditor pass** (per the plan, this step touches new outbound
HTTP from user-influenced URLs) returned PASS, 0 CRITICAL, with an explicit verdict
on the one accepted residual: a TOCTOU/DNS-rebinding gap where `guard_url`'s hostname
resolution and httpx's own connection-time resolution are two independent DNS
lookups a few milliseconds apart — a malicious/compromised DNS server could in
principle answer differently between them. The plan's literal spec is hostname-based
re-checking (not IP-pinning the connection), so this is a designed limitation, not an
oversight; the auditor judged it non-blocking for a personal BYOK chat tool, with an
explicit note to revisit via IP-pinning if this tool set is ever pointed at a
deployment with sensitive internal services reachable from the backend's network.
One informational NOTE also recorded (no raw-response byte cap before extraction —
truncation currently happens post-extraction, not on the wire — future hardening,
non-blocking, not fixed this pass).

`events.py` gains `citation_event(url, title)` — pure plumbing, no caller yet (the
execute loop that would call it is A.6, out of scope this session, same incremental
pattern as A.1/A.2). Frontend: `client.ts` `onCitation`, `ChatPage.tsx` appends
de-duped-by-URL citations onto the assistant message, `Message.tsx` renders source
chips that stay visible independent of the trace-collapse toggle (get ahead of A.8's
"citations stay visible when collapsed" requirement now, rather than reworking it
later).

New `tests/test_agent_tools_search.py` (21 tests): registry gating (fetch_url
always-on, web_search key-gated), web_search provider-mocked (Tavily-preferred,
Brave-fallback, no-key TOOL_ERROR), and a full SSRF matrix (non-http scheme, loopback
literal, localhost hostname, `10.x`, the `169.254.169.254` cloud-metadata IP,
DNS-resolution-failure, both IPv4-mapped-IPv6 cases, redirect-to-private on the
second hop, max-redirects exceeded). One now-stale A.2 test loosened (it hardcoded
the exact toolset as exactly `{calculator, get_datetime}`, which A.3 legitimately
changes). 286 backend tests green (up from 265); `tsc --noEmit` + `npm run build`
clean.

**Aside, not a code issue:** the backend Docker image rebuild for this step took
much longer than A.1/A.2's (~25+ min vs. seconds) — adding `trafilatura` to
`requirements.txt` invalidated the single-layer `pip install` Docker cache, forcing
every dependency (numpy, langgraph, google-api libs, etc.) to re-download from
scratch over an unusually slow connection this session (~50-70 KB/s). Not a bug,
just a heads-up for future steps that touch `requirements.txt`.

Next: A.4 (`doc_search` replaces whole-doc injection) **[Phase M]**.

---

### [2026-07-13] — Phase A / A.4: doc_search replaces whole-doc injection

Deletes the last remnant of the old "inject the entire uploaded document into
every chat message" design — content now reaches the model exclusively via a
scoped `doc_search` tool, same retrieval machinery Phase M already built for
chat history, filtered by a new `kind` column.

**Upload path (`routes/upload.py`).** Previously had no concept of which
chat a document belonged to at all — `PAWN/uploads/{doc_id}.txt` was pure
global blob storage, no scope, nothing indexed. Now accepts an optional
`conversation_id` form field; if present, lazy-creates the conversation
first (small `_ensure_conversation` helper mirroring `chat.py`'s
`_create_with_id` — not literally shared/imported since that helper isn't
exported, judged an acceptable small duplication rather than a cross-module
coupling for 5 lines), resolves scope, and schedules the new
`memory/indexer.py::index_document_task` as a background task. No
`conversation_id` → the doc is stored but never indexed (there's no scope to
index into — matches the plan's "no unscoped document rows can exist"
guarantee, since the alternative would be indexing to nowhere).

**Where document chunks live is different from message chunks, on purpose.**
`index_document_task` reuses `chunk_turn` as-is (it was already text-agnostic
— just needed `[{"content": doc_text}]`) but writes straight to Postgres,
never to the chat's `rag_chunks.jsonl`. Per the plan: `PAWN/uploads/<doc_id>.txt`
is itself the rebuild source of truth for documents — re-chunking it fresh on
`rebuild_index` is simpler and avoids duplicating the same text in two
places on Drive. The one thing that DOES need to persist on Drive (not just
Postgres) is *which* doc_ids are attached to which chat, since that's not
derivable from the doc text alone — new `conversations_drive.add_attached_doc`/
`get_attached_docs` store `{doc_id, filename}` records in each chat's
`meta.json`. This is what makes `rebuild_index`'s new document loop survive
a full manual Postgres truncate (§M.7 item 7's exact disaster-recovery
scenario) — without it, a wiped `memory_chunks` table would have no way to
even discover which documents used to belong to a scope. Added a dedicated
test proving this (`test_rebuild_index_survives_postgres_wipe_via_drive_attachment_record`
— attaches a doc via Drive only, zero prior Postgres rows, confirms rebuild
still recovers it).

**Schema change required a DROP, not just CREATE OR REPLACE.**
`match_scoped_chunks`/`search_scoped_chunks` (Phase M) returned
`(id, conv_id, text[, score])` — no `kind`/`doc_id`, fine while every row was
`kind='message'`. `doc_search` needs to know which chunk came from which
upload, so both functions now also return `kind`/`doc_id`. Postgres won't let
`CREATE OR REPLACE FUNCTION` change a `RETURNS TABLE` shape — needed an
explicit `DROP FUNCTION` first, both in `schema.sql` (for a future fresh
volume) and in a new migration file (`2026-07_doc_search_kind_return.sql`,
same pattern as Phase M's own migration) applied live to the local dev
Postgres this session (`docker compose exec postgres psql ... < migration.sql`
— confirmed clean `DROP FUNCTION`/`CREATE FUNCTION` output).

**`retrieve()`'s `match_kind` used to be a hardcoded literal.** Both SQL calls
passed the string `"message"` inline — Phase M's own comment already flagged
this as inert scaffolding for this exact follow-on plan. Now a real parameter,
defaulting to `None` (search both kinds) so existing callers don't silently
change behavior unless they opt in. One real behavior-preservation catch: the
OLD ReAct graph node (`agent/graph.py::search_memory_node`, not yet deleted —
that's A.6) called `retrieve()` without `match_kind` at all, which used to
implicitly mean "message" via the old hardcoded literal. Left as `None` it
would now silently start blending document chunks into the old ReAct
protocol's memory search results — not wrong exactly, but a scope creep this
step shouldn't introduce. Fixed by making that call site pass
`match_kind="message"` explicitly, one line, preserves exact pre-A.4 behavior
until A.6 replaces the whole node with the new `search_memory` tool.

**`chat.py`'s whole-doc injection deleted outright** (not stubbed, not
feature-flagged) — the `if req.doc_id: doc_text = ...; system_content = ...`
block that used to prepend the entire document as a system message on every
turn. `doc_id` stays on `ChatRequest` for frontend backward-compat but is
now genuinely inert in `/chat`; `needs_drive` simplified since doc_id no
longer triggers a Drive load there. Removed the now-unused `documents_drive`
import.

**New tools** (`agent/tools/doc_search.py`, `search_memory.py`) are thin
`retrieve(..., match_kind=...)` wrappers, added to the toolset only when
`ctx.scope_type is not None` (stateless chats get neither — same pattern as
A.3's key-gated `web_search`). `doc_search` does a best-effort
`doc_id -> filename` lookup via the hit's originating chat's
`get_attached_docs` so observations read `[report.pdf] ...text...` instead of
a bare UUID — falls back to the doc_id if Drive/meta lookup fails, never
blocks the observation on that.

**Frontend draft-chat edge, implemented exactly as locked.** `handleUpload`
in `ChatPage.tsx` now promotes the draft conversation first — the identical
`activeConvId ?? createConversation()` / `promoteDraft` / `navigate` sequence
`handleSend` already used for the first message — before calling `uploadDoc`,
so uploading into a brand-new empty chat always has a real conversation_id to
scope against.

**build-validator caught a real gap on its first pass:** the plan's test list
explicitly calls for a "cross-scope doc isolation" test, and while message-kind
isolation was already proven by a Phase M test, nothing specifically indexed a
`kind='document'` chunk under one scope and confirmed a different scope's
`doc_search` call couldn't see it. Added
`test_retrieve_cross_scope_document_isolation_guarantee` (mirrors the existing
message-kind isolation test, `match_kind='document'`) before re-validating.
Also caught two Phase M tests that would've silently broken from this step's
signature changes (`add_chunk`'s new `kind`/`doc_id` columns changing its
positional-params assertion; `retrieve()`'s default no longer implicitly
meaning "message") — both fixed in the same pass, not deferred.

304 backend tests green (up from 286); `tsc --noEmit` + `npm run build` clean.
code-reviewer PASS (0 CRITICAL/WARN — verified the Drive-then-Postgres write
ordering in `index_document_task` matches `index_turn_task`'s established
invariant, confirmed no lock-race/deadlock between concurrent doc-indexing
and turn-indexing on the same chat since both serialize on the same
`get_conv_lock` key, confirmed the SQL migration's `DROP`+`CREATE` is correct
and the returned columns are accessed by name not position so ordering
doesn't matter). No security-auditor run — no new outbound HTTP/secrets/auth
surface, this step is pure Postgres/Drive plumbing reusing Phase M's existing
security posture.

**Aside:** hit one flaky native-extension crash (`exit 135`, a `httpx2`
client teardown inside `test_summarize.py`) mid-full-suite-run — reproduced
clean in isolation and on a full re-run immediately after, confirmed
transient/environmental, not a real regression from this diff.

Next: A.5 (model router — `core/router.py`, heuristic + LLM-fallback
classifier, `ROLE_LEVELS`).

---

### [2026-07-13] — Phase A / A.5: model router (last step this session, A.1-A.5 done)

New `core/router.py`, self-contained (deliberately not wired into
`agent/graph.py` yet — that's A.6). `classify()` implements the plan's
heuristic tier exactly: an OR of 5 heavy triggers (char threshold, code
fence, an 8-keyword set matched with `\b` word-boundary regex so "why"
doesn't false-positive inside "whystuff", a doc attached, the prior turn
used tools), falling to light only when the text is under the light
threshold AND none of those fired, and to a genuinely ambiguous middle band
otherwise. `needs_agent` layers on top: heavy OR a URL is present OR (a
search key is configured AND the message matches a time-sensitive keyword
set) — the last one deliberately gated on having an actual search key,
since flagging "needs_agent" for a tool that doesn't exist would be useless.

The LLM fallback tier only fires for that ambiguous middle band. One
`chat_complete` call on the `fast` capability level, a fixed prompt asking
for exactly one word. Per the plan's explicit "fail toward capability, not
away" instruction, any failure anywhere in this tier — no model available,
an upstream error, an unparseable response — defaults to `heavy`/
`needs_agent=True` rather than guessing light and risking an under-powered
answer. code-reviewer's one real finding: this fallback swallowed its
exception with no logging, which would make a broken fast-tier model
silently invisible in production (always "successfully" defaulting to
heavy with no signal anything was wrong). Fixed: logs to stderr before
returning the default.

Two small implementation calls, both explicitly reviewed and accepted as
reasonable rather than deviations: (1) `classify()`'s real signature has 4
more params than the plan's literal 3-arg text (`resolver`, `rate_limiter`,
`user_id`, `has_search_key`) — the LLM fallback tier cannot make a model
call without a resolver, so this is structurally necessary, not scope
creep; (2) added a `resolve_final_model(difficulty, user_model_id, resolver)`
helper not literally named in the plan, specifically because the plan's own
test list requires "user override respected" as a testable behavior, and
`classify()` itself has no natural place to thread a `user_model_id`
through without conflating its `RouteDecision` return shape with final-model
resolution (an A.6/graph concern). Returns the user's explicit pick verbatim
when given, bypassing the resolver entirely; otherwise resolves
`ROLE_LEVELS['final_heavy'/'final_light']`.

New `tests/test_router.py` (29 tests) covers every heavy trigger
individually (including the word-boundary negative case), the light path,
all three `needs_agent` triggers, fallback-not-invoked when the heuristic
tier already decided (both directions), fallback-invoked only for the
ambiguous band, response parsing, all three failure-defaults-heavy paths
(parse failure, model exception, no resolver passed at all), an exact
`ROLE_LEVELS` dict match, and the `resolve_final_model` override/fallback
behavior. 333 backend tests green (up from 304).

code-reviewer PASS (0 CRITICAL/WARN; the logging fix above plus a couple of
non-blocking NOTEs — keyword-list micro-optimization, no explicit prompt
truncation before the ambiguous-band text reaches the fallback model, both
judged not worth acting on given the 1500-char heavy threshold already
bounds the input). build-validator PASS, verified every trigger/threshold/
keyword/ROLE_LEVELS-entry against the diff line-by-line plus a live
`pytest` run. No security-auditor run (pure classification logic, same
`chat_complete` path A.1 already covers, no new secrets/auth surface).

**Phase A status at end of session: A.1-A.5 all done and committed.** A.6
(orchestrator graph v2 — the full LangGraph rewrite consuming everything
A.1-A.5 built) is the next, largest, and riskiest remaining step per the
plan's own risk section.

---

### [2026-07-13] — Phase M complete: embedding fix + M.6 (projects UI) + M.7 (automatable parts)

Closing out Phase M (`plan_memory_scoping.md`) this session. Picked up mid-M.6 after
an interruption; reconciled the in-progress diff against the plan by hand (read every
new/changed file, compared against §M.6's exact spec) rather than restarting, per the
user's instruction — the interrupted work was in good shape and needed only the fixes
below.

**Embedding-model gap, fixed first.** The prior session's registry-refresh had already
identified that `text-embedding-004` was shut down 2026-01-14 and the correct
replacement is `gemini-embedding-2` (not `gemini-embedding-001`, which shuts down
2026-07-14), but the actual code swap hadn't landed yet — `memory/embed.py` was still
calling the dead model on every embed request. Fixed: `_gemini_embed` now calls
`gemini-embedding-2` with `outputDimensionality: 768` (auto-normalized Matryoshka
truncation, no manual normalization needed). Registry: `text-embedding-004` +
its endpoint deactivated (kept for history), `gemini-embedding-2` + its endpoint
added and active. `postgres/schema.sql`'s `vector(768)` column comment updated —
**no schema/migration change**, the dimension was already correct. `test_registry.py`
updated for two internal embedding entries. Verified via `docker compose exec backend
pytest` (not a bare local `python -m pytest` — a stale `/app/data` artifact on this
Windows dev machine from a much earlier local run, predating this whole registry
refresh, was silently shadowing the real repo registry files when run outside Docker;
caught by comparing local-vs-container results, not by trusting the first green run).
Committed standalone: `fix: swap dead text-embedding-004 -> gemini-embedding-2
(768-dim), M.1 gap`.
**Known follow-up (real chats only, not this dev machine):** any chat indexed while
the model was dead has chunks with missing/broken embeddings — needs a
`POST /memory/rebuild` per affected scope once there's a real Drive-linked stack to
run it against. Folded into M.7's live checklist rather than run now.

**M.6 — frontend projects UI + move flows.** Reconciled the interrupted diff against
plan §M.6 file-by-file: `types.ts`/`client.ts` additions, `useConversationStore`'s
`projects` list + move mutators, `syncQueue`'s four new op kinds
(`createProject`/`renameProject`/`deleteProject`/`moveChat`, exactly as named in the
plan), `ProjectSection.tsx`/`ProjectRow.tsx` (split out of `Sidebar.tsx` per
frontend.md's 150-line rule), shared `KebabMenu.tsx`/`ConfirmDialog.tsx`, three of the
plan's four confirm dialogs, `/project/:projectId` + `/project/:projectId/chat/:id`
routing, and backend `routes/memory.py` (rebuild/clear, both scope-checked + 404'd)
surfaced via kebab "Memory ▸" submenus — all present and correct against the spec.
Added one gap of my own: a test for `GET /conversations` now tagging project-scoped
chats with their `project_id` (the endpoint's list logic changed to
`list_all_conversations` but had no test coverage for the new behavior).
Ran the build-step skill's test-runner + code-reviewer over the diff (implementation
already written, so skipped straight to verification): 227 backend tests green,
`tsc --noEmit`/`npm run build` clean.
**code-reviewer found 1 CRITICAL, fixed:** `syncQueue.ts`'s `moveChat` op coalescing
recomputed `fromProjectId` (the source project a move-out needs to call
`DELETE /projects/{id}/chats/{conv_id}` against) from the store's live ref on every
re-enqueue, not just the first. Since the ref reflects the op's own already-applied
optimistic update, a second rapid remove-from-project (double-click, or any re-render
landing between two clicks) would read the project as already-cleared and silently
overwrite the correct captured source with `null` — the queued op would then no-op at
drain time with no error, so the UI showed "removed" while the backend never got the
call: a real memory-isolation leak (the project's other chats would keep retrieving
from a chat the UI claimed was no longer shared). Fixed: `fromProjectId` is now
captured once, only when a queue entry is first created.
**1 WARN found, fixed:** the plan's M.6 text says "Clear memory" gets a confirm
dialog like the other three flows; the first pass wired it straight to the kebab
click with no gate. Added the fourth `ConfirmDialog` (destructive-styled).
**2 NOTEs deferred** (pre-existing bare-except pattern in `conversations_drive.py`;
`memory.py`'s Postgres delete has no try/except unlike its sibling
`_delete_chunks` — both low-severity, rebuildable-index concerns, out of this step's
scope). No security-auditor run (same call as M.4/M.5 — no secrets/config/auth
touched). Committed: `feat: Phase M / M.6 - projects UI + move flows`.

**M.7 — automatable parts only.** Full backend suite green, frontend gates clean,
code-reviewer run (above). **The live verification checklist (plan §M.7 items 1-7,
plus the embedding re-index check) was not run** — it needs a real Drive-linked
account and the docker compose stack up, with the user driving the browser/curl
steps. Listed as an explicit numbered pending list in `build_tracker.md`'s M.7 entry
rather than silently folded into a green checkmark. M.7 is marked `[~]` (in
progress), not `[x]`, until those are confirmed.

**Phase M is now code-complete on `dev`** — schema+scoped SQL (M.1), Drive
chats/projects layout with legacy migration (M.2), chunker/indexer write path (M.3),
scoped retrieval + agent wiring (M.4), projects API + two-way moves (M.5), full
projects UI (M.6), plus the embedding-model fix. Docs (`build_tracker.md`,
`current_state.md`, this entry) updated to reflect that only the live-verification
checklist remains before M.7 (and the phase) can be marked fully done.

**Next phase note (not started, out of this session):** `plan_chat_agent_refinement.md`
has `[Phase M]` tags written against the *planned* M design from before this
implementation existed. Those need a re-verification pass against the real code
(file/function names, `resolve_scope`, the `kind` param, `memory_hit` payload shape,
`chats/`/`projects/` Drive paths) before any Phase A work starts — a separate session
with the user, per explicit instruction this session.

---

### [2026-07-13] — Registry refresh (registry-refresh skill, applied via Cowork session)

Sources verified directly (not just the CLI agent's report): GitHub changelog
2026-07-01, Gemini deprecations page, Gemini embeddings docs, Gemini rate-limits page.

- Deactivated 6 endpoints: `ep-llama-3.3-70b-cerebras` + `ep-qwen-3-32b-cerebras`
  (Cerebras deprecated 2026-02-16), `ep-deepseek-r1-openrouter` (:free tier removed),
  `ep-llama-3.3-70b-github` + `ep-deepseek-r1-github` (GitHub Models retires
  2026-07-30; brownouts 07-16/07-23 — deactivated ahead of them),
  `ep-llama-3.3-70b-openrouter` (free variant ends 2026-07-19 — proactive).
- `qwen-3-32b` model → `active: false` (zero endpoints left).
- `last_verified` bumped to 2026-07-13 on the 7 endpoints re-verified today.
- REJECTED from the CLI agent's proposal: 4 Gemini rate-limit field changes — the
  rate-limits docs page no longer publishes per-model free-tier numbers (moved into
  AI Studio account view), so the values were unverifiable; skill rule: never invent
  limits. Existing stored limits left as-is.
- URGENT finding confirmed + CORRECTED: `text-embedding-004` shut down 2026-01-14.
  The CLI agent recommended migrating to `gemini-embedding-001` — WRONG target: that
  model shuts down 2026-07-14 (tomorrow). Correct replacement is
  `gemini-embedding-2` (supports `output_dimensionality=768`, auto-normalized →
  `vector(768)` schema keeps working). Fix folded into Phase M step M.1
  (`plan_memory_scoping.md`), which wipes `memory_chunks` anyway, so no re-embed
  migration is needed. Registry embedding entries deliberately untouched today per
  the skill's hard rule.
- Heads-up for next refresh: groq `llama-3.3-70b-versatile` deprecation notice for
  2026-08-16; `gemini-2.5-flash`/`-lite` earliest shutdown 2026-10-16 (successors:
  `gemini-3.5-flash` / `gemini-3.1-flash-lite`); new Gemini 3.x models exist but not
  added (context/limits unverified this pass).
- **Also found and fixed while committing this refresh:** `.gitignore`'s bare `data/`
  pattern was silently matching `backend/data/registry/*.json` too — the model
  registry (per `.claude/CLAUDE.md`: "data, not code," meant to be committed) had
  **never actually been tracked in git**, on any branch, since the file was created.
  Every prior registry-refresh session's edits only ever existed in the working
  tree/Docker volume, not in version control. Narrowed the ignore rule to the three
  actual runtime-data paths (`backend/data/conversations/`, `backend/data/memory/`,
  `backend/data/checkpoints.db`) so `registry/` is no longer swept up. This refresh
  is the first one to actually land in git history.
- Validation: JSON parse + referential integrity clean; every active model has ≥1
  active endpoint (llama-3.3-70b: groq+hf; deepseek-r1: hf only). Full pytest run
  completed this session (see below).

---

### [2026-07-13] — Phase M / M.1: memory-scoping schema + migration

Kicked off Phase M (`workspace/plan/plan_memory_scoping.md`, prescriptive, locked 2026-07-13): drops the always-cross-chat memory tier for strict per-chat/per-project isolation. Session scope: M.1 and M.2 only.

**M.1 — Schema + migration file.** `postgres/schema.sql`'s `memory_chunks` redefined (drop+recreate) with `chunk_id`/`scope_type`/`scope_id`/`conv_id`/`kind`/`doc_id`/`msg_index` columns and a `unique(user_id, chunk_id)` constraint (idempotency key for re-indexing). Old `match_memory_chunks`/`search_memory_chunks` (exclude-active-conv semantics) dropped; new `match_scoped_chunks`/`search_scoped_chunks` (strict equality on `scope_type`/`scope_id` — the inverse of the old exclude filter) added. New `postgres/migrations/2026-07_memory_scoping.sql` for already-initialized volumes (schema.sql alone only runs on a fresh volume) — applied to local dev Postgres via `docker compose exec -T postgres psql -U pawn -d pawn < postgres/migrations/2026-07_memory_scoping.sql`, verified live (`\d memory_chunks`, `\df match_scoped_chunks`/`search_scoped_chunks`, `\df match_memory_chunks` → 0 rows). `memory/index.py`'s `add_chunk` signature changed to `(user_id, scope_type, scope_id, conv_id, chunk_id, msg_index, text, embedding)`, upserting via `on conflict (user_id, chunk_id) do update`. `test_rag.py`'s two `add_chunk` tests updated to the new signature + one new upsert-idempotency test. 165 backend tests green.

**Known, accepted transitional gap (by plan design, sequenced M.1→M.2→M.3→M.4):** `memory/retrieve.py` still calls the now-dropped `match_memory_chunks`/`search_memory_chunks` by name — every `retrieve()` call hits "function does not exist," caught by its own fail-soft except blocks, silently returning `[]`. Chat memory retrieval is fully inert until M.4 rewrites `retrieve.py` to the scoped signature. `memory/summarize.py`'s `add_chunk` call site (line 101) still uses the old 4-arg form and will `TypeError` on every summary write, caught by its surrounding `except Exception` (fails soft) — deferred to M.3, which replaces this call path with the new chunker/indexer. Both gaps documented inline (code comments) and here; not regressions, not fixed this step — next steps in the same phase close them.

code-reviewer PASS (0 CRITICAL; 1 WARN — retrieve.py's silent-inert-until-M.4 gap wasn't documented anywhere, fixed with a module docstring note; 2 NOTE — summarize.py's stale call site got an inline TODO comment, migration file got the column-purpose comments mirrored from schema.sql for parity). No security-auditor run (M.1 touches no secrets/config/auth).

**M.2 — Drive storage layer: new layout + projects.** `storage/drive.py` gains `move_item(item_id, new_parent_id, old_parent_id)` (single `files().update(addParents=..., removeParents=...)` call, lock-guarded, cache-invalidated). `storage/conversations_drive.py` retargeted from flat `PAWN/conversations/{conv_id}/` to `PAWN/conversations/chats/{conv_id}/`; new `_locate_conv_folder` resolves a chat wherever its scope places it (chats/ or projects/{pid}/ — folder placement alone is the scope, no membership table, per plan decision #7); new `load_rag_chunks`/`append_rag_chunks` per-chat helpers (`rag_chunks.jsonl`, full-file rewrite pattern matching `messages.jsonl`); one-time automatic legacy-folder migration (`PAWN/conversations/{conv_id}/` → `chats/{conv_id}/`, detected by layout, no flag file, logs each move to stderr). New `storage/projects_drive.py` — full project CRUD (`create_project` idempotent on client-generated id, `list_projects`, `get_project_meta`, `rename_project` json-only, `delete_project` cascade via Drive's own recursive folder delete, `list_project_chats`) + `move_chat` (thin wrapper over `drive.move_item`, used both directions per decision #8). `tests/fake_drive.py` gains `move_item`. New `backend/tests/test_projects_drive.py` (15 tests: chats-layout, migration + idempotency, project CRUD, cascade delete, move-in/move-out both directions incl. post-move write correctness, rag_chunks roundtrip). 180 backend tests green (rebuilt the backend Docker image first — `develop.watch` doesn't sync `backend/tests/`, so a stale container silently ran old tests twice this session; rebuild-before-trust is now the standing move for this project).

code-reviewer found 1 CRITICAL on first pass: the legacy-migration "already checked" memo was a module-level `set` keyed by `id(drive)` — since `DriveStorage` instances are TTL-cached per user by `drive_factory` and evicted/GC'd, CPython's allocator can reuse a freed instance's address for a new object, causing a real user's migration to be silently skipped forever (their pre-Phase-M chats would vanish from `list_conversations` with no error). Fixed: the flag is now an attribute set directly on the `drive` instance itself (`getattr`/`setattr(drive, "_pawn_legacy_migration_checked", ...)`), tying its lifetime to the object's own lifetime instead of a global id()-keyed table. Re-reviewed PASS. Two lower-severity races (migration check-then-act not lock-guarded; `_conv_folder_for_write`'s create-fallback could in principle race a future move) were left as documented, deferred items — no move code path exists yet in M.2, so neither is currently exploitable; both fall under M.5's per-`(user,conv)` locking work. No security-auditor run (M.2 touches no secrets/config/auth).

### [2026-07-13] — Phase M / M.3: chunker + write path (indexing every turn)

New `backend/app/memory/chunker.py` — `chunk_turn(turn_msgs, msg_index_start)` splits a committed turn's messages into fixed-size overlapping character chunks (`MEMORY_CHUNK_TOKENS=400`/`MEMORY_CHUNK_OVERLAP_TOKENS=50` in `app/constants.py`, token count approximated as `len(text)//4`, no tokenizer dependency); each chunk keeps its source message's `msg_index`. New `backend/app/memory/indexer.py`: `resolve_scope(user_id, conv_id, drive=None)` walks Drive folder placement (via new `conversations_drive.resolve_conv_scope`) and caches the result in-process (`SCOPE_CACHE_TTL_SECONDS=300`, thread-locked dict, `evict_scope` for M.5's moves); `index_turn_task(user_id, conv_id, scope, turn_msgs)` — the background task scheduled from `chat.py`'s existing persist-turn block (same place `auto_title_background_task`/`summarize_conversation_task` are scheduled) — chunks the turn, appends records to the chat's own `rag_chunks.jsonl` on Drive **first** (source of truth; a Drive failure aborts with zero Postgres writes), then embeds each chunk and upserts scoped rows into Postgres (a per-chunk embed failure is caught and skipped, not fatal — Drive already has the chunk, recoverable via rebuild); `rebuild_index(user_id, scope_type, scope_id)` deletes the scope's Postgres rows and re-derives them from Drive (all chats under a project, for project scope). Stateless chats (`conversation_id=None`) are never indexed — `chat.py` only schedules the task inside the existing `if req.conversation_id and success ...` block, and the task itself guards on `conv_id` too.

`routes/conversations.py`'s `DELETE /conversations/{id}` now also deletes that chat's Postgres `memory_chunks` rows (`_delete_chunks`, best-effort — runs after the Drive folder is already gone, failures logged not raised, so a Postgres outage can't block the delete) — closes a pre-existing gap where conversation delete left Postgres untouched. `memory/summarize.py`'s stale 4-arg `add_chunk` call (documented gap from M.1, TypeError'd on every summary write, caught fail-soft) is now routed through `index_turn_task` — closes the last known transitional gap from M.1/M.2.

19 new/changed tests (`test_chunker.py`, `test_indexer.py`, +1 in `test_conversations.py`): chunk-splitting incl. overlap and empty-message skipping; `resolve_scope` standalone/project/missing/cache-hit/cache-evict; `index_turn_task` end-to-end via FakeDrive with mocked `embed`/`add_chunk` (chat scope, project scope, stateless no-op, Drive-unavailable no-op, **Drive-write-failure aborts before any Postgres write** — the core M.3 invariant — and a partial-embed-failure-doesn't-block-other-chunks case); `rebuild_index` for both chat and project scope; delete-cleans-chunks. 199 backend tests green (rebuilt the backend Docker image before trusting the count — same standing lesson from M.2, `develop.watch` doesn't sync `backend/tests/` for a plain `exec`).

code-reviewer PASS (0 CRITICAL). One real bug caught and fixed before review even started: the new `conversations_drive.resolve_conv_scope` helper initially returned a project chat's scope as `("project", <Drive's internal folder id>)` instead of `("project", <project_id>)` — project folders are named `<id>` only (per M.2's Drive-layout convention), so the logical project_id is the folder's `name`, not its Drive-internal `id`; caught immediately by `test_resolve_scope_project_chat`/`test_index_turn_task_project_scope` failing with a `folder-8` vs `proj-1` mismatch. 2 WARN from the review, both addressed with clarifying comments rather than code changes (accepted tradeoffs, not regressions): (1) `index_turn_task`'s `msg_index_start` is derived from a fresh `load_messages` read rather than a count passed through from `chat.py`, so two rapid concurrent turns on the same chat could in principle mis-attribute `msg_index` on their chunks — blast radius is provenance/display metadata only, never scope or retrieval correctness, and fixing it would require deviating from the plan's locked `index_turn_task` signature; (2) `summarize.py`'s new `except Exception` around the `index_turn_task` call is intentionally broad (last-resort safety net for a fire-and-forget background task with no HTTP response to attach an error to) — now has an explicit comment saying so. No security-auditor run (M.3 touches no secrets/config/auth).

### [2026-07-13] — Phase M / M.4: retrieval rewrite + agent wiring

`backend/app/memory/retrieve.py` rewritten to a scoped signature: `retrieve(query, user_id, scope_type, scope_id, top_k=MEMORY_TOP_K)` (`MEMORY_TOP_K=4` new in `app/constants.py`), calling the new `match_scoped_chunks`/`search_scoped_chunks` SQL functions (strict `scope_type`/`scope_id` equality, the inverse of the old exclude-active-conv filter) instead of the dropped `match_memory_chunks`/`search_memory_chunks`; RRF fusion logic unchanged. `backend/app/agent/graph.py`: **two call sites changed.** `load_context_node` no longer retrieves at all — it's now a pure no-op (`return {}`); `retrieved_memory` starts `[]` in `chat.py`'s graph inputs and is populated only if the agent itself chooses the `search_memory` action. `search_memory_node` switched to the scoped `retrieve()` call, guarded on `scope_type`/`scope_id` both being truthy (stateless chats have neither, so they never reach Postgres even if the agent tries), and its `memory_hit` custom-event dispatch now carries `scope`/`source_conv_id` alongside `summary`. `AgentState` gains `scope_type`/`scope_id` fields. The agent's `search_memory` action prompt text updated to frame RAG as an escape hatch ("only reach for this when you're actually missing something"), not a per-turn habit, per plan decision #5.

`backend/app/routes/chat.py` resolves scope once per request via M.3's `memory.indexer.resolve_scope(user_id, conv_id, drive)` (only when `conversation_id` is present; stays `None`/`None` for stateless chats) and threads `scope_type`/`scope_id` into the LangGraph inputs dict; the SSE dispatch for the `memory_hit` custom event now forwards `scope`/`source_conv_id` into `events.memory_hit_event`. `backend/app/events.py`'s `memory_hit_event(summary, scope="", source_conv_id="")` — additive, only includes the new keys in the JSON payload when non-empty (no clutter on ordinary calls). Frontend: `types.ts`'s `TraceEvent` gains `scope`/`sourceConvId`; `client.ts`'s `onMemoryHit` callback threads them through; `ChatPage.tsx` carries them into trace state; `Message.tsx` shows a badge on a memory-hit card only for `scope === 'project'` hits, naming the source chat (chat-scope hits, the common case, stay unbadged). `npm run build` clean.

Tests: `test_agent.py`'s `test_load_context_node_no_longer_retrieves` (asserts `retrieve`/`adispatch_custom_event` are never called from that node — the plan's core M.4 removal), `test_search_memory_node` (updated to the scoped signature + asserts the `memory_hit` payload carries `scope`/`source_conv_id`), new `test_search_memory_node_stateless_never_queries`. `test_rag.py`: all `retrieve()` tests updated to the scoped signature; new `test_retrieve_cross_scope_miss_isolation_guarantee` (**the core isolation test of this entire plan** — a chunk indexed under chat A's scope must never surface when chat B, a different scope_id, queries its own scope, proven via a Python-side fake that replays the SQL functions' exact WHERE-equality filtering keyed off the params `retrieve()` actually passes); new `test_retrieve_project_scope_shared_across_member_chats` (a project-scoped chunk written by one member chat is retrievable by the project's own scope, but not by that same chat's standalone `'chat'` scope); `test_chat_yields_memory_hit_events` reworked into a full `/chat` round-trip driven by a scripted 3-call mock LLM sequence (search_memory action → final action → synthesis) since the agent no longer auto-retrieves, asserting the emitted `memory_hit` event's `scope`/`source_conv_id`; new `test_stateless_chat_never_queries_memory` (end-to-end: even when the agent chooses `search_memory` on a stateless request, `retrieve()` is never called and no `memory_hit` event fires). 203 backend tests green (up from 199).

code-reviewer PASS (0 CRITICAL, only trivial NOTEs — a stale `match_memory_chunks` reference in a `postgres_client.py` comment, fixed). All five isolation/wiring invariants independently re-verified by the reviewer directly against the diff (SQL-level scope equality, no reintroduced retrieval path in `load_context_node`, stateless chats never hit Postgres, `memory_hit_event`'s additive params produce no payload clutter, zero leftover references to the old `active_conv_id` signature anywhere in `backend/app`). No security-auditor run (M.4 touches no secrets/config/auth).

### [2026-07-13] — Phase M / M.5: projects backend API + two-way chat moves

New `backend/app/routes/projects.py` (registered in `main.py`): `POST /projects` (client-generated id, idempotent, mirrors `conversations.py`'s create pattern), `GET /projects` (list with `chat_count` per project), `PATCH /projects/{id}` (rename, json-only, never moves the Drive folder), `DELETE /projects/{id}` (cascade — Drive's own recursive folder delete removes every contained chat's files, plus `delete from memory_chunks where user_id=%s and scope_type='project' and scope_id=%s`), `POST /projects/{id}/chats/{conv_id}` (move in), `DELETE /projects/{id}/chats/{conv_id}` (move out). Both moves: Drive relocate (`storage.projects_drive.move_chat`, a thin wrapper over `drive.move_item`) always happens **before** the Postgres `update memory_chunks set scope_type=..., scope_id=...` — Drive is authoritative — then `memory.indexer.evict_scope(user_id, conv_id)` invalidates the in-process scope cache so the next `resolve_scope()` (in `chat.py` or `index_turn_task`) sees the new placement immediately, not a stale entry. Both directions are idempotent (already-there / already-standalone short-circuits to a 200 no-op before touching Drive or Postgres) and reject moving into a second project while already in one (409, not silent data corruption) — matches plan decision #8 (in/out only, no direct project-to-project transfer).

New `backend/app/memory/locks.py` — `get_conv_lock(user_id, conv_id)`, a module-level per-`(user, conv)` `asyncio.Lock` dict (same shape as the existing per-`(user,model)` lock in `routes/generate.py`). `memory/indexer.py`'s `index_turn_task` now holds this lock for its entire body (Drive write + Postgres write); both move endpoints hold it for their entire relocate+update. This is the concurrency guarantee the plan calls for: a turn being indexed for a chat mid-move either finishes writing under the old scope before the move proceeds, or resolves the new scope fresh after it — never interleaved.

219 backend tests green (up from 203) — new `backend/tests/test_projects.py`: CRUD, idempotent create-by-client-id, move-in/move-out both directions (asserting both the Drive placement via `resolve_conv_scope` and the exact Postgres `update`/`delete` SQL+params), idempotency on repeat calls, the 409 already-in-another-project conflict, 404s for missing project/chat and for moving out of the wrong project, cascade delete removing both the Drive folder and the scoped Postgres rows, post-move-out scope-cache eviction (a chat moved out immediately resolves to `('chat', conv_id)`, not a stale cached `('project', ...)`), and a moved chat's *next* `index_turn_task` call (no precomputed scope passed) correctly resolving to wherever it currently lives.

code-reviewer PASS (0 CRITICAL). 1 WARN found and fixed before commit: `DELETE /projects/{id}`'s cascade delete originally took no lock at all, so an in-flight `index_turn_task` write for a chat inside the project being deleted could land an `add_chunk` Postgres row *after* the Drive folder (and that scope) was already gone — an orphan `memory_chunks` row `rebuild_index` can never repair, since there's nothing left on Drive to rebuild from. Fixed: `delete_project` now lists every contained chat, acquires all of their per-`(user,conv)` locks via `AsyncExitStack` before deleting, and holds them through both the Drive folder delete and the Postgres chunk delete. security-auditor PASS (0 CRITICAL/WARN) — run proactively per the plan's own M.7 guidance ("security-auditor... for new route module touching user-scoped data") given the destructive cascade-delete and data-relocation surface, even though this step's diff doesn't literally touch secrets/config/auth: confirmed every Drive operation is implicitly user-scoped (a raw project_id/conv_id from another user's account simply 404s inside the caller's own Drive tree — there's no code path that accepts a raw file ID from the client), every Postgres statement carries `user_id = %s`, all SQL is parameterized, and no secrets/env/key usage anywhere in the new files. One informational, **pre-existing** (not introduced by M.5, no fix needed now) note: `DriveStorage.find_file` builds its Drive search query with Python `repr()` escaping rather than proper Drive-query-language escaping — bounded blast radius (can only match a different sibling inside the same already-user-scoped parent folder, never cross a Drive account boundary), logged as a future hardening backlog item.

### [2026-07-05] — Fixed warm-session Stop never actually killing the Kaggle kernel (+ death detection during warmup)

**Reported:** (1) clicking Stop showed "stopping" then reverted to not-running in the UI, but the Kaggle kernel kept running/consuming GPU; (2) stopping the kernel externally on Kaggle didn't update PAWN's UI. User believed it "worked fine 2-3 days ago."

**Git archaeology (user asked to check 2-3 day old commits):** the warm-session notebooks' serve-loop AND model-load cells are **byte-identical across 06-30, 07-03, and today** — the stop logic never changed. What changed 2-3 days ago was infrastructure only (Supabase→PostgREST on 07-03 `9350664`, RLS `session_token` scoping on 07-04 `2e9918f`), not the stop mechanism. So there was **no regression to revert to**; the bug is structural and has existed since the warm-session feature was built (W.1, 06-29).

**Actual root cause:** the stop check lived ONLY in the serve loop (cell 3), which runs *after* the model finishes loading. During the entire warmup window (pip install + model load — up to 10+ min for FLUX) the kernel never reads the stop flag. Worse, cell 2's success path unconditionally patched `status='ready'`, **resurrecting** a session the user had already stopped. Stop only ever worked if clicked while `ready` — which is why SDXL (loads in ~1-2 min) seemed fine and FLUX (slow, and currently OOMing on load) exposed it constantly. Confirmed against the live prod DB: a FLUX session stopped 13s after start (still warming) sat unresponsive.

**Fix — lifelong supervisor daemon thread** (both warm-session notebooks, identical): starts before pip install and runs for the kernel's whole life. Every poll it heartbeats AND checks for stop/expiry; the instant it sees either, it patches `ended` and **`os._exit(0)`** — hard-ending the Kaggle run and freeing the GPU even while the main thread is blocked mid-load. Kaggle exposes no external "cancel kernel" API, so a cooperative self-exit is the only mechanism that exists. Also added a resurrection guard before the ready-patch (belt-and-suspenders for a stop landing in the final seconds of a load). Because the supervisor now heartbeats during warmup, the backend (`get_session_status`) detects a kernel that died mid-startup via stale heartbeat and surfaces it as `error` (previously such a session sat in `loading_model` for up to 15 min); falls back to the wall-clock startup timeout before the first heartbeat / for older kernels.

**Universality (user asked):** applied to BOTH warm-session notebooks (`image_flux_session`, `image_sdxl_session`) — identical supervisor. The cold one-shot notebooks (`image_flux`, `image_sdxl`) run to completion and have no session/stop concept; `session_poc` is unused (not in the model registry). So stop+tracking is now universal across every notebook that has a session.

**Verification:** 164 backend tests green (4 new warmup-death tests). Deployed to prod (backend rebuild; notebooks are read from the backend image at session-start). **Live Kaggle test still pending — not verifiable from the dev environment.** Caveat surfaced to the user: any kernel already running on Kaggle predates this fix and won't self-stop; a fresh session must be started after deploy to pick up the supervisor. This builds directly on the prior 2026-07-05 fix (`472a170`, the `stop_requested_at` / stale-`ready` detection) — that fix made PAWN *honest* about not knowing; this one makes the kernel *actually stop*.

**Commits:** `4c33bf8` (dev) → `b92e883` (main, deployed).

---

### [2026-07-05] — Migrated prod off the paid bridge onto the permanent free-tier Ampere instance

**Built:** the background retry loop (started 2026-07-04, documented in `current_state.md`'s Known Issues) succeeded on attempt 183 at `2026-07-04T17:54:11Z` — Oracle freed up Always-Free Ampere A1 capacity in `ap-mumbai-1` and the saved Resource Manager stack provisioned a new dedicated instance, `pawn` (`144.24.119.184`, 1 OCPU/6GB, `VM.Standard.A1.Flex`, ARM64). Unlike `deployment.md`'s "second app on Enma's shared box" framing, both `pawn-temp` and the new `pawn` instance turned out to be fully standalone VMs (Enma's Always-Free pool was split across separate instances, not a shared host) — so the shared-box hard rules in `deployment.md` §0 didn't actually apply to this migration; Nginx/firewall were set up fresh with no Enma coexistence concerns.

Migration executed data-preserving (user chose this over a from-scratch deploy): installed Docker CE + Node 20 fresh on the new box, cloned `main`, copied `.env.prod` + all real secrets (including `encryption_secret`/`jwt_secret`) verbatim from `pawn-temp` so existing encrypted BYOK keys/Drive tokens kept decrypting correctly, built the frontend, brought up the stack against an empty DB (schema auto-init), then `pg_dump --data-only` from `pawn-temp` → restored on the new instance (verified matching row counts: 2 users, 5 BYOK keys, 2 Drive tokens, 12 image sessions, 32 image jobs). Firewall (iptables 80/443) + Nginx (identical server block to `pawn-temp`'s actual live config, not the stale copy sitting in `sites-available`) set up HTTP-only first; after the user manually repointed DuckDNS, did one final freeze-and-resync (stopped `pawn-temp`'s `backend`+`postgrest` to halt writes, re-dumped, confirmed identical row counts — nothing had changed), then issued a fresh Let's Encrypt cert via `certbot --nginx` now that DNS actually resolved to the new box.

**1 real bug found and fixed:** `docker-compose.prod.yml` hardcoded `backend: cpus: 1.5` (plus `postgres: 1.0` + `postgrest: 0.5`, summing to 3.0) — safe on `pawn-temp`'s x86 `E5.Flex` (1 OCPU = 2 vCPUs via hyperthreading, confirmed via `nproc`), but Docker rejected it outright on the new Ampere A1 box, whose 1 OCPU is a single physical vCPU with no SMT (`nproc` → 1). No container's `cpus` limit can exceed the host's real vCPU count. Rescaled to `0.6/0.3/0.1` (sums to ~1.0) — fixed on `dev`, promoted to `main`, pulled on the new instance. This is a portability gap in the compose file for any future move between differently-shaped hosts, not fixed generically (values are still hardcoded, just correctly sized for the actual permanent target now).

**User-authorized destructive step:** after the user manually verified login, chat streaming, and app load against the new instance in their own browser, they asked to fully terminate `pawn-temp` immediately (accepted the risk explicitly — "if we have any issues, we will resolve them anyways") rather than keep it as a rollback fallback for a few days. Took one last local backup (final `pg_dump` + full `secrets/`+`.env.prod` tarball, saved to `backups/pawn-temp-final-2026-07-05/`, gitignored) before running `oci compute instance terminate --preserve-boot-volume false`. Confirmed unreachable via SSH timeout shortly after.

**Outcome:** prod now runs entirely on the free-tier instance; no more paid-instance billing risk against the Universal Credits balance expiring 2026-07-31. `enma-production` untouched throughout (never in the blast radius — separate instance, never modified).

---

### [2026-07-04] — Fixed the permissive pawn_anon RLS gap (blocker for going public)

**Built:** `/pgrst/` (PostgREST) is a public HTTPS endpoint with no auth layer of its own — every request runs as the `pawn_anon` Postgres role, which previously had blanket table-level access to `image_sessions`/`image_jobs` with a permissive RLS policy (`using (true) with check (true)`). Anyone on the internet, without a PAWN account, could read every user's generated images/prompts or corrupt/hijack any live session or job. `session_token` already existed on `image_sessions` and was already sent to the Kaggle kernel's startup payload, but nothing ever checked it — it was inert.

Fix: both warm-session Kaggle notebook templates (`backend/app/kaggle_templates/image_{sdxl,flux}_session/notebook.ipynb`) now send `session_token` back as an `X-Session-Token` header on every PostgREST call. New RLS policies in `postgres/schema.sql` (`image_sessions_scoped_select/update`, `image_jobs_scoped_select/update`, backed by a small `pawn_current_session_token()` SQL function reading PostgREST's `request.headers` GUC) require that header to match before permitting SELECT/UPDATE — `image_jobs` has no `session_token` column of its own, so its policies join through `session_id`.

**Investigation detour (self-corrected):** initially believed `kaggle_templates/` wasn't in version control at all (searched the repo root, found nothing, no git history). This was wrong — the real path is `backend/app/kaggle_templates/` (relative to `constants.py`, not the repo root), and it's fully committed. No actual version-control gap existed; wasted a Kaggle-API pull-down before catching the mistake.

**Decisions:** chose "wire up the existing session_token as a header" over a full scoped-JWT redesign — much less new surface, and the token already existed for exactly this purpose. A safety hook correctly blocked an early attempt to verify PostgREST's header-exposure mechanism via a temporary debug SQL function granted to `pawn_anon` (would have ironically expanded exposure on the exact over-permissioned role being locked down) — relied on PostgREST's documented, stable-since-early-v9 behavior instead, and verified via the real application flow.

**Verification:** applied the schema change live to `pawn-temp`'s running Postgres (a one-off migration — `docker-entrypoint-initdb.d` only runs on a fresh volume). `curl` against `/pgrst/image_sessions` with no token or a wrong token → `[]` (nothing leaked); with the correct token → only that session's own row. Promoted `dev`→`main` (using the now-fixed promote script — completed end-to-end on the first try, no manual intervention needed), pulled + rebuilt on `pawn-temp`. User manually confirmed a real session-start + image generation still works end-to-end against the new token-scoped policies.

**Outcome:** this was the explicitly-documented blocker for ever flipping the Google OAuth consent screen from Testing to public. That's now clear.

**Commit:** (pending — committed alongside this doc update)

---

### [2026-07-04] — D.8: first live production deploy, executed and verified (on a temporary bridge instance)

**Built:** Split Enma's Always-Free Ampere A1 pool (4 OCPU/24GB) into two — resized `enma-production` down to 3 OCPU/18GB (verified healthy via SSH: `free -h`/`nproc` match, all 4 containers "Up (healthy)", app health green) and attempted to launch a new 1 OCPU/6GB Ampere instance for PAWN with the freed quota. Oracle returned `Out of host capacity` on every attempt in `ap-mumbai-1` (a known, common Always-Free constraint — the region has only one availability domain, so there was no alternate AD to fall back to). Rather than block indefinitely, launched PAWN instead on a temporary paid instance (`pawn-temp`, `VM.Standard.E5.Flex`, 1 OCPU/6GB, ~$46/month) funded by an existing Universal Credits balance (SGD 400, expires 2026-07-31), while a retry loop keeps polling for the free slot in the background via a saved OCI Resource Manager stack.

Full deploy from scratch on `pawn-temp`: Docker Engine + Compose plugin, a fresh GitHub deploy key (generated on the VM itself, private key never leaves it), cloned `main`, generated fresh secrets, built the frontend, brought up postgres+postgrest+backend, DuckDNS repointed to the new IP, Nginx server block + Certbot TLS, and Google OAuth credentials (shared client with local dev) copied over.

**4 real bugs found and fixed live** (all folded back into `deployment.md`):
1. Oracle's stock Ubuntu image's host iptables allows only SSH (22) by default — the OCI Security List already permitted 80/443, but the host itself silently rejected everything else. The app was completely unreachable from the internet until this was found (via `sudo iptables -L INPUT -n`) and fixed with an explicit rule + `netfilter-persistent save`.
2. `/pgrst/`'s Nginx `client_max_body_size` defaulted to 1MB. The warm Kaggle kernel's PATCH write-back of a finished image (base64, routinely 1-3MB) got silently 413'd — confirmed via the Nginx access log showing `413` responses from the Kaggle notebook's IP. Every image-gen job got stuck at "running" forever with zero error surfaced in PAWN's own UI. Fixed: `client_max_body_size 20m;`.
3. `get_session_status()`'s cold-start timeout (a bare `300` in `image_session.py`, not even a named constant) was too short for a real SDXL cold start under this deploy's network conditions — the Kaggle kernel was still genuinely alive and loading past 8 minutes, but PAWN's own auto-cleanup declared the session dead and reaped its jobs with a misleading "session ended"/"terminated unexpectedly" error. Raised to a named `IMAGE_SESSION_STARTUP_TIMEOUT_SECONDS = 900` in `constants.py`.
4. CSP `img-src` gap: `default-src 'self'` does not implicitly permit the `data:` scheme. Image Lab renders every thumbnail/lightbox as `<img src="data:image/...;base64,...">`, and with no `img-src` directive set, browsers silently blocked all of them — diagnosed by checking the actual stored `image_b64` length in Postgres (correct), then the raw backend response bypassing Nginx (correct), then realizing the CSP itself (added earlier this same day for an unrelated static-frontend-headers fix) was the culprit. Fixed in both `SecurityHeadersMiddleware` and the static frontend's Nginx `location /` block.

**Also found and fixed:** `scripts/promote-to-main.sh` silently died right before its final `git commit` on both real promotions run today — each time leaving the repo mid-merge on `main` with everything already correctly resolved, requiring a manual `git commit` to finish. Root cause: the `while read -r f; do ... done` loop stripping `CLAUDE.md`/`AGENTS.md` always exits 1 on EOF (standard, often-surprising bash behavior for `while read` from a pipe) regardless of how many lines it actually processed, and unlike every other risky line in the script, this one had no trailing `|| true`. Under `set -e` that killed the script immediately, every time. Fixed and verified against a throwaway clone — completes end-to-end now.

**Decisions:** Accepted the paid-bridge approach rather than waiting indefinitely for free capacity, since Ampere A1 shortages in this region are unpredictable (could be minutes or days) and the credit balance covers the gap with margin. Deliberately generated the GitHub deploy key and OCI API signing keys directly on each target machine (never copied a private key across machines) — the Enma VM's own original deploy key had been "lost" earlier in this same session and was eventually found relocated (not actually lost) at `~/.ssh/enma_oci.key`, with an Windows ACL misconfiguration (an inherited sandbox-user grant) separately blocking OpenSSH from using it until `icacls` stripped the bad inheritance.

**Verification:** Full `deployment.md` §7 checklist passed live — health, no CSP violations, Google OAuth + Drive-linked round-trip, BYOK chat, and a real Kaggle SDXL generation end-to-end through the PostgREST rendezvous. Enma re-verified healthy after every shared-account action (the resize, and indirectly via the retry-loop attempts against the same tenancy).

**Outstanding:** migrate `pawn-temp` → the permanent free-tier instance once the retry loop succeeds (now being moved to run from `pawn-temp` itself via a fresh OCI CLI setup, so it survives the operator's laptop going offline); terminate `pawn-temp` afterward, well before its backing credit expires 2026-07-31.

**Commit:** (pending — committed alongside this doc update)

---

### [2026-07-04] — Drive-Mandatory Phase 4 (review/docs/commit) + deployment simplified to prod-only

**Built:** Closed out `plan_drive_mandatory.md` Phase 4 — ran code-reviewer + security-auditor across the full combined Phase 1-3 diff (`git diff 9350664..28cfcc4`). This review had never actually happened for Phase 1+2 despite the plan explicitly calling for a security-auditor pass (it touches Drive-token/auth code); only manual live testing had been done. Both agents came back PASS, 0 critical, with 4 WARN-level fixes applied:
1. `backend/app/routes/auth.py:18` — a stale comment claimed Drive was "optional" with a local-filesystem fallback, directly contradicting the Drive-mandatory architecture everywhere else in the codebase. Reworded to describe the actual behavior (fails clearly via `require_drive_for_user()`/412).
2. `backend/app/core/drive_factory.py`'s `_build_drive_for_user` (Postgres fetch failure, token decrypt failure) and `routes/auth.py`'s `/auth/drive/status` (Drive-call failure) were silently swallowing exceptions with zero logging — inconsistent with every other fail-soft path this same plan introduced (`chat.py`, `summarize.py` both log to stderr). Ironic given the whole plan was triggered by a hard-to-diagnose failure. Added `print(..., file=sys.stderr)` logging to both.
3. `backend/app/routes/upload.py` (file-read, PDF-parse, text-decode failures) and `backend/app/routes/chat.py`'s SSE catch-all were returning raw exception text (`f"...{exc}"` / `str(exc)`) directly in the client-facing error — an information-disclosure smell, not a credential leak but still library/stack internals reaching the client. Genericized all four to fixed messages with server-side stderr logging (chat.py already had `traceback.print_exc()` server-side; only the client-facing string changed).

152 backend tests still green after the fixes (re-verified twice). Independently re-confirmed the build-validator's checklist myself: `storage/conversations.py`/`documents.py` are deleted and only the `_drive.py` variants remain; no leftover `if drive`/`local_storage` patterns in `crypto.py`/`summarize.py`; `docker compose config` validates.

**Decision (separate from Phase 4, raised mid-session):** Simplified the deployment plan — **dropped the two-environment staging-first deploy**. `dev` stays local-only, never deployed to the VM; only `main` deploys to prod (`pawnai.duckdns.org`). Rationale: PAWN currently has no public user base (Google OAuth consent screen is Testing-mode, explicit allowlist only, not the general public — corrected an earlier mischaracterization of this as a "single-user app": it's built multi-user, just not yet opened beyond the allowlist), so the blast radius of skipping a dedicated staging box is small, and D.6's local pre-deploy gate already substitutes for it. Local dev and prod will **share one Google OAuth client** (both redirect URIs registered) and the same Google account(s) for login; database/secrets stay **separate** per environment (own local Postgres + own `encryption_secret`/`jwt_secret` for dev, own set on the VM for prod) — chosen as the safer default (a shared DB would let local `dev`-branch bugs corrupt real prod data; a shared `encryption_secret` would let a compromised dev machine decrypt prod's BYOK keys) since the user didn't respond to an explicit question about DB-sharing scope before the session moved on. Accepted tradeoff: local dev is x86, the VM is ARM64, so ARM-specific issues surface for the first time at the real prod deploy rather than a disposable staging box. `plan_deployment.md` D.1-D.7 checkboxes synced to `[x]` (previously out of sync with `build_tracker.md`); D.6b dropped entirely; D.7/D.8 rewritten prod-only. A pre-existing, already-documented gap — permissive `pawn_anon` Postgres RLS on `image_sessions`/`image_jobs`, not scoped per-user — remains a prerequisite for ever flipping the OAuth consent screen from Testing to public, tracked but not blocking this deploy.

**Outstanding before D.8:** `deployment.md` itself still contains the original two-environment runbook text and needs a follow-up edit pass to strip the staging section before D.8 is actually executed (noted as step 0 of D.8 in the plan rather than reopening D.7).

**Commit:** (pending — committed alongside this doc update)

---

### [2026-07-04] — Feature: "Connect Google Drive" control in Settings

**Built:** The Drive-mandatory 412 tells users to "Connect your Google Drive in Settings," but no such control existed — this adds it. Backend: new `GET /auth/drive/status` in `routes/auth.py` (decodes the Bearer token itself, since `/auth/*` bypasses AuthMiddleware) → `get_drive_for_user` then a cheap idempotent `get_or_create_root` Drive call to prove the `drive.file` scope actually works → `{"connected": bool}`. Frontend: `client.getDriveStatus()`; `ApiKeysSection.tsx` now renders a **Google Drive** row FIRST in the API-keys card — Connected/Not-connected badge + a Connect/Reconnect button that runs the existing `useAuth().login()` OAuth flow (already requests `drive.file` with `prompt=consent` and stores fresh tokens on callback, evicting the drive cache). Drive status is fetched independently of the keys list so one failing doesn't blank the other.

**Decisions:** Status is verified with a REAL Drive call, not token-existence — a login that declined `drive.file` via granular consent still leaves a stored token, and a naive check would show a false "Connected" for exactly the users this feature is meant to help (the original-bug scenario). Reused `login()` rather than adding a separate link-drive endpoint (re-consent is the correct fix and it already stores/evicts correctly). Reconnect lands back on the app root (the callback always redirects to `/`) — acceptable for v1.

**Tests/verify:** New `backend/tests/test_auth.py` (5 tests: 401 on missing/bad token; connected=false when unlinked; true when usable; false when `get_or_create_root` raises = scope declined). Backend **157 passed**. `npm run build` clean (rebuilt the frontend image so the container had the new TSX). Live: `/auth/drive/status` → 401 unauthenticated, `{"connected":false}` for a token whose user has no Drive linked. The Connected=true happy path + the OAuth redirect still need a real Google account (covered by manual/D.8 staging verify).

**Commit:** (pending — with this doc update)

---

### [2026-07-04] — Phase D / D.6: pre-deploy gate executed (incl. live Drive-less 412)

**Ran the full pre-deploy gate:** backend pytest **152 passed**; frontend `npm run build` clean; `docker compose config` valid for all three (dev compose + prod compose under both `.env.staging.example` and `.env.prod.example`). Live checks against the running dev backend (`:8001`): `GET /health` → 200, `GET /conversations` unauthenticated → 401.

**Live-verified the Drive-mandatory 412 path** (the exact regression this plan targeted) without a Google account, by minting a valid JWT in-container (`app.core.jwt_utils.create_token`) for a user with no linked Drive and calling Drive-required endpoints: `GET /conversations` → **HTTP 412** and `GET /crypto/salt` → **HTTP 412**, both with `{"detail":"Connect your Google Drive in Settings to use PAWN.","code":"not_configured"}`. `/crypto/salt` is the very endpoint whose unhandled 500 started the Drive-mandatory plan — now a clean 412.

**Outstanding:** only the Drive-**linked** happy path (create conversation → persists to Drive, BYOK chat), which needs a real OAuth/Drive token and can't be faked locally. It's covered by the D.8 staging verify checklist (`deployment.md §8`), so D.6 is effectively closed for gating.

**Commit:** (pending — with this doc update)

---

### [2026-07-04] — Phase D / D.7: deployment.md runbook + parameterized prod compose

**Built:** Repo-root `deployment.md` — a full second-app-on-the-Enma-VM runbook covering **both** environments staging-first (hard rules, prerequisites, DuckDNS/OAuth setup, per-env clone→secrets→frontend build→compose up→Nginx block→certbot, promote step, prod repeat, verify checklists, Enma re-check, firewall table, release/rollback, known deferrals). New `docker-compose.prod.yml` — ONE parameterized file for both envs: an `--env-file` (`.env.prod` / `.env.staging`) sets `COMPOSE_PROJECT_NAME`, loopback ports, and the non-secret deployment URLs; Docker's project-name prefixing isolates volumes/networks (`pawn_postgres_data` vs `pawn-dev_postgres_data`). Backend loopback-only, default (non-reload) uvicorn CMD, `mem_limit`/`cpus` caps per hard rule 9; no frontend service (Nginx serves the static `dist`); postgrest on a loopback port for the Nginx `/pgrst/` rendezvous. New `.env.prod.example`/`.env.staging.example`; `.gitignore` now excludes the real `.env.prod`/`.env.staging`.

**Decisions:** Same-origin layout — one Nginx `server_name` per env serves the SPA at `/`, reverse-proxies the root-level API paths (regex `^/(health|auth|chat|generate|conversations|registry|keys|upload|crypto)`) to the backend with SSE-friendly settings (`proxy_buffering off`, long read timeout), and proxies `/pgrst/` to PostgREST. One Google OAuth client with both redirect URIs (staging + prod) rather than two clients. PostgREST is internet-exposed with the permissive `pawn_anon` role — documented as a carried-over deferral (scoped JWT mandatory before multi-user).

**Verification:** `docker compose config` validates cleanly for both envs (resolved project name, ports, volume names, env vars). **Live local boot test** (throwaway project on ports 8002/3002, fresh volume, alongside the untouched dev stack): the prod compose actually comes up — postgres healthy, schema+`init_pawn_anon` ran on the empty volume (`pawn_anon` role + `users`/`user_api_keys`/`image_sessions`/`image_jobs` tables), backend `/health` → `{"status":"ok"}` on the non-reload uvicorn CMD with a clean DB connection, PostgREST up on loopback (HTTP 200). PostgREST rendezvous behavior confirmed: anon `GET /image_sessions` → `[]` 200 (granted), anon `GET /users` → 401 (correctly denied — `pawn_anon` posture intact). Torn down with the volume; dev stack unaffected. Still not run on the real VM behind Nginx/TLS/OAuth — that is D.8 (gated).

**Commit:** (pending — committed alongside this doc update)

---

### [2026-07-03] — Drive-Mandatory Phase 3 (D.5 clean-`main` mechanism + D.6 gate) + branch/env strategy

**Discussed & decided:** (1) User BYOK provider keys stay in Postgres (`user_api_keys`, AES-256-GCM via `encryption_secret`, cached + `prefetch` per chat) — **not** moved to Drive; keys are hot-path, Drive is for cold user docs. (2) `dev` is tested via a **VM staging stack** (`dev.pawnai.duckdns.org`) fully isolated from prod — never against live data/account. (3) `main` kept doc-free; (4) deploy **staging-first**, then promote `dev`→`main`, then prod.

**Built:** `scripts/promote-to-main.sh` — the clean-`main` mechanism. Does a normal `dev`→`main` merge (advances merge base → code merges cleanly every round) then unconditionally strips dev-only doc paths (`.claude/`, `workspace/`, any `CLAUDE.md`/`AGENTS.md`; keeps `README.md`) and commits. Amended `plan_deployment.md` for the two-environment staging-first deploy (new D.6b staging stack, rewritten D.5, staging-first D.8, prod-vs-staging reference table) and `plan_drive_mandatory.md` Phase 3.

**Decisions / key finding:** The originally-planned `.gitattributes merge=ours` mechanism (deployment D.5) was **tested in a sandbox and abandoned** — `merge=ours` is never consulted for the modify/delete case, so once docs are removed from `main`, every `dev`→`main` merge that touched a doc (i.e. nearly all, since `workspace/` changes each step) throws a modify/delete conflict. A naive `git merge --squash` + strip also fails (merge base never advances → real code files conflict on later promotions). The normal-merge promotion script is the proven-clean, repeatable alternative. **Constraint:** `dev`→`main` must always go through the script; a plain `git merge dev` re-adds docs.

**Verification:** Step A closed the pytest loose end from Phase 2 — full suite **152 passed** (had been manually-verified-only, never run via pytest). `npm run build` clean. Promote script proven end-to-end against a real repo clone: 39 doc paths → 0 on `main`, 123 backend/frontend code files preserved, `README.md` kept, returned to `dev`. Real `main` left untouched — first strip deferred to the staging-first deploy (D.8). **Outstanding (D.6, manual, needs real linked Google account):** live Drive-mandatory flow + Drive-less 412 on the running/staging stack.

**Commit:** (pending — committed alongside this doc update)

---

### [2026-07-03] — Drive-Mandatory Storage Phase 1+2: remove local-storage fallback everywhere

**Built:** Triggered by investigating a passphrase-gate 500 (Drive OAuth scope gap in `routes/crypto.py`). Rather than patch just that route, Google Drive became the only storage backend for user data — no local-filesystem fallback anywhere. New `core/drive_factory.py` helpers: `require_drive_for_user()` (raises the existing `NotConfiguredError`, HTTP 412, when Drive isn't linked) and `call_drive()` (translates ANY Drive-operation failure into that same clear error instead of an unhandled 500). Removed the `if drive: ... else: local_storage...` branch from `routes/crypto.py`, `routes/conversations.py`, `routes/upload.py`, `routes/chat.py`, `memory/summarize.py`; deleted the now-dead `storage/conversations.py`/`storage/documents.py`. `chat.py` only requires Drive when a request actually needs storage (`conversation_id`/`doc_id` present) — stateless chat keeps working with no Drive link. Background tasks fail soft instead of raising (no HTTP response to attach an error to). New `backend/tests/fake_drive.py` (in-memory `FakeDriveStorage` running the real `conversations_drive.py`/`documents_drive.py` logic); rewrote `test_conversations.py`, `test_upload.py`, `test_summarize.py`, `test_rag.py`, `test_crypto.py`; added 412-path tests.

**Decisions:** Reused `NotConfiguredError` rather than adding a new exception class — same "user must configure X" shape as the existing Kaggle-creds error, and the frontend already surfaces any `detail` field generically. Chose per-request errors over an app-wide "Connect Drive" gate screen (smaller surface, user's explicit choice). Discovered mid-investigation that the *entire* test suite implicitly relied on Drive-unavailable-fallback-to-local (tests have no real Postgres/Drive connection, so `get_drive_for_user()` already silently returned `None` today) — fixed by building one shared in-memory Drive fake rather than mocking each high-level function per test file.

**Related fixes made along the way (not originally scoped):** Removed the Phase 3 encryption passphrase gate from the auth flow entirely (`App.tsx`, deleted `PassphraseGate.tsx`) — it unconditionally blocked the whole app after login for a feature whose actual encrypt/decrypt-on-write wiring was deferred (`implemented_phases/phase_8_encryption.md`), so it derived a key nothing downstream used; pure friction, no benefit. The crypto module and backend salt endpoint stay in the codebase, unused, for later. Renamed `supabase/` → `postgres/` (`schema.sql`+`init_pawn_anon.sh`) since the old name was actively confusing post-D.3/D.4 — updated `docker-compose.yml`'s mounts and all current-state doc references; verified a fresh Postgres volume still bootstraps correctly from the renamed files.

**Verification:** Manually verified against the full live stack (`docker compose up --build`: postgres+postgrest+backend+frontend) — confirmed by direct user testing rather than the automated pytest suite (explicitly skipped this pass per user instruction). Automated suite should be re-run before D.6 (pre-deploy test gate), which already plans to run it.

**Commit:** (pending — committed alongside this doc update)

---

### [2026-07-03] — Phase D / D.1: kill hardcoded localhost values (CORS, OAuth redirect, CSP)

**Built:** `backend/app/config.py` gains `CORS_ORIGINS`/`FRONTEND_URL`/`OAUTH_REDIRECT_URI`/`CSP_CONNECT_SRC` as `os.getenv(name, default)` constants (non-secret deployment config, not `read_secret` — no secret-file shadowing risk); defaults reproduce today's hardcoded localhost values exactly, so local `docker compose up` is unaffected. `main.py` CORS `allow_origins` now built from `CORS_ORIGINS` (comma-split) with a startup `ValueError` guard against `*`. `routes/auth.py` `_FRONTEND_URL`/`_REDIRECT_URI` sourced from config instead of hardcoded strings — `_REDIRECT_URI` is the highest-risk value (must exactly match the Google OAuth client's registered redirect URI in production). `middleware/security.py` CSP `connect-src` reads `CSP_CONNECT_SRC`. New `backend/tests/test_deployment_config.py` (6 tests).

**Decisions:** Read via plain `os.getenv` rather than `read_secret` — these are non-secret URLs, not API keys, and `read_secret` has no default-value support. Values are read once at process/import time (standard 12-factor pattern); env-var overrides are proven at the `config.py` level via `importlib.reload` in tests rather than reloading every consumer module.

**Issues found in review (both fixed):** code-reviewer caught a test-pollution bug — the `finally` block in the env-override test reloaded `app.config` while the monkeypatched env vars were still set (monkeypatch only tears down after the test returns), silently leaving the shared config module polluted for later tests; fixed by explicitly clearing the vars before the restorative reload. security-auditor caught that `CORS_ORIGINS` had no guard against an operator setting it to `*` (violates `.claude/rules/security.md`'s "never `allow_origins=['*']`"); fixed by raising at startup if `*` appears in the parsed origin list, with a new regression test.

**Tests:** 148 backend tests green (was 147 + hotfix wildcard test = 148). `docker compose config` still validates cleanly (no new env vars referenced in `docker-compose.yml` yet — that's D.7's job).

**Commit:** (pending — committed alongside doc updates)

---

### [2026-07-03] — Phase D / D.3+D.4: Supabase → self-hosted Postgres+pgvector+PostgREST

**Built:** Dropped Supabase entirely. New `backend/app/db/postgres_client.py` — psycopg3 sync client (chosen over asyncpg specifically to avoid rewriting ~25 `run_in_threadpool` call sites across 6 files into async; see the plan's D.3 entry for the full tradeoff), `fetchone`/`fetchall`/`execute` + a `transaction()` helper. Rewrote every Supabase `.table()/.rpc()` call to parameterized SQL across `routes/auth.py`, `core/key_store.py`, `core/drive_factory.py`, `memory/index.py`, `memory/retrieve.py`, and a full rewrite of `core/image_session.py` (session/job CRUD). D.4 (Kaggle→PostgREST rendezvous) done in the same pass since dropping the Supabase secrets in D.3 would otherwise break D.4's Kaggle-payload code: `schema.sql` gains a `pawn_anon` role + retargeted RLS policies, new `init_pawn_anon.sh` sets its password from a secret, `docker-compose.yml` gains `postgres`+`postgrest` services, and all 3 Kaggle session notebooks now talk to PostgREST directly instead of Supabase's REST gateway. The `supabase/` directory (schema.sql + init_pawn_anon.sh) was renamed to `postgres/` afterward — the old name was actively confusing once Supabase was fully dropped.

**Decisions:** psycopg3 over asyncpg (see above). Per-call connections, no pool — simplest correct option at this app's single/few-user scale, and still cheaper per-call than the old HTTPS round-trip to Supabase's cloud. No JWT/bearer auth added to PostgREST's anon role — kept the same permissive-anon-on-two-tables posture the app already had and had already documented as "deferred until multi-user" (Phase W); adding scope here would have been solving a problem this app doesn't have yet.

**Issues found (all fixed before commit):**
- **Live-Postgres integration testing** (not just mocks) caught a real bug: `match_memory_chunks`/`search_memory_chunks` SQL-function calls failed with `UndefinedFunction` because Postgres won't implicitly cast a plain array parameter to `vector` in a function-call argument context (it will in an INSERT/UPDATE target-column context, which is why `memory/index.py`'s plain insert didn't need the same fix) — fixed with explicit `%s::vector`/`%s::int` casts in `memory/retrieve.py`.
- **code-reviewer caught a CRITICAL bug**: `image_jobs.params` (jsonb) was never added to `schema.sql`'s `CREATE TABLE` — it only existed in a separate `add_image_jobs_params.sql` meant to be run manually in the Supabase SQL editor. Since Postgres now self-bootstraps from an empty volume via `docker-entrypoint-initdb.d`, that manual step had no automatic equivalent, so every job insert/list would have errored on a fresh deploy. Fixed by folding the column into the main `CREATE TABLE` and deleting the now-redundant file. Verified live against a fresh Postgres volume afterward.
- **code-reviewer flagged read-then-write races**: `start_session` (evict-prior + insert-new), `extend_session`, and `submit_session_job` each did a liveness check followed by a separate write with no transaction linking them. Added `postgres_client.transaction()` and wrapped all three; verified commit/rollback semantics live against the real container.
- **security-auditor flagged** a raw-exception leak in `routes/auth.py`'s `/callback` (pre-existing, not introduced by this diff, but in an already-touched file) — now logged server-side, generic message returned to the client. Also flagged stale, no-longer-referenced local Supabase secret files still on disk — deleted (they were gitignored, so this wasn't a leak, just cleanup).
- **Unrelated pre-existing bug found while live-testing**: `frontend/.dockerignore` didn't exist, so the frontend's Docker build context (`./frontend`) pulled in the host's `node_modules` wholesale, and a broken symlink inside it crashed BuildKit. Added the missing `.dockerignore`.

**Tests:** 148 backend tests green (rewrote `conftest.py`, `test_rag.py`, `test_image_session.py`, `test_image_jobs.py`, `test_keys_kaggle.py` to mock the new SQL functions — a simpler mock surface than the old chained Supabase-client fake). `npm run build` clean (backend-only migration). `docker compose config` validates. **Live-verified beyond mocks**: brought up real `postgres`+`postgrest`+`backend`+`frontend` containers from an empty volume; confirmed schema/role bootstrap, pgvector/pgcrypto/uuid/jsonb/timestamptz round-trips, the two SQL-function calls, PostgREST anonymous read+write access (and correctly-denied DELETE, confirming least-privilege grants), and both backend `/health` and the frontend responding. This live pass is ahead of D.6's own dry-run requirement, not a replacement for it.

**Commit:** (pending — committed alongside doc updates)

---

### [2026-07-03] — Phase D / D.2: fix frontend build-time API URL

**Built:** `frontend/.env.example` port fixed 8000 → 8001 (doc-only, matches the actual dev backend port in `docker-compose.yml`). New committed `frontend/.env.production` with `VITE_API_URL=https://pawnai.duckdns.org`.

**Decisions:** Committing `.env.production` is intentional per plan — it holds a public URL, not a secret, consistent with `.claude/rules/frontend.md`'s "non-secret env values are committed" convention.

**Tests:** `npm run build` (tsc + vite build) clean; verified the built `dist/assets/*.js` bundle actually embeds `pawnai.duckdns.org` (confirms Vite picked up `.env.production`). code-reviewer PASS (1 NOTE, pre-existing, out of scope: `client.ts`'s hardcoded fallback is still `:8000`).

**Commit:** (pending — committed alongside doc updates)

---

### [2026-07-03] — Mobile readiness pass + Phase 3 P3-1 (encryption foundation)

**Built (mobile, implemented_phases/phase_7_mobile_readiness.md — all 7 fixes):** user bubble `max-w-[70%] sm:max-w-[50%]` (Message.tsx); hamburger hit area `p-3.5 -m-2` (ChatPage.tsx); delete-confirm buttons `h-8 min-w-[48px] text-sm` (Sidebar.tsx); conversation search enabled + case-insensitive `title` filter with "No matching chats" empty state, and mini-sidebar search button now opens the sidebar (Sidebar.tsx); trace row `flex-wrap gap-y-1` (Message.tsx); code blocks `text-sm sm:text-xs` (Message.tsx); settings colour swatches `w-8 h-8` (SettingsPage.tsx).

**Built (encryption, implemented_phases/phase_8_encryption.md P3-1):** `frontend/src/crypto/index.ts` (PBKDF2-SHA256 600K → AES-256-GCM, non-exportable key; encrypt/decrypt; base64 + salt helpers; EncryptedBlob), `frontend/src/crypto/session.ts` (per-tab key in memory only — initSession/getKey/hasKey/clearSession, self-roundtrip check), `frontend/src/pages/PassphraseGate.tsx` (gate shown after auth, before app; fetches salt, derives key), wired into `App.tsx` AuthGate; `client.ts` `fetchSalt()`; `AuthContext.logout()` calls `clearSession()`. Backend `GET /crypto/salt` (`routes/crypto.py`) stores/returns the public PBKDF2 salt in `PAWN/.salt` on Drive (local fallback `<DATA_DIR>/salts/<user>.salt`), created idempotently on first request; registered in `main.py`.

**Decisions:** Full encrypt-on-write / decrypt-on-read of Drive payloads was NOT wired — it conflicts with the current server-side LLM streaming, RAG, summarization and auto-titling (all read plaintext). Delivered the reusable, tested foundation + gate instead and flagged the conflict in implemented_phases/phase_8_encryption.md for a product decision. Added `vitest` as a devDep.

**Issues:** The Windows→Linux workspace mount intermittently truncated tool-written files; affected files were reconstructed deterministically from `git HEAD` via scripted replacements and re-verified.

**Tests:** 7 vitest crypto tests pass (roundtrip, fresh-IV, wrong-passphrase, tampered-ciphertext, session lifecycle, cross-session). `tsc -b` clean, `vite build` clean. Backend `tests/test_crypto.py` added (3 tests — Drive create/reuse + local-fallback idempotency); run under Docker per project convention (backend deps not installed in this sandbox).

**Commit:** (uncommitted)

---

## Format

### [YYYY-MM-DD] — Step N: [Step Name]

**Built:** [brief description]
**Decisions:** [any non-obvious choices made]
**Issues:** [anything that took time or was tricky]
**Tests:** [N passing]
**Commit:** [hash]

---

### 2026-06-30 — Phase 6 UI: Settings Page UI Polish & API Keys Row Alignment

**Built:** Polished Settings Page layouts and the dark mode toggle:
1. Reverted global theme toggle to a single button with hover rotation/tilt and click scale animations.
2. Refactored Settings Page columns (Appearance & Defaults) to stack controls, preventing boundary overflow.
3. Corrected detailed ThemeToggle background alignment math to account for gaps.
4. Made detailed ThemeToggle responsive (hiding labels and adjusting padding on medium columns/viewports).
5. Refactored Profile card rows (Display Name, Email, Actions) to stack vertically, preventing layout boundaries overflow.
6. Restructured credentials cards in ApiKeysSection.tsx into separate rows for Title, Description, Status (Configured status and Remove button placed on opposite corners), and Inputs.
7. Converted credentials setup descriptions into interactive help guide toggles.
8. Reduced page/card paddings and column spacing (p-4 to p-3, gap-6 to gap-4, px-6 to px-4) across Settings.
**Decisions:** Shifted to a vertical stacked pattern on tight screen columns for all dropdowns, text inputs, status badges, and action buttons to ensure 100% boundary safety.
**Issues:** None.
**Tests:** Frontend build compiles cleanly with zero errors; all 139 backend pytest tests passed successfully.
**Commit:** feat: settings page ui polish and api keys row alignment

---

### 2026-06-30 — Phase 6 UI: Model Sessions UI Polish, Lifecycle Alignment, and Generations Panel Refresh

**Built:** Polished and streamlined the Model Session UI and generations history styling:
1. Removed session limit by max images count logic and associated input buttons.
2. Removed session tab from the bottom panel completely, merging all status monitoring natively into the title bar controls.
3. Redesigned model selection tabs row to show model title alongside status indicators (Idle/Warming/Running/Stopping) in a single row with curated color grading: Idle (white), Warming (yellow), Running (green), and Stopping (red).
4. Redesigned Start/Stop session buttons to have identical solid dimensions and styles.
5. Moved the notebook redeploy reload icon to the Kaggle Connection button (placed before the edit icon).
6. Removed redundant queued count and in-progress text from below the Generate button.
7. Fixed the "stuck in stopping" state by implementing a backend self-healing routine that auto-ends sessions that are stopping for > 30s or warming for > 5m.
8. Refined title bar session state checks to align precisely with model selection tab status indicators (ready status vs warmup phases).
9. Updated Generations panel item chip styles: queued (amber glass), running (green glass with green pulsing dot), and done (solid complete green). Removed the empty state message.
**Decisions:** Shared the session action transition status (`sessionBusy` / `busyAction`) at the parent `ImageLabPage` component level to prevent sync lag between model selector tabs and card titles.
**Issues:** Cleaned up duplicate return statements in JSX rendering.
**Tests:** Frontend build compiles clean; all 28 python backend lifecycle unit tests passed successfully.
**Commit:** feat: model sessions ui polish & generations colors alignment

---

### 2026-06-30 — Phase 6 UI: ImageLab Layout Restructure + Kaggle Settings Integration

**Built:** Refactored `/imagelab` to a 2-column layout (left: model select, session deploy, image generator; right: Generations history panel). Integrated Kaggle credentials setup directly into the Settings page (`ApiKeysSection.tsx`) under the BYOK section, matching the format and layout of the other provider keys.
**Decisions:** Restructured the layout to place controls on the left and full-height scrollable history on the right to match standard creative tool workspace patterns. Moved Kaggle key credentials to the top of the Settings API keys list.
**Issues:** JSX parsing issue with `->` character solved by replacing with unicode `&rarr;`. Fixed unused imports/variables compilation warnings.
**Tests:** Frontend build passes cleanly.
**Commit:** feat: imagelab layout restructure & settings integration

---

### 2026-06-30 — Phase 6 UI: URL Routing + Global Dark Mode Toggle

**Built:** Migrated from boolean flag view-switching (700-line AppContent) to `react-router-dom`. `AppContext.tsx` holds cross-route state (theme, models, prefs, bubble colors). `Layout.tsx` owns the sidebar, Outlet, and a globally mounted dark mode toggle (top-right floating pill, visible on every route). `ChatPage.tsx` extracts all chat logic; bidirectional URL ↔ store sync via `useParams`/`useEffect`. `SettingsPageWrapper` and `ImageLabPageWrapper` are thin pages that wire context to the existing components. `Sidebar.tsx` uses `useNavigate`/`useLocation` internally (removed callback props for settings/imagelab). Catch-all `*` route redirects to `/chat`.
**Decisions:** Layout owns the dark mode toggle (not per-page) so it appears on ImageLab and Settings without duplicating the button. `useOutletContext` passes store + sidebar state to child pages to avoid calling `useConversationStore` twice.
**Issues:** None — tsc zero errors, npm run build clean.
**Tests:** 140 backend tests unchanged; frontend gate is `npm run build` (passes clean).
**Commit:** feat: Phase 6 UI — react-router-dom routing + global dark mode toggle

---

### 2026-06-15 — Step 1: Create the Repo

**Built:** Directory skeleton — `backend/app/` (main.py, config.py, constants.py, routes/, core/), `backend/tests/`, `frontend/src/`. Stub files only; real content in Steps 2.5 and 4.
**Decisions:** Stub files use one-line comments pointing to the step that fills them in; avoids empty files while keeping the tree readable.
**Issues:** None.
**Tests:** N/A (directory structure only).
**Commit:** chore: init repo — directory structure

### 2026-06-15 — Step 2: Claude Code Config (done in scaffolding session)

**Built:** `.claude/CLAUDE.md`, `AGENTS.md`, `settings.json`, 4 rule files, 5 agent files, `skills/build-step/SKILL.md`. PreToolUse + PostToolUse hooks block secrets writes and force-push.
**Decisions:** Used plan/12-claude-setup-guide.md verbatim as the authoritative source for all .claude/ content.
**Issues:** None.
**Tests:** N/A.
**Commit:** chore: project scaffolding — .claude config, workspace/, secrets pattern

### 2026-06-15 — Step 2.5: Docker Scaffolding

**Built:** `docker-compose.yml` with secrets block, `constants.py` (all paths from `DATA_DIR`), `config.py` (`read_secret()` checks `/run/secrets/` first then env var fallback), `backend/Dockerfile`, `backend/requirements.txt`, `frontend/Dockerfile`, 5 `secrets/*.example` files, empty gitignored placeholder secret files.
**Decisions:** Placeholder secret files created locally (gitignored) so `docker compose config` resolves without real keys. Dockerfiles are minimal stubs — full content in Steps 3 and 4.
**Issues:** None.
**Tests:** `docker compose config` validates cleanly; secrets mount at `/run/secrets/*`.
**Commit:** chore: docker scaffolding — compose, secrets-as-files, constants, config loader

### 2026-06-15 — Step 3: Static Chat UI

**Built:** React + Vite 8 + TypeScript + Tailwind v4 frontend. Components: `ChatWindow` (scrollable, auto-scroll to bottom), `MessageInput` (Enter sends, Shift+Enter newline), `Message` (user bubble right/dark, assistant left/light). `src/types.ts` defines `Message` and `ChatState`. Messages echo locally — no API calls yet.
**Decisions:** Used Tailwind v4 CSS-first setup (`@import "tailwindcss"` + `@tailwindcss/vite` plugin) — no config file needed. Upgraded Vite 6→8 to resolve esbuild high-severity vuln (0 vulns after fix). Module counter (`nextId`) is file-scoped to avoid state management overhead at this stage.
**Issues:** esbuild vuln in Vite 6 — fixed by upgrading to Vite 8 + @vitejs/plugin-react 6.
**Tests:** `npm run build` passes clean (tsc + vite build, 0 type errors, 0 vulns).
**Commit:** feat: static chat UI — message list, input, bubbles

### 2026-06-15 — Step 4: FastAPI Backend

**Built:** `main.py` (FastAPI + middleware stack), `middleware/security.py` (SecurityHeadersMiddleware: X-Frame-Options, CSP, X-Content-Type-Options, Referrer-Policy), `middleware/timeout.py` (45s timeout, SSE paths exempt), `exceptions.py` (ProviderError, NoEndpointError + handlers), `tests/test_health.py` (2 tests).
**Decisions:** Used `httpx2` instead of `httpx` to silence Starlette deprecation warning in TestClient. Exception handlers registered in `main.py` even though no provider routes exist yet — establishes the pattern for Step 6+.
**Issues:** `httpx` deprecation warning from Starlette TestClient — fixed by swapping to `httpx2`.
**Tests:** 2 passed (health returns ok, security headers present). Ran inside Docker container.
**Commit:** feat: fastapi backend — health check, middleware stack

### 2026-06-15 — Step 5: Connect Frontend to Backend

**Built:** `frontend/src/api/client.ts` — `healthCheck()` using `VITE_API_URL ?? localhost:8000` with `res.ok` guard. `App.tsx` updated with `useEffect` calling `healthCheck().then(console.log).catch(console.error)` on mount. Added `.env` to `.gitignore`. Fixed `tsconfig.app.json` missing `"types": ["vite/client"]` (caused TS2339 on `import.meta.env`).
**Decisions:** Kept the `localhost:8000` fallback (matches the plan spec) but added a comment to make the intent explicit. Added `res.ok` check and `.catch()` to surface backend errors clearly rather than swallowing them.
**Issues:** `import.meta.env` TypeScript error — fixed by adding `"types": ["vite/client"]` to `tsconfig.app.json`. Two WARNs from code reviewer (missing res.ok, missing .catch) — both fixed before commit.
**Tests:** `npm run build` passes (tsc + vite, 0 errors, 20 modules). Backend: 2/2 passing.
**Commit:** feat: frontend api client + health check wired

### 2026-06-15 — Step 6: First Real AI Response

**Built:** `backend/app/core/llm_core.py` (shared `httpx.AsyncClient`, `_detect_provider`, `_provider_headers`, `_format_upstream_error`, `close_client`, `stream_llm` async generator parsing OAI-compat SSE). `backend/app/routes/chat.py` (typed `ChatMessage` schema with `role: Literal[...]`, `POST /chat` SSE endpoint). `backend/app/main.py` chat router wired + lifespan for async client shutdown. `frontend/src/api/client.ts` `streamChat()` via fetch + ReadableStream. `frontend/src/App.tsx` `isStreaming` state, streaming assistant placeholder, token accumulation.
**Decisions:** Module-level `httpx.AsyncClient` singleton is a planned deviation; Step 9 refactors to `initialize_managers()` DI. Direct `llm_core` import in `chat.py` (bypassing `normalize.py`) is also planned; `normalize.py` arrives in Step 9. Messages schema typed as `ChatMessage(role: Literal, content: str)` to reject malformed upstream payloads. `close_client()` wired into FastAPI lifespan so the async client shuts down cleanly.
**Issues:** Test used `resp.text` on a streaming response — `httpx2` raises `ResponseNotRead`; fixed to `resp.read().decode()` inside the stream context manager. Code reviewer flagged bare `except Exception` leaking `str(exc)` to SSE stream — fixed to catch only `ProviderError` using sanitized `exc.message`.
**Tests:** 4 passed (test_chat_streams_tokens, test_chat_empty_messages, test_health_returns_ok, test_health_has_security_headers).
**Commit:** feat: first real AI response — llm_core, /chat SSE route, streamChat frontend

### 2026-06-17 — Step 7: Typed SSE Events

**Built:** `backend/app/events.py` — 7 typed SSE builder functions (`token_event`, `done_event`, `error_event`, `provider_switch_event`, `step_event`, `memory_hit_event`, `model_call_event`). `routes/chat.py` updated to emit typed JSON events via `events.*`. `frontend/src/api/client.ts` refactored: `streamChat` now accepts a `StreamChatCallbacks` object and dispatches on `event.type`; all 7 event types handled (optional callbacks silent until their steps land).
**Decisions:** `streamChat` changed from positional function args to a callbacks object — cleaner API as more event types arrive in later steps. Added `X-Accel-Buffering: no` and `Cache-Control: no-cache` headers to the SSE response — prevents Nginx/Docker proxy buffering. Used `switch(event.type)` dispatch rather than `if/else` chain for readability.
**Issues:** None.
**Tests:** 6 passed (4 new chat tests: typed token events, no-raw-strings, SSE headers, empty messages; 2 health tests unchanged). Old 2 chat tests replaced by 4 more precise assertions.
**Commit:** feat: typed SSE events — structured wire format, callbacks object

### 2026-06-17 — Step 8: Conversation History

**Built:** Full conversation history forwarding was already implemented in Step 6 (App.tsx builds `[...messages, userMsg]` and sends to backend; backend forwards entire array to LLM). Step 8 adds the explicit verification test `test_chat_forwards_full_history` — asserts all 3 messages in a multi-turn array reach `stream_llm` in order, proving the backend doesn't truncate to just the latest message.
**Decisions:** No code change required — history forwarding was already correct. Step is complete by adding the test that makes the contract explicit and locked.
**Issues:** None.
**Tests:** 7 passed (1 new: `test_chat_forwards_full_history`; 6 from Step 7 unchanged).
**Commit:** test: assert full conversation history forwarded to LLM provider

### 2026-06-17 — Step 9: Multi-Provider (normalize.py)

**Built:** `backend/app/core/normalize.py` implementing a 6-provider layout (Groq, Cerebras, Gemini, HuggingFace, GitHub Models, OpenRouter) and unified model routing. Added `groq_api_key` secrets files and Docker secrets mounting. Refactored `chat.py` and backend tests.
**Decisions:** Groq selected as top priority due to 800+ tok/s speed. Normalizer maps abstract providers to correct baseUrl, default model, and authorization headers.
**Issues:** Mock patching targets in pytest (must patch `app.core.normalize.stream_llm` instead of `app.core.llm_core.stream_llm`).
**Tests:** 12 passed (5 new provider routing tests).
**Commit:** feat: multi-provider model routing with groq support

### 2026-06-17 — Step 10: Model Switcher UI

**Built:** `frontend/src/components/ModelSwitcher.tsx` featuring grouped capability selector (Fast, Balanced, Research). Passed provider state to backend via `streamChat` body payload.
**Decisions:** Switcher disabled during streaming to avoid mid-stream provider changes that can mess up state logic.
**Issues:** None.
**Tests:** 12 passed; frontend builds cleanly with 0 TypeScript issues.
**Commit:** feat: model switcher UI for selecting providers

### 2026-06-17 — Step 11: Document Upload (pdfplumber)

**Built:** Added `pdfplumber` and `python-multipart` to `backend/requirements.txt`. Implemented `backend/app/storage/documents.py` for in-memory text storage and `backend/app/routes/upload.py` to handle document uploads, extracting content from `.txt` and `.pdf` files. Updated `backend/app/routes/chat.py` to accept `doc_id` and inject the document text as a system message. Added paperclip button and file attachment preview chip in the React frontend (`MessageInput.tsx` and `App.tsx`). Added 6 new integration tests in `backend/tests/test_upload.py`.
**Decisions:** Use `pdfplumber` for text extraction to handle complex multi-column layouts accurately. Store document text in-memory globally in a backend module to facilitate seamless context injection for stateless chat queries.
**Issues:** Encountered FastAPI runtime error due to missing `python-multipart` dependency for form parsing; resolved by installing `python-multipart`.
**Tests:** 18 passed (6 new: upload text, upload PDF mock, unsupported types, empty validation, system message injection, 404 handler). Frontend typechecks and builds cleanly.
**Commit:** feat: document upload text extraction and system prompt injection

### 2026-06-17 — Step 12: Multi-Chat Persistence

**Built:** Created `backend/app/storage/conversations.py` to implement full CRUD file management under `data/conversations/<uuid>/` containing `meta.json` and append-only `messages.jsonl` files. Developed endpoints in `backend/app/routes/conversations.py` and wired them in `main.py`. Integrated conversation loading and auto-titling `BackgroundTask` in `chat.py`. Built `frontend/src/components/Sidebar.tsx` displaying the sorted list of threads and allowing thread creation, deletion, and inline double-click renaming. Updated `App.tsx` and `client.ts` to manage and pass the `conversationId`.
**Decisions:** Automatically seed a clean conversation context on page load if none exist. Delay list refresh by 800ms post-response streaming to allow the background auto-title model generation to complete and write metadata before the frontend fetches.
**Issues:** Encountered argument mismatch in frontend `streamChat` during compilation; resolved by adding `conversationId` parameter to the API client signature and payload.
**Tests:** 21 passed (3 new: REST CRUD endpoints, messages saving to disk, auto-titling trigger). Frontend typechecks and builds cleanly.
**Commit:** feat: multi-chat persistence with sidebar navigation and auto-titling

### 2026-06-17 — Step 13: Complete Typed SSE Events

**Built:** Updated `frontend/src/types.ts` to include the `TraceEvent` schema and an optional `trace` field on the `Message` interface. Wired the remaining SSE callbacks (`onStep`, `onMemoryHit`, `onModelCall`, and `onProviderSwitch`) in `App.tsx`'s `streamChat` invocation to append incoming trace events dynamically onto the active message object.
**Decisions:** Maintain trace logs directly inside the Message object scope in frontend state, preparing the state format for the upcoming TracePanel (Step 16) and provider switch inline notifications (Step R4).
**Issues:** None.
**Tests:** 21 passed; frontend typechecks and builds cleanly.
**Commit:** feat: wire up all remaining typed SSE trace callbacks in frontend state

### 2026-06-17 — Step 14: Per-Chat Memory Summaries

**Built:** Created `backend/app/memory/summarize.py` implementing bullet-point summarization (`summarize_history`) using the fastest LLM and a disk-write task (`summarize_conversation_task`). Added `load_summary` and `save_summary` in `conversations.py`. Integrated context memory window truncation (to the last 10 messages) in `routes/chat.py` and enqueued background summarization triggers whenever the conversation turn count hits multiples of 20.
**Decisions:** Truncate context memory to last 10 messages to avoid context window inflation while keeping recent message turns intact. Prepend `summary.md` inside a dedicated system prompt.
**Issues:** Cleaned up duplicated return statements in the chat router route handler.
**Tests:** 25 passed (4 new: direct summarizer test, context window truncation verify, summary prepend, and background threshold task trigger). Frontend typechecks and builds cleanly.
**Commit:** feat: rolling conversation summaries with context memory truncation

### 2026-06-17 — Step 15: RAG over Memory (sqlite-vec)

**Built:** Integrated sqlite-vec extension loading into a sqlite3 database index manager (`backend/app/memory/index.py`), storing text summaries alongside float32 vector embeddings and FTS5 keyword indexing. Created the embedding query interface (`backend/app/memory/embed.py`) mapping to Gemini's `text-embedding-004` (with Ollama `nomic-embed-text` fallback). Created a hybrid retrieval system (`backend/app/memory/retrieve.py`) merging vector nearest-neighbors and FTS matching using Reciprocal Rank Fusion (RRF). Integrated RAG retrieval in the `/chat` route, prepending retrieved context system messages, and yielding `memory_hit` SSE tokens.
**Decisions:** Request a candidate count multiplier of `top_k * 4` during candidate generation before filtering out the active conversation ID, ensuring we retain a sufficient candidate pool.
**Issues:** None.
**Tests:** 29 passed (4 new RAG integration tests verifying vector search similarity, active thread filtering, FTS5 fallback, and SSE memory hit streams). Frontend typechecks and builds cleanly.
**Commit:** `0b7ac54` (feat: hybrid vector FTS RAG over memories with sqlite-vec)

### 2026-06-17 — Step 16: LangGraph Agent

**Built:** Replaced single-shot streaming route with a 5-node StateGraph compiled with `AsyncSqliteSaver` checkpointer. Implemented ReAct JSON action parser, purpose-to-capability routing map, and database context lifecycle manager. Built TracePanel UI collapsible container displaying steps, memory hits, and model calls underneath assistant chat bubbles.
**Decisions:** Expose `initialize_managers` as an async context manager to wrap the `AsyncSqliteSaver` lifespan properly. Use `adispatch_custom_event` inside nodes to route custom events dynamically into the `graph.astream_events` stream.
**Issues:** Resolved `TypeError` on awaiting `dispatch_custom_event` by swapping to its async counterpart `adispatch_custom_event`. Updated existing integration tests asserting message lengths to account for the planning and final generation steps of the agent runner.
**Tests:** 39 passed (10 new agent tests). Frontend typechecks and builds cleanly.
**Commit:** `08473b0` (feat: LangGraph multi-step agent with checkpointer persistence and UI trace panel)

### 2026-06-17 — Step R1: Registry Foundation

**Built:** Created Pydantic ModelEntry and EndpointEntry schemas, database files models.json and endpoints.json seeding, loaded them via loaders module and returned catalogue dynamically on GET /registry/models. Added HuggingFace, GitHub Models, and OpenRouter secret keys.
**Decisions:** Initialized data registry schemas and seeding loader dynamically on startup.
**Issues:** None.
**Tests:** 41 passing.
**Commit:** `6b51bcc` (feat: model registry foundation with json data endpoints (step R1))

### 2026-06-17 — Step R2: Rate Limiter

**Built:** Implemented in-memory EndpointRateLimiter class that tracks rolling RPM/RPD limits, filters out endpoints exceeding a 90% threshold, handles custom cooldowns for live 429s, and triggers dead-host locks after consecutive failures. Registered limiter in app_initializer lifespan managers and stored on app.state.
**Decisions:** Extended EndpointEntry schema limits in schemas.py to default to None for cleaner instantiation in unit tests.
**Issues:** None.
**Tests:** 47 passing (6 new rate limiter tests).
**Commit:** `da568f4` (feat: endpoint rate limiter with 90% soft-wall and cooldowns (step R2))

### 2026-06-17 — Step R3: Resolver + normalize Contract Change

**Built:** Created Resolver class in `resolver.py` picking optimal active endpoints and supporting capability-level routing. Modified `normalize.chat_stream` signature to accept canonical `model_id`. Updated `/chat` request schema and mapped old `provider` payload fields to model_id for backwards compatibility. Added Groq to seeded endpoints and updated test assertions.
**Decisions:** Handled backward-compatible friendly provider name aliases directly inside the Resolver's pick function and chat.py model_id mapping to allow old tests and client implementations to work seamlessly.
**Issues:** Trailing spaces in Authorization Bearer token header caused Newer HTTPX specifications to reject header format; resolved by stripping the header token string.
**Tests:** 47 passing (unit tests adjusted to account for Groq endpoint addition and custom final provider event propagation).
**Commit:** `83d3d16` (feat: resolver and fallback provider aliases with model_id signature (step R3))

### 2026-06-17 — Step R4: Frontend Wiring

**Built:** Updated `ModelSwitcher.tsx` to retrieve models dynamically from `GET /registry/models` and group options by `capability_level` (Fast, Balanced, Research, Other). Added `fetchRegistryModels` in `client.ts`. Updated `types.ts` with `'notice'` role and `viaProvider` attribute in `Message`. Updated `App.tsx` to handle `onProviderSwitch` (appending a notice message and trace log) and `onDone` (passing and storing `viaProvider`). Added a formatted provider badge under assistant message bubbles in `Message.tsx`. Filtered out `'notice'` messages from chat history sent to backend.
**Decisions:** Handled the custom notice messages purely in frontend state to keep backend conversation logs clean and standard. Explicitly typed `groups` in `ModelSwitcher` to avoid compile time issues with pushing 'other' groups.
**Issues:** None.
**Tests:** 47 passing backend tests. Frontend typescript typechecks and builds cleanly with zero errors.
**Commit:** `88738e2` (feat: frontend wiring for dynamic models, inline failover notices, and provider badges (step R4))

### 2026-06-22 — Hotfix: Port and CORS Configuration

**Built:** Fixed a silent misconfiguration that caused all browser API calls to hit a foreign service instead of PAWN's backend. `docker-compose.yml` used port ranges (`8000-8010:8000`, `5173-5180:5173`); Docker allocated 8001 for the backend and 5174 for the frontend, but `VITE_API_URL` was hardcoded to `http://localhost:8000` (another service) and CORS `allow_origins` only listed `http://localhost:5173`. Pinned ports to `8001:8000` and `5174:5173`, updated `VITE_API_URL` to `http://localhost:8001`, added `http://localhost:5174` to CORS allowed origins, and created `frontend/.env` for local dev outside Docker.
**Decisions:** Fixed port ranges to deterministic values rather than trying to free port 8000 — another service on the host owns it and there is no reason to conflict.
**Issues:** PDF upload (and all other API calls) silently failed because requests went to an unrelated service that happened to return 200 on `/health` but 404 on all PAWN routes.
**Tests:** CORS preflight verified via curl: `access-control-allow-origin: http://localhost:5174`. Upload endpoint confirmed working inside container.
**Commit:** stable: small fixes resolved

### 2026-06-27 — Step R5: UI Visual Overhaul + LAN Access

**Built:**

*Theme & layout system:*
- `frontend/src/index.css` — Full CSS variable theme system: `@theme` block, `:root` light tokens (zinc-based), `.dark` override tokens. Scrollbars hidden globally.
- `frontend/index.html` — Blocking inline `<script>` in `<head>` reads `localStorage['pawn-theme']` and `prefers-color-scheme`, applies `.dark` before first paint to eliminate FOUC theme flash.
- `frontend/src/App.tsx` — Responsive `isSidebarOpen` state (open ≥768px); `darkMode` state with localStorage + `prefers-color-scheme`, synced via `useEffect` to `document.documentElement`. Floating pill header islands (left: title + sidebar toggle, right: ModelSwitcher + dark mode toggle). Top-corner gradient overlays set to `h-16 via-theme-bg/25` (reduced from h-28/via-50 to avoid masking scrolled text). Floating bottom gradient input area. Sidebar receives `isOpen/onClose/onOpen` props.

*New component:*
- `frontend/src/components/InteractiveGridBackground.tsx` — 184-line animated canvas dot-grid reacting to mouse position; receives `darkMode` prop.

*Message rendering:*
- `frontend/src/components/Message.tsx` — `react-markdown` for assistant messages with custom component overrides (ul/ol/li, p, h1-3, pre, code inline+block, a). User messages: height >140px triggers collapsible fade overlay + "more/less" button. Unified metadata row below assistant bubble: provider name left, "Agent Execution (N steps)" toggle button right. Trace panel logic inlined (replaces deleted `TracePanel.tsx`): step/memory_hit/model_call rows in a `max-h-60` scrollable card using `bg-theme-bg` to blend with page. Auto-collapses trace 500ms after streaming ends. `w-fit` container with `ml-auto`/`mr-auto` so trace card aligns to bubble edges. `relative z-10` on metadata + trace rows fixes canvas dot bleed-through.
- `frontend/src/components/TracePanel.tsx` — **Deleted** (logic absorbed into Message.tsx).

*Input:*
- `frontend/src/components/MessageInput.tsx` — Auto-resize textarea clamped at 138px. `isMultiLine` state: pill → card morph on expansion.

*Sidebar:*
- `frontend/src/components/Sidebar.tsx` — Mini-sidebar collapsed width narrowed from `w-16` to `w-12`, padding `px-1`. Clicking the blank collapsed column expands (outer wrapper has `onClick={onOpen}`; icon buttons call `e.stopPropagation()`). Inner container uses fixed widths (`w-64` expanded, `w-12` collapsed) so the parent clips as a curtain — eliminates "New Chat" text-squish flicker. Profile avatar badge ("H", `w-8 h-8 bg-theme-brand rounded-full`) rendered below settings icon in collapsed state. Delete icon and confirmation popup colors neutralized to zinc (red removed). Conversation item clicks no longer call `onClose`, keeping sidebar open on thread switches.

*Registry API:*
- `backend/app/registry/schemas.py` — Added `providers: List[str] = []` to `ModelResponse`.
- `backend/app/routes/registry.py` — Populates `providers` as sorted unique set of endpoint provider names per model.
- `frontend/src/api/client.ts` — Added `providers: string[]` to `RegistryModel`.

*LAN access:*
- `backend/app/main.py` — Added `http://10.95.144.153:5174` to CORS `allow_origins`.
- `docker-compose.yml` — `VITE_API_URL` set to `http://10.95.144.153:8001` for cross-device testing.

- `frontend/package.json` — Added `react-markdown` dependency.

**Decisions:** LAN IP `10.95.144.153` hardcoded for testing session — revert to `localhost` before merging to main. `react-markdown` over MDX for simplicity; no syntax highlighter added yet. Smart scroll freezes on alignment (not pinned to bottom) for better UX during long streamed responses. Trace auto-collapse delay (500ms after `isStreaming` → false) gives the user a moment to see the final state before it closes.
**Issues:** None.
**Tests:** 47 passing backend (no new backend tests). Frontend TypeScript build: pending verification before merge.
**Commit:** (uncommitted — working tree changes on dev branch)

---

### 2026-06-27 — Phase MU: Multi-User / Auth / BYOK / Google Drive (all code steps)

**Built:** Transformed PAWN from single-user local app to multi-user system.
- **Auth (MA-1..MA-4):** Google OAuth2 (`routes/auth.py`), JWT sessions (`core/jwt_utils.py`, HS256/7-day), `middleware/auth.py` (Bearer → `request.state.user_id`, public `/health` `/auth/*`), AES-256-GCM crypto (`core/crypto.py`), Supabase client (`db/supabase_client.py`). Frontend: `AuthContext`, `LoginPage`, AuthGate, Bearer headers + 401 auto-reload, 429 countdown banner.
- **Drive (DD-1..DD-3):** `storage/drive.py` (DriveStorage), `core/drive_factory.py` (exception-safe `get_drive_for_user` → None → local fallback), `conversations_drive.py`, `documents_drive.py`. Routes + summarize use Drive when available, else local filesystem.
- **Memory (SM-1):** Replaced sqlite-vec with Supabase pgvector. `memory/index.py` add_chunk → insert; `memory/retrieve.py` → pgvector + FTS via RPCs `match_memory_chunks`/`search_memory_chunks` with RRF fusion in Python. `AgentState.user_id` threaded through graph + chat. `supabase/schema.sql` created.
- **BYOK (BK-1..BK-3):** `core/key_store.py` (AES-GCM, exception-safe), `routes/keys.py` (GET/PUT/DELETE; values never returned). `resolver.pick(model_id, user_id)` prefers user key over shared secret. `normalize.chat_stream(..., user_id)`. Frontend `ApiKeysSection.tsx` in `SettingsPage` + Sign out + real email.

**Decisions:**
- App data (profiles, encrypted tokens, BYOK keys, memory embeddings) → Supabase free tier; user data (conversations, uploads) → user's own Google Drive.
- Backend-proxy BYOK (keys decrypted server-side, never reach frontend) — avoids CORS and key exposure. Edge-proxy is a future optimization.
- Graceful degradation everywhere: Supabase/Drive unavailable → fall back to local filesystem and no-op memory, so tests pass without external services.
- `resolver.pick` keeps legacy behaviour when no key resolves (returns all available) so shared-secret/dev/test path is preserved.

**Issues:**
- All existing tests would 401 after auth middleware → added `conftest.py` bypass_auth fixture.
- Test/storage user_id mismatch after scoping → tests pass `user_id="test-user-id"`.
- `KeyError: 'user_id'` in load_context/search_memory nodes (test states lack it) → use `state.get("user_id")`; updated one call-args assertion.
- Rewrote `test_rag.py` to mock Supabase (no live pgvector in tests).
- Fixed pre-existing frontend unused-var build errors (`useCallback`, `isAuthenticated`).

**Tests:** 56 backend tests passing (47 prior + 7 keys + 2 net new rag mocks/agent). Frontend `npm run build` passes clean.
**Blocked on (manual):** Supabase project + `supabase/schema.sql`; Google OAuth2 credentials. Then verify end-to-end and merge dev → main.
**Commit:** (uncommitted — working tree changes on dev branch)

### 2026-06-27 — BK-4: BYOK-only key resolution (drop shared-secret fallback)

**Built:** Provider API keys now come *exclusively* from the user's Settings-configured BYOK keys (Supabase `key_store`); the shared `secrets/*` provider keys are no longer used for LLM or embedding calls.
- `resolver._resolve_key` — removed the `self._secrets.get(ep.secret)` fallback; returns only the user's BYOK key (or "" when none).
- `resolver.pick` — returns only endpoints that carry a usable BYOK key. When the user has no key for any available provider, raises `NoEndpointError("No API key configured for {provider}. Add your provider key in Settings to use this model.")` instead of silently returning unkeyed endpoints.
- `memory/embed.py` — `embed(text, user_id=None)` resolves the Gemini embedding key from the user's `google` BYOK key (`_resolve_gemini_key`); dropped the `from app.config import GEMINI_API_KEY` import. Ollama fallback unchanged.
- `memory/retrieve.py` / `memory/summarize.py` — thread `user_id` into `embed()`; `summarize_history(..., user_id)` passes it to `chat_stream` so summaries use BYOK too.
- Tests: `conftest.py` adds an autouse `stub_byok_key` fixture (patches `key_store.get_key` → `"TEST-BYOK-KEY"`) so the test user "has" keys; `test_keys.py` `test_resolver_falls_back_to_shared_secret` → `test_resolver_raises_when_no_byok_key`; `test_rag.py` mock_embed signatures accept `*args, **kwargs` for the new `user_id` kwarg.

**Decisions:** Kept the now-unused `secrets` constructor param on `Resolver` (and the shared secret files themselves) for backward compatibility — the dependency is removed in behaviour, files can be deleted later. Embeddings degrade gracefully without a key: `retrieve()` already catches embed failures (FTS-only) and summary indexing runs in a background task.
**Issues:** Compose uses `develop.watch` (sync), not a bind mount — running container kept old code until `docker compose up -d --build backend`. Verified live: BYOK key → endpoints resolved without shared key; no key → clear NoEndpointError.
**Tests:** 56 backend tests passing.
**Commit:** (uncommitted — working tree changes on dev branch)

### 2026-06-28 — Perf fix: stop blocking the event loop on Drive/Supabase I/O

**Symptom:** After enabling login, chats had long load times, intermittent "no replies", and history that randomly disappeared. Worked sometimes, broke under any concurrency.

**Root cause:** The multi-user path (commit 410e4b7) introduced synchronous, blocking I/O — Google Drive (`googleapiclient`) and Supabase (`supabase-py`) — called directly inside `async def` routes and async LangGraph nodes. FastAPI runs on a single event loop; a blocking call there freezes *every* concurrent request. A single chat with a `conversation_id` did ~12 serial Drive round-trips (meta + messages + summary, each re-resolving folders by name) before the LLM even started, plus blocking Supabase calls for BYOK keys (per reasoning step) and memory retrieval. No timeouts meant a stalled Drive call hung the request forever. Drive's eventually-consistent name queries (`find_file` right after a write) returned None → "disappearing history".

**Built:**
- `storage/drive.py` — socket timeout (`AuthorizedHttp(creds, httplib2.Http(timeout=20))`); re-entrant lock guards all API access (the instance is now shared across threadpool workers, and googleapiclient's transport isn't thread-safe); file-ID cache so reads go by ID via `get_media` (strongly consistent) instead of name queries; caches cleared on delete.
- `core/drive_factory.py` — per-user `DriveStorage` cache (TTL 10 min live / 30 s for not-linked) + `evict_user()`; avoids refetching tokens and rebuilding the service every request. `auth.py` evicts on (re)link.
- `core/key_store.py` — short-TTL decrypted-key cache + `prefetch(user_id)` (one query warms all providers); `set_key`/`delete_key` evict.
- Routes (`chat.py`, `conversations.py`, `upload.py`) and `memory/summarize.py` — every blocking Drive/Supabase/`key_store`/PDF-parse call moved off the loop via `run_in_threadpool`; conversation reads batched into a single hop. `chat.py` warms the key cache once per request.
- `memory/retrieve.py` — the two Supabase RPCs wrapped in `asyncio.to_thread`.

**Decisions:** Kept Drive as the conversation store (per user direction) and fixed it in place rather than migrating to local FS/Supabase. Consistency relies on the cached instance's file-ID map surviving across requests; the brief not-linked cache window is self-healing.
**Issues:** Caching `None` from a Supabase blip could mask a linked user's Drive (showing empty local storage); mitigated with a short 30 s TTL on negative results and a 10 min TTL on live instances.
**Tests:** 56 backend tests passing (unchanged).
**Commit:** (uncommitted — working tree changes on dev branch)
**Next (manual verify):** Live test under Docker with a linked Drive — concurrent chats, no event-loop stalls, history persists across reloads.

### 2026-06-28 — PERF-2: Instant conversation UX (optimistic UI + client cache + fail-proof sync)

**Symptom (Drive mode):** New chat slow + created duplicates; switching laggy ("won't open then suddenly loads"); delete slow/unreliable (row lingered, double-clicked); messages glitched/disappeared after send.

**Root cause:** Every conversation action awaited slow Drive round-trips with no client cache, and `onDone` ran a full-list refetch that *reset* `activeConvId`, re-firing the load effect and reloading messages from eventually-consistent Drive — clobbering the just-streamed turn.

**Design (user-approved plan):** Make the client the source of truth. Client-owned UUIDs + localStorage cache drive the UI instantly; Drive persistence drains in a fail-proof background queue; server fetches become reconciliation merges, never authoritative resets.

**Built:**
- Backend (2 small edits): `conversations.py` `ConversationCreate.id` + idempotent `_create` (returns existing meta if the id exists); `chat.py` lazy-creates the conversation when `conversation_id` meta is missing instead of 404 (so the first message materializes it). Both storage backends already accept `conv_id`; no test depended on the 404.
- Frontend store layer (new): `store/ids.ts` (UUID + collision-free message ids), `store/conversationCache.ts` (per-user localStorage cache of list + messages; debounced save; LRU(30) + ~4 MB eviction; corruption-safe load; `mergeServerMeta` merge rules), `store/syncQueue.ts` (persisted create/rename/delete queue with exponential backoff, idempotent ordering, DELETE-404-as-success, drains on `online`, survives reloads), `store/useConversationStore.ts` (single owner of list/messages/active selection + optimistic mutators + bootstrap/reconcile).
- `client.ts`: `createConversation(..., id?)`; `deleteConversation` treats 404 as success.
- `App.tsx`: removed `conversations`/`activeConvId`/`messages` local state, the awaiting switch effect, and the `handleCreate`/`handleDelete`/`handleRename`/`refreshConversations` handlers; wired to the store. Messages are keyed by conversation, so a stream writes to its **captured** conv id even if the user switches away. `onDone` now does `bumpAfterTurn` (local list update) + debounced `quietTitleRefresh` (title-only merge) instead of the disruptive full refetch.
- `Sidebar.tsx`: removed the stale empty-chat dedupe (now race-free in the store); added pending-sync dots + an offline banner.

**Decisions:** Full fail-proof persisted sync queue (not lighter in-memory) and localStorage-persisted messages — both chosen by the user. On switch, trust cache and only background-fetch when a conv has NO cached messages (avoids clobbering just-sent turns under Drive eventual consistency).
**Issues:** Streaming-during-switch required moving message ownership into the store keyed by conv (App's single `messages` buffer would have appended to the wrong conversation). Multi-device + trace persistence are documented limitations.
**Tests:** 57 backend tests passing (added `test_chat_lazy_creates_unknown_conversation`); frontend `npm run build` clean.
**Commit:** (uncommitted — working tree changes on dev branch)
**Next (manual verify):** Browser test under slow Drive — instant new-chat (no dupes) / switch / delete; messages persist + reconcile after reload; kill backend → ops queue in `localStorage['pawn-syncq:*']` and drain on restart/`online`.

### 2026-06-28 — PERF-2a: Draft "New Chat" (no persistence until first message)

**Change:** New Chat no longer creates anything on the backend. It opens a frontend-only *draft* (welcome page, empty in-memory buffer); the conversation is materialized — sidebar row + Drive file — only when the first message is sent.

**Built:**
- `store/useConversationStore.ts`: added `draftConvId` state; `createConversation()` now opens/reuses the single draft (no list insert, no `create` enqueue, no network); new `promoteDraft(id)` adds the meta to the list at first send and clears the draft. Persist effect excludes the draft from the localStorage cache.
- `App.tsx` `handleSend`: calls `promoteDraft(convId)` before streaming (no-op for already-real convs); the chat route's lazy-create writes it to Drive on that request. Sidebar `onCreate` simplified to `createConversation()`.
- `store/syncQueue.ts`: the `create` op is now unused (commented as defensive/kept).
- Behavior contract documented in `workspace/decisions/draft_new_chat.md`.

**Decisions:** Sidebar shows NO row for the draft (user choice) — the titled row appears only after the first message. At most one draft → no duplicate empty chats. An unsent draft does not survive reload (nothing to persist).
**Tests:** No backend change (lazy-create already covered). Frontend `npm run build` clean.
**Commit:** (uncommitted — working tree changes on dev branch)
**Next (manual verify):** New Chat → no network request, no sidebar row, welcome page; spam → one draft; first message → row + one `POST /chat` lazy-create; reload → row+messages persist.

### 2026-06-28 — Per-conversation streaming (concurrent chats)

**Built:** "Is generating" and the rate-limit cooldown were global single values, so sending in one chat blocked sending in every other chat while it streamed. Made both per-conversation. Store: `streamingConvIdRef` (single) → `streamingConvIds: Set<string>` state + ref; `setStreaming(convId, on)` add/removes; `selectConversation` refetch-skip guard uses `.has(id)`. App: removed the global `isStreaming` and the four singleton stream refs (`abortRef`/`streamingIdRef`/`lastUserRef`/`streamConvIdRef`), replaced with one `streamsRef: Map<convId, {assistantId, controller, userMsgId, userContent}>`. Composer/ChatWindow now gate on `isActiveStreaming` (active conv only). Rate limit moved from one `rateLimitCountdown` to `rateLimitUntil: Record<convId, epochMs>` with a single 1s ticker; the active conv's remaining time is derived.
**Decisions:** `handleStop` targets the conversation currently being viewed (each has its own AbortController). Send is blocked only for the conv already streaming, not globally. `isUploading` stays global (active-conv attachment action). Per-conversation drafts remain out of scope — `draft` is still one shared input for the active conv.
**Tests:** No backend change. Frontend `npm run build` clean (tsc + vite).
**Commit:** (uncommitted — working tree changes on dev branch)
**Next (manual verify):** Open chat A, send long prompt; while streaming switch to B and send → both stream; switching back to A still shows live tokens + Stop; Stop restores A's text; rate-limit A → only A's composer shows countdown, B sendable; second send into a streaming chat still blocked.

### 2026-06-28 — Key-aware model selection + cross-model rate-limit failover

**Built:** Fixed two BYOK issues: (1) selecting a Google model still errored "No API key configured for cerebras", and (2) no fallback when a provider was rate-limited.
- **Root cause of cerebras error:** when the user's Gemini endpoint got rate-limited, the agent's `pick_model_by_capability("fast")` (graph.py) fell through to the next available fast model — GLM 4.7 (Cerebras) — because it only checked `active`+`can_use`, never whether the user had a key. `normalize.chat_stream → resolver.pick(user_id)` then rejected it.
- **resolver.py:** `pick_model_by_capability`/`pick_by_capability` now take `user_id` and only consider models with ≥1 endpoint the user holds a key for (new `_has_usable_endpoint`). Added `usable_user_models(user_id)` and `fallback_models(model_id, user_id)` (requested model first, then other usable models, same capability_level first).
- **normalize.py:** extracted `_stream_one_model` (per-endpoint failover, unchanged) and rewrote `chat_stream` to iterate `fallback_models` — on rate-limit/no-endpoint *before the first token*, it switches to another usable model (new `on_model_switch` callback); mid-stream errors still propagate (can't restart a partial reply).
- **graph.py:** agent/ask_model nodes pass `user_id` and fall back to `state["user_model_id"]` on `NoEndpointError`; all three model-calling nodes pass `on_model_switch` (reuses the existing "Failing over" provider_switch notice). `DummyResolver` updated.
- **Frontend:** `App.tsx` fetches the user's configured providers via `getKeys()` and derives `availableModels` (models served by ≥1 keyed provider); the composer picker + Settings default-model list now show only usable models. Selection/default coerce to a usable model when the current pick isn't available. Empty-state hint links to Settings. Key add/remove triggers `onKeysChanged` → re-fetch so the picker updates without reload.

**Decisions:** `/registry/models` stays the global catalogue; per-user filtering is a frontend view concern. Cross-model fallback only triggers before the first token. "grok" = Groq (no separate xAI provider).
**Tests:** Backend 66 passed (added `test_resolver.py`, `test_normalize_fallback.py`). Frontend `npm run build` clean. Backend + frontend images rebuilt and running (8001/5174 healthy).
**Commit:** (uncommitted — working tree changes on dev branch)
**Note:** Earlier `drive.py` client_id/secret fix was baked into the image with this rebuild (the dev `watch` sync wasn't running, so prior `restart` hadn't picked it up).

### 2026-06-28 — Image-gen pipeline working (T4 fix + deploy auto-queue) [imageLab]

**Context:** Milestone A.0 image generation (SDXL on the user's own Kaggle account) had the kernel transport working but two blockers stopped end-to-end generation.

**Built / fixed:**
- **T4 GPU fix** (`core/kaggle.py`): runs always landed on a P100 (Pascal) and failed with CUDA kernel mismatch / `Torch not compiled with CUDA enabled`. Root cause: the `/kernels/push` body sent the GPU type under `accelerator`, which Kaggle silently ignores → default P100. The wire field is `machineShape` (the SDK's `machine_shape` / CLI `--accelerator`; valid values `NvidiaTeslaT4`, `NvidiaTeslaP100`, `Tpu1VmV38`). Changed `body["accelerator"]` → `body["machineShape"]`. `generate_image` already passes `NvidiaTeslaT4`. Verified live: image returned in ~127s.
- **Deploy → "Kaggle is busy" auto-queue** (`core/kaggle.py`, `constants.py`): a Kaggle push always starts a run, so the deploy warmup leaves the slug `queued`/`running` for ~1–2 min; clicking Generate during that window hit the pre-flight busy check and errored instantly. Replaced the immediate raise with `_wait_until_idle(...)` — polls `/kernels/status` until the slug reaches any terminal state (complete *or* failed, so a failed warmup doesn't block), bounded by new `KAGGLE_BUSY_WAIT_TIMEOUT_SECONDS = 300`; only raises "still busy" if it never frees. `run_kernel` gains a `busy_wait_timeout` param. Generate now transparently queues behind the warmup.
- **Frontend** (`ImageLabPage.tsx`): running indicator now notes it "waits for warmup if just deployed"; Generate stays enabled (backend queues).

**Decisions:** Backend auto-queue chosen over a frontend cooldown/readiness-poll — no time guessing, no new endpoint, robust to variable warmup duration (user-approved plan).
**Issues:** Public Kaggle API has no documented value for dual T4 (T4×2) — issue #821 unanswered; we use a single T4. Image quality not yet tuned (out of scope for now).
**Tests:** 13 `test_generate.py` tests passing (3 new `_wait_until_idle` tests: waits-through-inflight, times-out, proceeds-on-non-200). Frontend `npm run build` clean.
**Commit:** (this commit)

### 2026-06-29 — W.0: persistent Kaggle loop proof (CPU echo) + Supabase rendezvous [imageLab]

**Context:** Phase W Step W.0 — the load-bearing risk for warm sessions is *"can a batch-pushed Kaggle kernel run a long-lived internet loop for tens of minutes?"* De-risked it with the cheapest payload (CPU echo, no GPU/model), exactly as the cube POC de-risked the transport.

**Built:**
- **Schema** (`supabase/schema.sql`): `image_sessions` + `image_jobs` tables (+ indexes). RLS intentionally left disabled for the single-user W.0 trial (anon key has full access — the documented fallback); scoped per-session JWT + RLS policies are the W.1 deliverable.
- **CPU echo notebook** (`kaggle_templates/session_poc/notebook.ipynb`): decodes the injected payload, PATCHes `status='ready'`, then loops on Supabase REST (`requests`): heartbeat each iteration, echo any pending job's prompt into `image_b64`, honor stop/timer/cap, exit cleanly.
- **Session manager** (`core/image_session.py`): `start_session` (evict prior live → insert row → inject anon key + url payload → non-blocking `kaggle.deploy_kernel` push, CPU/internet, no dataset), `get_session_status` (liveness = status + fresh heartbeat + before expiry), `stop_session` (cooperative flag), `submit_session_job` (alive-guard → queued row), `get_job`. All Supabase/Kaggle calls blocking → routes off-load via `run_in_threadpool`.
- **Routes** (`routes/generate.py`): `POST /generate/session/start|job|stop`, `GET /generate/session/status`, `GET /generate/job/{id}`. Session start reuses the per-`(user,model)` lock.
- **Config/secrets**: new `supabase_anon_key` (PUBLIC) via `read_secret` + docker-compose `secrets:` block + committed `.example`; real file gitignored. Service key is NEVER injected into the notebook.
- **Constants**: poll interval (3s), heartbeat-stale (30s), max-duration backstop (120 min), POC slug/template path.
- **Frontend**: `client.ts` helpers (start/status/job/stop/getJob, typed `SessionStatus`/`JobResult`); minimal `components/SessionPocPanel.tsx` (duration/cap picker, live countdown, submit echo job + poll, Stop) wired into `ImageLabPage` under the active model when connected.

**Security:** Audited (security-auditor PASS, 0 critical) — only the public anon key + url reach the notebook (dedicated test base64-decodes the payload and asserts the service key is absent); payload base64-injected (no code injection from prompt); no key logging. Code-reviewer PASS, 0 critical. WARN fixes applied: `start_session` fails early (412) if Supabase url/anon key missing; `submit_session_job` rejects jobs to a non-live session; conftest seeds `SUPABASE_ANON_KEY`. Deferred to W.1 (documented WARNs): RLS policies + scoped JWT (session_token is inert until then).

**Tests:** 117 backend passed (24 new in `test_image_session.py`: manager + all 5 routes, mocked Supabase/Kaggle). Frontend `npm run build` clean.
**Live verify (manual, pending user setup):** run the new schema in Supabase + add `secrets/supabase_anon_key`, then Image Lab → connect → Start warm session → submit echo job → watch the CPU kernel pick it up, echo back, heartbeat, and exit on Stop/expiry.
**Commit:** (this commit)

### 2026-06-29 — W.0 LIVE-VERIFIED + new-key RLS gotcha [imageLab]

**Live result:** Image Lab → Start warm session → kernel reached **Warm** with a live countdown (29:12) and fresh heartbeat; 2 echo jobs round-tripped through Supabase (queue → kernel pickup → result write → UI read-back: "ECHO: really"). The load-bearing assumption — a batch-pushed Kaggle kernel can run a long-lived internet loop + Supabase rendezvous — is **PROVEN**.
**Gotcha caught by the probe (before any Kaggle run):** Supabase's new `sb_publishable_*` key enforces RLS on the anon role, so "RLS off for the trial" didn't hold — the kernel could READ but INSERT/PATCH 401'd (`42501`). Fix: enable RLS + a permissive anon policy on `image_sessions`/`image_jobs` (commit `043a7f3`) — the documented "anon-key-open on the two dedicated tables" trial fallback. Re-probe confirmed READ/INSERT/PATCH/DELETE all succeed with the publishable key. W.1 narrows this to a scoped per-session_id policy.
**Commit:** 043a7f3 (RLS fix) + tracker/state updates.

### 2026-06-29 — W.1: warm FLUX serve-loop + unified durable job layer [imageLab]

**Built:**
- **FLUX persistent notebook** (`kaggle_templates/image_flux_session/notebook.ipynb`): cell-0 payload + Supabase REST helpers (anon key bearer; `session_jwt` honored if present — W.1 follow-up); cell-1 pip install; cell-2 load FluxPipeline ONCE (bf16, balanced device_map across 2× T4, VAE tiling, CPU-offload fallback) → PATCH `ready`+heartbeat (or `error`+exit); cell-3 serve loop (heartbeat, honor stop/timer/cap, 4-step/guidance-0/1024² inference → PATCH job `done`+PNG b64).
- **Registry-driven sessions** (`core/image_models.py`): `ImageModel` gains `session_template`/`session_slug`/`session_gpu`. FLUX → real GPU serve-loop (`pawn-flux-session`); SDXL → CPU echo POC (cheap loop/monitor testing without GPU). `start_session` reads these (GPU+dataset for FLUX, CPU/no-dataset for echo).
- **Session manager** (`core/image_session.py`): `extend_session` (bump `expires_at`, capped at the 120-min backstop, rejects a non-live session).
- **Unified durable job layer (the bug fix)**: `create_cold_job` (de-dup — a queued/running `(user,model)` job returns the same id, no duplicate row), `run_cold_job` (background worker: queued→running→done writing `image_b64`/`via`; never raises — records a truncated error), `list_jobs` (metadata only, no image bytes), `reap_stale_jobs` (cold job stuck `running` past `COLD_JOB_MAX_WALLCLOCK_SECONDS=1200` → `error`).
- **Routes** (`routes/generate.py`): `POST /generate {image}` now non-blocking → `{job_id, status:"queued"}` + GC-safe `_spawn_bg(_run_cold_job_bg(...))` behind the per-`(user,model)` lock; `GET /generate/jobs`; `POST /generate/session/extend`.
- **Frontend (minimal — full panel is W.2)**: `client.ts` `runGenerate`→`{job_id}`; `runKaggleImage` now submits+polls `getJob` (cold Generate keeps working); `extendSession`/`listJobs`; `JobResult` gains `done_at`/`has_image`/`session_id`. `SessionPocPanel` renders PNG (FLUX) or echo text (SDXL); labels/heading generalized.

**Review:** code-reviewer initially FAIL — **CRITICAL**: `asyncio.create_task` keeps only a weak ref, so a GC cycle mid-Kaggle-call could collect the worker and strand a job at `running`. Fixed with a module-level `_bg_tasks` set + `add_done_callback` (`_spawn_bg`). WARNs fixed: `extend_session` live-check, `run_cold_job` error truncated to 300 chars + stderr log, `reap_stale_jobs` stderr log, `JobResult` fields, docstring. security-auditor PASS (only the public anon key is injected; service key never reaches the notebook; payload base64-injected).

**Decision (documented):** scoped per-session JWT (`supabase_jwt_secret`) **deferred within W.1**. Supabase's new `sb_publishable_*` key platform enforces RLS on the anon role and deprecates the legacy HS256 JWT-secret minting the plan assumed — so the permissive-anon RLS policy from W.0 is kept for the single-user trial. The scoped JWT becomes **mandatory before multi-user** (the new keys can't bypass RLS). A real SDXL serve-loop is a follow-up.

**Tests/build:** 132 backend passing (new `test_image_jobs.py`: create/de-dup, run_cold_job transitions, reap, list, non-blocking route, `/generate/jobs`; `test_generate.py`/`test_image_session.py` updated to the job contract + extend/FLUX-GPU-start tests). Frontend `npm run build` clean.
**Live verify pending:** Image Lab → FLUX → Start warm session → first image ~10 min, later images in seconds; Extend/Stop; cold Generate still returns an image (now job-polled).
**Commit:** (this commit)

### 2026-06-29 — W.2: Image Lab UI (session controls + Generations monitor) [imageLab]

**Built (frontend):**
- **Job-driven `ImageGenerator`** (`ImageLabPage.tsx`): submit → poll `getJob` → inline render. **Server-derived button state** — parent lifts a shared `listJobs` poll (all models); Generate is disabled while that model has a `queued`/`running` job, so a refresh / second tab can't fire a duplicate (the double-submit bug, now structurally prevented). Routes to `submitSessionJob` when a warm session is live (fast) else cold `runGenerate`. Added a local `submitting` guard for the click→response window.
- **`GenerationsPanel.tsx`** (new): collapsible monitor of all jobs across models/sessions, newest first — model badge, prompt, status chip (running spinner), relative time; done image jobs lazily fetch their PNG via `getJob` → thumbnail + View lightbox + Download. Server-backed → a navigated-away result reappears here (lost-result bug visibly fixed).
- **`SessionBar.tsx`** (new): per-model warm-session lifecycle — duration/cap picker, Start, live countdown, Extend +30, Stop, "session ended" CTA; re-attaches on mount via `getSessionStatus`; reports the live session up to the generator. `SessionPocPanel` deleted (superseded).

**Review:** code-reviewer PASS (0 critical). WARN fixes applied: (1) double-submit window → local `submitting` guard on top of the server-derived `busy`; (2) always-on 1s ticker → gated on a live countdown; (3) hardcoded lightbox download filename → derived from the image mime. Deferred (documented): frontend unit tests (project has none — gate is `npm run build`); GenerationsPanel lazy-image fan-out is bounded by the 30-job list cap (fine for the trial).

**Tests/build:** 132 backend tests still green (no backend change); frontend `npm run build` clean. **Phase W code-complete (W.0/W.1/W.2).**
**Live verify pending:** full warm-FLUX flow + monitor; refresh mid-generate → job re-attaches in the panel and Generate stays disabled. Then merge imageLab → dev. Scoped per-session JWT remains the gate before multi-user.
**Commit:** (this commit)

### 2026-06-29 — Fix: orphaned session jobs hung the panel/button (reap gap) [imageLab]

**Symptom:** Generate button stuck on "Generating (cold ~14 min)…" with nothing actually running on Kaggle; Generations showed "1 active". Root cause: a job submitted to an SDXL warm session stayed `queued` after the session **ended** (kernel exited before picking it up). `reap_stale_jobs` only handled cold jobs (`session_id` null) stuck `running` past the wall-clock — it never reaped **session** jobs whose session is dead, so the server-derived button state stayed disabled forever.
**Fix** (`core/image_session.py` `reap_stale_jobs`): now also (a) reaps cold jobs stuck in *any* active status (queued or running) past the wall-clock (a queued cold job whose in-process worker died on a backend restart), and (b) reaps queued/running **session** jobs whose session is no longer alive (ended/stopped/expired/stale heartbeat) → marked `error` "session ended before this job ran". Since `list_jobs` calls reap every poll, the panel + button self-heal within ~3s. The pre-existing stuck job was auto-cleared on redeploy.
**Tests:** 133 backend passing (added `test_reap_stale_jobs_reaps_jobs_of_dead_sessions`; renamed the cold reap test).
**Commit:** (this commit)

### 2026-06-30 — W.4/W.5/W.6: startup observability + liveness fixes + per-model panels [imageLab]

**Built:**
- W.4: Notebooks patch `installing` → `loading_model` → `ready` at phase boundaries. `_LIVE_STATUSES` extended to include both new statuses. `SessionBar` shows phase-specific messages ("Waiting for Kaggle GPU…" / "Installing dependencies…" / "Loading model onto GPU…"). Type comment in `client.ts` updated.
- W.5: Tab switcher (`activeModelId` state + tab bar) removed from `ImageLabPage`. Replaced with always-mounted stacked `ModelPanel` components — each owns its own jobs poll, `SessionBar`, `ImageGenerator`, and `GenerationsPanel`. No cross-model state sharing; switching away no longer resets timers or countdowns.
- W.6: `IMAGE_SESSION_HEARTBEAT_STALE_SECONDS` raised 30 → 90 s (fixes false "Session ended" during FLUX inference). `create_cold_job` blocks with HTTP 400 when a warm session is already live for that model. Kaggle GPU limit error detected by message text and surfaced as human-readable error. `SessionBar` shows a confirm dialog before re-Start when a session exists.
**Decisions:** Warmup-phase queuing (W.4) required extending `_LIVE_STATUSES` first so new statuses aren't treated as dead sessions by `_is_alive` and `reap_stale_jobs`.
**Tests:** (see commit 5728b9e)
**Commit:** 5728b9e — Stable: fix session reaping, heartbeat gaps, and UI crash in image pipeline; add warmup-phase queuing and multi-prompt queue support

---

### 2026-06-29 — W.3: real SDXL warm serve-loop (warm sessions generate images, not echo) [imageLab]

**Why:** A warm session on the SDXL tab returned `ECHO: <prompt>` text — SDXL's session was wired to the W.0 CPU-echo POC (placeholder; "real SDXL serve-loop is a follow-up"). Only FLUX had a real warm serve-loop. User wants warm image generation for SDXL too (load once → generate many).
**Built:**
- `kaggle_templates/image_sdxl_session/notebook.ipynb` (new): mirrors the FLUX serve-loop structure (cell-0 payload + Supabase REST helpers; cell-1 install; cell-2 load SDXL ONCE via `AutoPipelineForText2Image.from_pretrained(..., torch_dtype=float16, use_safetensors=True, local_files_only=True).to("cuda")` → PATCH `ready`/`error`; cell-3 serve loop with SDXL inference 4 steps / guidance 0 / 512×768 → PATCH job done + PNG, `via kaggle:sdxl-session`).
- `core/image_models.py`: SDXL entry repointed — `session_template=image_sdxl_session`, `session_slug="pawn-sdxl-session"`, `session_gpu=True` (start_session then mounts the SDXL dataset + T4). Dropped the now-unused `KAGGLE_SESSION_POC_TEMPLATE`/`KAGGLE_SESSION_SLUG` imports (constants + session_poc notebook remain as the W.0 artifact, unreferenced).
- No frontend change — `ImageGenerator`/`GenerationsPanel` already render PNG vs text by MIME.
**Decision:** kept the cold path's 4 steps / guidance 0 / 512×768 for consistency (SDXL quality tuning is a separate pre-existing deferred item). The CPU echo POC stays in the repo (W.0 artifact) but is no longer user-facing — both SDXL + FLUX warm sessions are real now. SDXL loads in ~1–2 min (single T4, ~7GB fp16) vs FLUX ~10 min.
**Tests:** 134 backend passing — rewrote `test_start_session_inserts_row_and_pushes_cpu_notebook` → `test_start_session_sdxl_uses_gpu_serve_loop` (asserts GPU + dataset + `pawn-sdxl-session`); added `test_session_slug_titles_round_trip` (Kaggle title↔slug invariant for session slugs). The anon-key-only security test (runs on sdxl) still passes → no service key in the SDXL session push.
**Live verify pending:** SDXL → Connect → Warm session → Start → `Warm` in ~1–2 min → Generate returns an image in seconds (`via kaggle:sdxl-session`); thumbnails in Generations.
**Commit:** (this commit)

---

### 2026-06-30 — Plan 1.0: Generations panel UI fixes [imageLab]

**Why:** Five targeted UX gaps in the Generations monitor panel: (1) "6 active" header conflated queued and running; (2) no way to see how long a generation actually took; (3) style preset not visible on job rows; (4) no way to reuse a prompt; (5) killing a Kaggle notebook externally left running jobs stuck forever in "running" state.
**Built:**
- **Fix 1 (header):** Split `N active` into `N running · M queued`; running segment uses amber colour, queued uses muted text; either segment hidden if count is 0.
- **Fix 2 (gen time):** `⏱ Xm Ys` shown at right of each row's second line — live ticking every second for running jobs (1 s `setInterval` in `JobRow`), fixed `started_at→done_at` duration for done/error jobs, hidden for queued or when `started_at` is null. `started_at` added to `_JOB_LIST_COLUMNS` and `list_jobs` dict (was selected but not mapped); `JobResult.started_at` added to `client.ts`.
- **Fix 3 (style preset tag):** Small pill badge in the top-right of the first line when `job.params?.style_preset` is set; key inverted to human-readable label via `STYLE_PRESET_LABELS` map in `GenerationsPanel`. `params` added to `_JOB_LIST_COLUMNS`, `list_jobs` dict, and `JobResult` type.
- **Fix 4 (copy button):** Clipboard icon button per row copies the full `job.prompt`; swaps to a green checkmark for 1.5 s then resets. Timer cancelled on unmount.
- **Fix 5 (session-death failover):** `reap_stale_jobs` now fetches full session rows and uses `_is_alive()` (which includes heartbeat-stale detection) instead of a structural status check. Running session jobs for non-alive sessions are also failed with "Session terminated unexpectedly" (previously only queued jobs were touched). This handles the case of a notebook being manually killed — on the next 3 s panel poll the job flips to error with `done_at` set.
- **View/Download buttons:** Stacked vertically (column) at far right of each row with image.
**Decisions:** Reaping running session jobs is now gated by `_is_alive()` (90 s heartbeat-stale threshold), which provides enough buffer for warm-session FLUX inference (typically seconds, not minutes).
**Tests:** 136 backend passing (updated `test_reap_stale_jobs_reaps_jobs_of_dead_sessions` to assert both the queued and running reap updates); `npm run build` clean.
**Commit:** (this commit)
