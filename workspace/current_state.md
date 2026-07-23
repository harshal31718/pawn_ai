# PAWN — Current State

Last updated: 2026-07-23

**PAWN 2.0 Phase C done (shared-pool fair-share quota, OmniRoute port):**
`core/quota_share.py` ports OmniRoute's `enforce.ts`/`fairShare.ts` into
PAWN's simpler shape (equal 1/N weight, tpd+rpd only, per-provider
`saturation_pct` from B.2). `registered_user_count()` is lazily cached per
UTC day. `rate_limiter.record_call`/`record_tokens` gained a `key_source`
param that mirrors pool-sourced usage into the R2-reserved `SHARED_USER`
aggregate row. `resolver.pick()`'s return tuple grew a 6th element
(`key_source`, computed once via a new `_resolve_key_and_source()` so it
can't disagree with the key actually used) — `quota_share.enforce()` runs
inside `pick()`'s loop, gated on `key_source == "pool"`, and a block simply
removes that endpoint from the candidate list so the existing
`fallback_models` failover picks it up. A real bug (absolute-pool-cap check
only applied inside the generous-mode branch, letting a saturated pool's
strict-mode fair-share math be bypassed by a brand-new zero-consumption
user) was caught by the port's own tests and fixed by porting OmniRoute's
separate, policy-independent cap check explicitly. 755 backend tests green,
`tsc` clean, live-verified via Chrome (real chat round-trip through the new
6-tuple pipeline). Not live-verified: actual N>1 division (solo dev, N=1) —
covered by unit tests with injected N instead. D (Providers page) is next.

**PAWN 2.0 Phase E.4 code plumbing done, tunnel activation deferred to the
user:** `postgres_client` functions gained an optional `dsn` override
(default `POSTGRES_DSN`, zero behavior change), new `config.SHARED_DB_DSN`,
`key_store`/`pool_key_store` now route through it via thin wrappers. New
profile-gated `keys-tunnel` docker-compose service (forward SSH tunnel to
prod's Postgres) + `keys_tunnel_key`/`shared_db_dsn` secrets — deliberately
NOT activated: doing so needs a live change to the production VM's SSH
`authorized_keys` and copying prod's real `ENCRYPTION_SECRET` onto this dev
machine, both of which need the user's own hands. 738 backend tests green,
`docker compose config --quiet` validates the new config, live-verified the
current stack is unaffected (`/keys` and a real chat round-trip both still
work). E.5 (the isolation verification checklist) is blocked on the user
completing that VM step.

**PAWN 2.0 Phase B done (admin role + DB-backed pool keys + admin page):**
`core/admin.py` (`ADMIN_EMAIL`, `is_admin`, `require_admin`), new
`pool_api_keys` Postgres table + `core/pool_key_store.py` (encrypted,
short-TTL cache, admin-editable live), `config.read_pool_key()` now DB-first
with the Docker secret as a bootstrap fallback (Phase 1b's `@lru_cache`
removed — it would have frozen live edits forever). `routes/admin.py`
(pool-key CRUD + enable/disable + registered-user count), all behind
`Depends(require_admin)`. Frontend `AdminPage.tsx` + a Sidebar entry gated on
`user.is_admin` (threaded from `/auth/me` and the OAuth callback payload).
Also standardized `ProvidersPage.tsx`/`AdminPage.tsx` onto the same floating
pill header as Settings, and added a global admin badge next to the
dark-mode toggle. 729 backend tests green, live-verified end-to-end via curl
(real admin JWT: PUT/GET/PATCH/DELETE all persisted/read correctly against
Postgres) and via Chrome (non-admin gets a graceful in-page 403 message, no
Admin nav entry). E.4–E.5 (shared keys DB) next, since they depend on this.

**PAWN 2.0 Phase A done (BYOK-first precedence flip):**
`resolver._resolve_key` and `dashboard._usable_key_source` now check the
user's own BYOK key before the operator's pool for `either` endpoints
(reverses Phase 1b's pool-first default) — the pool is a fallback for
keyless users only. 696 backend tests green, live-verified via Chrome
(`/providers` renders correctly, all-BYOK as expected with no pool keys
configured locally).

**PAWN 2.0 Phase E.1–E.3 done (dev/prod env isolation):** `config.PAWN_ENV`
(`dev`/`prod`, safe default `dev`) drives `constants.DRIVE_ROOT_NAME`
(`"PAWN-dev"`/`"PAWN"`, wired through `drive.py`'s `get_or_create_root()`) and
`constants.kaggle_slug()` (suffixes `-dev` onto `KAGGLE_CUBE_SLUG`,
`KAGGLE_SESSION_SLUG`, and both SDXL/FLUX cold+session Kaggle slugs outside
prod). `.env.prod.example`/`.env.staging.example`/local `docker-compose.yml`
all set it explicitly. Two real pre-existing bugs found and fixed along the
way (neither caused by this work): `config.read_secret()` used `path.exists()`
instead of `is_file()` — a Docker secret with a missing source file gets
bind-mounted as an empty directory on this Docker Desktop/Windows host,
raising `IsADirectoryError` instead of falling through to the env-var
fallback; and 6 mock `stream_llm` replacements in
`test_chat.py`/`test_summarize.py` were missing `**kwargs`, silently dropping
R2's `on_usage` callback with a `TypeError` masked as a generic
`ProviderError` (same bug class as a previously-documented fix, a second
missed pocket of it). Also applied the previously-pending
`2026-07_R2_endpoint_usage.sql` migration to local dev Postgres (the other 4
pending migration files turned out already applied). 695 backend tests green
(up from 68-failing before either fix), `pytest -n auto` clean, `tsc --noEmit`
clean, live-verified via Chrome (real chat round-trip through Google, no
console errors). E.4–E.5 (shared keys DB) deferred until Phase B lands, per
the plan's own dependency order. See `workspace/plan/architecture_2.0/00_overview.md`
(gitignored, local-only) and `build_tracker.md`'s PAWN 2.0 section.

**Model routing is capability-first (C1–C5) + free-tier registry expanded
(R1) + token-accurate quota (R2) + free-tier dashboard (R3) + two-tier
BYOK/pool keys (Phase 1b) — all `[x]` in `build_tracker.md`, real-pytest
verified 2026-07-21.** The backend's actual dependencies were installed into
the sandbox (not Docker, but the real packages) and `pytest` ran for real for
the first time this session: 676 passed, 15 failed. All 15 share one root
cause — an unpinned `langgraph>=0.3.0` floor let this sandbox install 1.2.9,
which broke `adispatch_custom_event`'s stricter run-id requirement; confirmed
via a deliberate downgrade attempt, not assumed. 14 other real, pre-existing
bugs (stale test assertions from C2's task_type addition, a self-referential
datetime monkeypatch, mock signature drift) were found and fixed along the
way; none were caused by this session's changes.

**2026-07-23 follow-up, closed:** the two items left open above are now done.
`requirements.txt` pins `langgraph>=1.2.0,<2.0.0` /
`langgraph-checkpoint-sqlite>=3.0.1,<4.0.0` (1.2.x is the confirmed-working
version from the 2026-07-21 run; 0.6.x is the confirmed-broken one) —
un-verified against a real `pip install` this session, next `docker compose
build` is the real test. Pool secrets are now wired into
`docker-compose.yml` (all 11 `pool_<provider>_api_key` entries, top-level +
backend service) at the user's request ("wire structure only" — no real key
files created). Confirmed live via a scratch `docker compose up` probe that
this Compose version (`v5.0.0`) tolerates a missing secret source file
(warning only, exit 0) — the earlier note that `required: false` was needed
first was checked and found wrong (`required` isn't a valid field on a
top-level secret at all in this version) and removed.

- **R1:** 5 new OpenAI-compatible free providers (mistral, nvidia, zhipu,
  sambanova, kluster). Registry 22 → 31 models, 30 → 47 endpoints, 6 → 11
  providers. Needed no new provider request code — `_provider_headers()` already
  emits plain bearer auth for everything non-Anthropic. Caught a CRITICAL:
  `EndpointEntry.provider` is a `Literal`, so all 17 new rows would have failed
  Pydantic validation at registry load and taken the backend down at startup.
- **C1–C5:** selection now ranks on curated `quality_rank` within a capability
  level, with a tie band handing near-equals to live signals (quota headroom,
  recent failures), and `capability_tags` promoted to a first-class task-type
  preference. `pick_model_by_capability` was first-match-wins in file order
  before this. F-6's Groq-priority hack removed. "Auto" is now the default model
  selection in the UI.
- **Known gap:** `tests/` runs against `app/registry/seed.py` fixtures, which
  have long-standing drift from the shipped `data/registry/*.json`. New
  `test_registry_integrity.py` now covers the shipped files directly.
- **R2 (done, code complete):** quota accounting is now token-accurate,
  persisted across restarts (new `endpoint_usage` table), and **keyed per
  user** — fixing a pre-existing bug where one BYOK user's traffic throttled
  everyone else, since the single app-wide limiter keyed on `endpoint_id` alone.
  `tpm_limit`/`tpd_limit` are enforced for the first time (`record_call`
  previously discarded its `token_count` argument). Short rpm/tpm windows stay
  in-memory by design; day/month persist. Persistence self-disables after
  repeated failures so a missing Postgres degrades instead of stalling requests.
  **Deploying this needs the manual migration
  `postgres/migrations/2026-07_R2_endpoint_usage.sql`.**
- **R3 (done):** `GET /dashboard/free-tiers` (per-user, honest math — headline
  sums only capped endpoints, `None` not `0` when nothing's capped, uncapped
  providers listed separately not folded in) + a responsive `/providers` page
  (`pages/ProvidersPage.tsx`, card grid, PAWN's own `theme-*` tokens) with its
  nav entry sitting **directly above Settings** in the sidebar footer, as
  instructed. Live-verified in Chrome once the user logged in; also fixed a
  mobile sidebar-reopen gap here and on `ProjectsGalleryPage.tsx`/
  `SettingsPage.tsx` (nav auto-closes the sidebar on navigate, stranding phone
  users with no way back — `ProjectPage.tsx` has the same latent gap, still
  open).
- **Phase 1b (done):** `EndpointEntry.key_source: "byok"|"pool"|"either"`
  (default `"byok"`, zero behavior change for existing rows; all 47 shipped
  endpoints + 15 seed fixtures set to `"either"`). `config.read_pool_key()`
  reads the operator's shared key from `/run/secrets/pool_<provider>_api_key`.
  `Resolver._resolve_key` now tries **pool first, BYOK fallback** for
  `"either"` endpoints (the user's explicit precedence call — conserves each
  user's own limits by spending the shared pool first) — `"pool"` endpoints
  ignore the user's own key entirely (unused by any shipped endpoint yet, a
  lever for later). Dashboard rows now report which source is ACTUALLY in
  play, so a keyless user can still see pool-funded rows. **Docker secrets
  now wired into `docker-compose.yml`** (2026-07-23) — see the follow-up note
  above. `.example` templates + a documented manual enable-path (copy to a
  real filename, add a real key, restart) still apply for actually turning a
  provider's pool on.

Plans and research for all of R1/C1-C5/R2/R3/Phase 1b live in
`workspace/plan/router_failover/`, which is **gitignored on purpose**
(local-only).

---

Last updated: 2026-07-17

**DEPLOYED — FLUX warmup + Create Image mode fixes live on prod
(`pawnai.duckdns.org`), 2026-07-17.** `main` is now at `22695be` (was
`6f2f75f`). Pure backend fix, no schema/migration/frontend changes needed —
directly confirmed on the VM that `IMAGE_MODELS['flux'].startup_*` reads the
new 300/600/1500 values (sdxl unchanged at 90/180/900). See `dev_log.md`'s
2026-07-17 "Deployed" entry.

**fixes: FLUX warmup false-dead-session + chat "Create Image" mode — DONE,
live-verified (2026-07-17).** (1) FLUX warm
sessions were being falsely declared dead mid-warmup ("session ended before
this job ran") because the dead-session-detection thresholds in
`image_session.get_session_status()` were flat globals tuned for SDXL's fast
cold start; FLUX's real cold start (heavier deps, ~34GB dataset mount, ~10min
sharded model load) legitimately outruns them. Fixed with new per-model
`ImageModel.startup_heartbeat_stale_seconds`/`startup_no_heartbeat_timeout_
seconds`/`startup_timeout_seconds` fields (`image_models.py`) — SDXL keeps the
unchanged defaults (90s/180s/900s), FLUX overrides to 300s/600s/1500s. (2)
Chat's "Create Image" mode only made `generate_image` *available*
(`tool_choice="auto"`), not guaranteed — `execute_node` now forces
`tool_choice` onto `generate_image` specifically on that turn's first
iteration (`agent/graph.py`), with a graceful short-circuit if Kaggle isn't
connected. Separately, "Fast" mode (the default) unconditionally skipped the
agent loop entirely regardless of wording, so an explicit image request typed
on Fast mode never had a chance to generate — fixed by reusing
`router_classify`'s own `_IMAGE_GEN_KEYWORDS`+`has_kaggle_creds` heuristic for
Fast mode specifically. 594 backend tests green (up from 587, 7 new). Both
fixes live-verified: a real Kaggle FLUX session survived past the old
180s/900s windows and generated successfully (SDXL unaffected control also
verified); chat generated images correctly under all three modes (Fast with
explicit wording, Pro, Create Image with vague wording), and Fast mode with an
ordinary question stayed a plain text reply (no false-positive image
attempts). See `dev_log.md`'s 2026-07-17 "fixes:" entry.

**DEPLOYED — 48-commit release now LIVE on prod (`pawnai.duckdns.org`),
2026-07-17.** `main` is now at `6f2f75f` (was `f7263f5`), matching `dev` at the
time of promotion. Ships: the full chat feature batch (F-1–F-11), imageLab Q1
(generation correctness fixes) + Q3.1–Q3.3 (prompting/presets) + G1
(Generations tab management), and today's 2 polish fixes (chat attachment
card, imageLab "Latest" preview). Both pending DB migrations applied to prod
(`2026-07_Q31_enhance_prompts.sql`, `2026-07_G1_image_jobs_queue_pos.sql`) —
`image_jobs` schema on prod now matches local dev. Health/HTTPS/security
headers/console all verified clean. **Still needs the user's own hands**: full
OAuth login round-trip, Drive link, a saved BYOK key + live chat, one real
Kaggle image-gen job — plus clicking Redeploy on any already-warm Kaggle
session to pick up the updated notebook templates. See `dev_log.md`'s
2026-07-17 "Deployed" entry and
`workspace/implemented_phases/plan_deployment_2026-07-17_release.md` for the
full plan this executed.

**Q2 (imageLab realism checkpoint models) and Q3.4 (optional negative-
embeddings spike) remain open** — deliberately deferred, not part of this
release.

**Chat: attached file/image shown as a card on the sent message — DONE, live-verified
(2026-07-17).** New `Message.attachment` field (`types.ts`, live-session only, not
persisted server-side). `ChatPage.tsx`'s `handleSend` captures then clears
`attachedImage`/`attachedDoc` right away (both attachment kinds are one-shot in the
composer now — a user correction mid-session: the first pass left the doc chip
lingering after send since the old design resent `doc_id` on every turn; doc
retrieval for follow-ups is unaffected since it goes through the existing
`doc_search` RAG tool, not `doc_id`, which has been server-side-unused since Phase
A/A.4). `Message.tsx` renders the card above the sent bubble — thumbnail for images,
filename+extension for docs. See `dev_log.md`'s 2026-07-17 entry.

**imageLab: "Latest" preview reflects real history — DONE, live-verified
(2026-07-17).** `ImageGenerator.tsx`'s "Latest:" preview no longer only reflects this
component's own submit-and-watch state — `ImageLabPage.tsx` now passes each model's
jobs slice down as a `jobs` prop, and two new effects derive "Latest" from the most
recently completed job on load/model-switch, and clear the shown result the instant
its job is deleted from the Generations list. See `dev_log.md`'s 2026-07-17 entry.

**imageLab G1 — Generations tab: delete/edit/reorder queue — DONE, live-verified
(2026-07-17).** Delete (queued/done/error rows, never running), reorder the queue
(up/down arrows, single status-priority-sorted table), edit a queued job
(delete-and-reload into the composer with full params — no `PATCH` route), a settings
popover (non-default params), and an input-image tag. Backend: new `queue_pos` column
+ `DELETE /generate/job/{id}` / `POST /generate/jobs/reorder` routes + both warm-session
notebooks' dequeue order updated + `original_prompt` broadened to cover suffix-only
jobs. Frontend: `GenerationsPanel.tsx`'s 3-icon action row, reorder arrows, settings
popover, input-image tag; `AdvancedParams.tsx` gained an `initial?: ImageParams` prop +
`advancedFromParams` inverse mapping so Refine/Edit can pre-seed the panel;
`ImageGenerator.tsx` gained `triggerEdit`. **Found this session's implementation was
already code-complete but uncommitted** (picked up mid-flight); ran code-reviewer +
build-validator, found and fixed 2 real bugs: (1) **CRITICAL** — the new `initial` prop
only seeded local state on mount, never called `onChange`, so Refine/Edit's pre-filled
Advanced panel was cosmetic-only — none of the carried-over settings actually reached
the Generate request until the user touched a field by hand; fixed with a mount-only
effect. (2) **WARN** — the row lightbox still showed the suffixed prompt instead of the
raw user text. **Live-verified via Chrome**: queued a job with explicit
`style_preset=cinematic`/`guidance_scale=5`/`896x1152`, edited it, confirmed the panel
pre-filled correctly, generated again, and confirmed via a direct Postgres query that
the new job's `params` carried the exact same values — proving the fix actually closes
the gap end-to-end, not just that the panel renders right. Also live-verified delete
(done/error vs queued confirm copy) and reorder arrows appearing on queued rows. Known
gap, not closed this session: no `@testing-library/react` anywhere in the project, so
the plan's component-level test requirements (icon visibility, delete-confirm flow,
etc.) remain pure-function-only like every other frontend test file — pre-existing,
project-wide gap. 580 backend tests green, `tsc` clean, 37 frontend tests green. See
`workspace/plan/imageLab/phase_G1_generations_management.md` and `dev_log.md`'s
2026-07-17 "imageLab G1" entry.

**imageLab Q3.1 pass 2 — Vision-grounded prompt enhancer wired into generation
routes + composer toggle — DONE (2026-07-17). Closes Q3.1.** Both image-
generation entry points now call pass 1's `enhance_with_vision()`: new
`_apply_prompt_enhancement()` helper in `routes/generate.py`, called from the
cold `/generate` path and the warm `/generate/session/job` path, ahead of
style/subject-preset suffix composition and Q3.2's default-negative merge.
New `enhance_prompt: EnhanceMode = "auto"` field (`Literal["auto", "always",
"off"]`) on both request models — "auto" defers to pass 1's rule-based gate,
"always" forces the call, "off" skips it (and, on the warm path, skips the
extra `get_session_model` lookup too when no preset needs it either).
`original_prompt`/`enhanced_prompt` persist on the job only when the enhancer
actually ran and didn't degrade — new `image_jobs` columns
(`postgres/schema.sql` + `postgres/migrations/2026-07_Q31_enhance_prompts.sql`,
applied to local dev), threaded through `create_cold_job`/`submit_session_job`/
`get_job`/`list_jobs`. Frontend: `ImageGenerator.tsx` gets a 3-button
Auto/Always/Off toggle next to "+ Advanced" (Auto default); `GenerationsPanel.tsx`
and the "Latest:" preview show the original (as-typed) prompt with a `✨`
affordance tooltipping the full enhanced rewrite. **Two real bugs found and
fixed this session:** (1) the enhancer's negative-list marker parsing was
exact-case `"Negative:"`-only — a live model used `"Avoid:"` instead, so the
negative text stayed stuck in the positive prompt; fixed with a
case-insensitive, earliest-match scan over `("negative prompt:", "negative:",
"avoid:")`. (2) **CRITICAL:** the warm path's `params_dict.setdefault
("strength", 0.6)` was a no-op — Pydantic v2's `model_dump()` always includes
`strength` as a key (`None` when unset), so `setdefault` never fired; since
the composer's Refine flow only ever calls `submitSessionJob`, every img2img
job through the main UI was silently getting `strength=None`. Fixed to match
the cold path's `if params_dict.get("strength") is None:` pattern. 566 backend
tests green (up from 550), `tsc`/build clean. code-reviewer: 1st pass FAIL (the
`strength` CRITICAL) → fixed → PASS. test-runner PASS. build-validator: 1st
pass FAIL (docs) → PASS. No security-auditor run (reuses pass 1's audited
vision-call path, no new secret surface). See
`workspace/plan/imageLab/phase_Q3_prompting_presets.md` §Q3.1 and
`dev_log.md`'s 2026-07-17 "imageLab Q3.1 pass 2" entry.

**imageLab Q3.1 pass 1 — Vision-grounded prompt enhancer, backend plumbing —
DONE (2026-07-16).** New `backend/app/core/vision_enhance.py`:
`enhance_with_vision(prompt, image_b64, target_model_schema, resolver,
rate_limiter, user_id=None)` rewrites a raw imageLab prompt via a
vision-capable LLM, chain Groq (`llama-4-scout`, preferred by the resolver's
existing F-6 Groq-priority sort) → Gemini → raw prompt unchanged on both
failing (`degraded=True`) — never raises. Rule-based gate
(`needs_enhancement`/`_looks_already_scaffolded`, `ENHANCE_SKIP_WORD_THRESHOLD
= 25`) decides whether a prompt is vague enough to warrant the LLM call before
any call happens. New `PromptSchema` dataclass on `image_models.ImageModel`
(sdxl: `keyword_scaffold` + `wants_negative=True`; flux: `natural_language` +
`wants_negative=False`), each with a generated (not hand-duplicated)
`system_prompt`. New `ROLE_LEVELS["vision_enhancer_primary"]` reusing F-11's
`require_vision=True` resolver filter. **Critical bug found and fixed in code
review:** the obvious `normalize.chat_complete()` call would have silently
broken the vision-only guarantee — that function's own cross-model
`fallback_models()` failover isn't vision-filtered and could hand image
content to a same-capability-level text-only model, while still reporting
`degraded=False`/`used_model=<the original vision pick>`. Fixed by adding a
narrower `normalize.chat_complete_single_model()` (endpoint-level failover
only, no cross-model step) and switching `vision_enhance.py` to call that
instead; `resolver.pick_model_by_capability()` also gained an
`exclude_model_ids` param so the Groq→Gemini chain can step past a failed
pick without a new provider-pinning mechanism. Also resolved the 3 open
questions blocking this plan (Groq vision model id, default-on scope,
provider-pinning mechanism) — see `plan_vision_prompt_enhancement.md` §5,
all closed by code already shipped for F-11. 550 backend tests green (up
from 549 — `app/registry/seed.py`, the fixture registry tests actually run
against, is still stale relative to the real `data/registry/*.json` files
F-11/this step depend on in production — not fixed here, noted as a gap).
code-reviewer: 1 CRITICAL found → fixed, re-reviewed PASS. security-auditor:
light-touch pass (no new secret surface, base64 image bytes only ever
embedded in an LLM request, never written to disk) — PASS. build-validator
PASS. See `workspace/plan/plan_vision_prompt_enhancement.md` and
`workspace/plan/imageLab/phase_Q3_prompting_presets.md` §Q3.1, and
`dev_log.md`'s 2026-07-16 "imageLab Q3.1 pass 1" entry.

**imageLab Q3.3b — Subject-type axis + per-model preset suffix variants — DONE
(2026-07-16). Closes Q3.3.** New orthogonal subject-type preset axis (portrait/
nature/product/architecture), composable with any style preset; 4 new style
presets (analog_film/studio_product/golden_hour/editorial — 9 total). Both style
and subject-type presets now carry per-model `sdxl_suffix`/`flux_suffix` variants
(SDXL keyword-scaffold vs FLUX natural-language, per Q3.1's research) instead of
one suffix shared across models. New `image_session.get_session_model()` lets the
`/session/job` route resolve per-model suffixes too (it doesn't carry the model
directly on the request, unlike `/generate`), gated so the extra DB lookup only
fires when a style/subject preset is actually set. **A "multi-person/group"
subject type (extended negative-prompt list + UI caveat) was built, then the
user explicitly rejected it mid-step — "why are we wasting time building
multi-person feature for sdxl if the model is not suitable for it... no need to
waste time on what does not work" — and it was fully removed**, including the
now-unused extended-negative/caveat mechanism (not left as dead code). Shipped
scope: 4 subject types, no multi-person. Real bug found independently: a
`_session_row()` default-parameter pitfall (bound at module-import time, so
`get_session_model()` needed an explicit `_fetchone=fetchone` pass or test
patching would silently miss it). 534 backend tests green (up from 519), 31
frontend tests (up from 13); `tsc`/build clean. code-reviewer PASS (0 CRITICAL/
WARN on the final post-removal diff). build-validator PASS. No security-auditor
run (pure data/param-plumbing, no secrets/config/auth touched). Live-verified via
Chrome: Subject dropdown shows exactly the 4 shipped types, Style dropdown shows
all 9. See `workspace/plan/imageLab/phase_Q3_prompting_presets.md` §Q3.3 and
`dev_log.md`'s 2026-07-16 "imageLab Q3.3b" entry.

**imageLab Q3.3a — Style preset registry (replaces hardcoded STYLE_SUFFIXES) — DONE
(2026-07-16).** Second Q3 step — deliberately scoped down from the plan's full Q3.3
(registry + a new subject-type axis + composer chips UI); this sub-step is JUST the
registry-load-and-replace foundation, behavior-preserving. New
`backend/data/registry/image_presets.json` (the same 5 presets — photorealistic/
cinematic/anime/oil_painting/sketch — same exact suffix strings, moved out of a
hardcoded dict in `routes/generate.py`). New `backend/app/core/image_presets.py`
loader (`get_preset_suffix()`, falls back to `""` on unknown/None/empty, matching
the old dict's `.get(key, "")`). **One real implementation wrinkle:** the registry
test-isolation harness (`tests/conftest.py`'s per-worker `PAWN_DATA_DIR`) only seeds
`models.json`/`endpoints.json` at runtime — there's no equivalent seeding for a
static file, so defining `IMAGE_PRESETS_FILE` the same `DATA_DIR`-relative way as
those two broke every single backend test with `FileNotFoundError`. Fixed by
resolving it relative to the source tree instead (`Path(__file__).resolve().parent
.parent / "data" / "registry" / "image_presets.json"`, matching the existing
`KAGGLE_TEMPLATES_DIR` pattern) — sound because `image_presets.json` is genuinely
static bundled data, never runtime-mutated, unlike the LLM model registry.
Documented inline in `constants.py` so a future maintainer understands why this one
file is special-cased against the sibling convention. Deferred to a future Q3.3b:
the new subject-type preset axis (portrait/multi-person/nature/product/architecture),
4 additional style presets, per-model (SDXL/FLUX) suffix variants, composer chips UI.
519 backend tests green (up from 513); the pre-existing `test_generate.py` style-
preset HTTP-route test (predates this diff) still passes unchanged — the real
regression proof. `tsc --noEmit` clean (frontend untouched this step). code-reviewer
PASS (0 CRITICAL/WARN, 2 informational NOTEs — the path-resolution deviation judged
sound and well-documented; no error handling around the import-time JSON load judged
acceptable for static bundled data). No security-auditor run (pure data-file load,
no secrets/config/auth touched). See `workspace/plan/imageLab/phase_Q3_prompting_presets.md`
§Q3.3 and `dev_log.md`'s 2026-07-16 "imageLab Q3.3a" entry.

**imageLab Q3.2 — Default negatives (SDXL-family) — DONE (2026-07-16).** First step
of the Q3 prompting/presets phase (Q2 deliberately skipped for now, per the user —
optimize the pipeline before adding new models). SDXL now gets a research-backed
default negative prompt (`cartoon, illustration, anime, painting, CGI, 3d render,
unrealistic proportions, extra fingers, low quality, deformed, extra limbs, bad
anatomy, blurry, watermark, text`) server-side-merged ahead of whatever the user
types, on EVERY SDXL generation — not just ones where the user knew to type
negatives in manually. New `ImageModel.default_negative` field (None for FLUX,
unaffected); new `merge_negative_prompt(model_id, user_negative, style_preset)` in
`image_models.py`, wired into both `submit_session_job`/`create_cold_job` via a new
`_apply_default_negative()` helper at the same choke point Q1.1's resolution
snapping uses. **Real bug found by code-reviewer's first pass, fixed same
session:** the default negative's "cartoon, illustration, anime, painting" terms
directly contradicted the existing "Anime" and "Oil Painting" style presets, which
add those exact words as *positive* suffixes — a user selecting either preset would
have gotten a prompt fighting itself. Fixed with a `NON_PHOTOREAL_STYLE_PRESETS`
frozenset (`anime`, `oil_painting`, `sketch`) that skips the default entirely under
those presets. Deliberately deferred: Q3.3's "multi-person preset gets an extended
negative list" (Q3.3 doesn't exist in code yet) and an opt-out UI toggle (the
default is currently always-on, un-opt-out-able — flagged as a real, if minor, gap
worth revisiting). Frontend hint added under the Negative Prompt field. 513 backend
tests green (up from 499), `tsc`/build clean. code-reviewer PASS (1 WARN fixed — the
style-preset conflict above). No security-auditor run (pure data/param-merge logic,
no secrets/config/auth touched). See `workspace/plan/imageLab/phase_Q3_prompting_presets.md`
§Q3.2 and `dev_log.md`'s 2026-07-16 "imageLab Q3.2" entry.

**imageLab Q1.5 — A/B benchmark + live verification — DONE, partial live run
(2026-07-16).** Closes out the Q1 correctness pass (Q1.1-Q1.5 all complete).
`workspace/plan/imageLab/benchmarks.md` defines 6 fixed prompt+seed pairs.
Local dev's `cloudflared` tunnel (needed so a Kaggle warm-session kernel can
reach the local PostgREST container) wasn't running this session — started it,
fixed a stale orphaned-container network error, updated
`docker-compose.override.yml`, restarted backend. Ran prompt #1 (photorealistic
portrait) live against a real Kaggle SDXL warm session, twice with the same
seed: both clean (no black/corrupt frame, full subject in frame, sharp
natural photoreal detail) and **pixel-identical** to each other — real,
live confirmation of Q1.1 (resolution buckets)/Q1.2 (VAE fix)/Q1.3
(scheduler+CFG)/Q1.4 (seed determinism) all working together end-to-end, not
just at the unit-test level. Did not run the full 6-prompt × 2 matrix (24
generations) — prompt #1 alone was judged sufficient confirmation given real
GPU-time cost; remaining prompts (#2-6, FLUX, style/negative-prompt variants)
can run before Q2 ships if a more exhaustive pass is wanted. Full result log
in `benchmarks.md`. See `dev_log.md`'s 2026-07-16 "imageLab Q1.5" entry.

**imageLab Advanced Params refactor: per-model config classes — DONE
(2026-07-16, user-requested, not a numbered Q-step).** New
`frontend/src/components/advancedParamsConfig.ts`: abstract
`ModelAdvancedConfig` base class + `SdxlAdvancedConfig`/`FluxAdvancedConfig`
subclasses replace scattered `isFlux` conditionals in `AdvancedParams.tsx`
with per-model `showSteps`/`showGuidance`/`showNegativePrompt` flags,
defaults, ranges, and hints. FLUX's Inference Steps control is now hidden
entirely (`showSteps = false` — fixed ~4-step distillation, no meaningful
adjustable range), alongside the pre-existing Negative Prompt hiding — both
now expressed the same structural way. `deriveParams` gates every field on
its config flag as defense-in-depth. `AdvancedState`/`ParamState` relocated
to `types.ts` per frontend.md convention. 28 frontend tests green (up from
13), `tsc`/build clean, backend unaffected (499 unchanged). code-reviewer
PASS. Live-verified via Chrome: FLUX's Advanced panel now shows Aspect Ratio
→ Style → Guidance Scale → Seed with Inference Steps/Negative Prompt both
absent from the DOM. See `dev_log.md`'s 2026-07-16 "Advanced Params
refactored" entry.

**imageLab Q1.4 — Seed control + FLUX negative-prompt honesty — DONE
(2026-07-16).** Fourth and final correctness fix in the Q1 pass. Added
end-to-end seed plumbing on the warm-session path: `ImageJobParams.seed: int |
None` (backend), a seed field in `AdvancedParams.tsx` with a 🎲 randomize
button (max `2_147_483_647`, well under `int4`/JS-safe-integer limits), and
both `image_sdxl_session`/`image_flux_session` notebook templates now build a
`torch.Generator(device="cuda").manual_seed(seed)` in the serve loop and pass
it into BOTH the text2img and img2img inference branches. Generations rows
(`GenerationsPanel.tsx`) now show the seed used and a "🎲 reuse seed" action
that round-trips through a new `triggerReuseSeed` imperative handle on
`ImageGenerator.tsx` (mirrors the existing `triggerRefine` pattern) — clicking
it opens Advanced and pre-populates the seed field via a `{value, nonce}`
prop so reusing the identical seed twice in a row still re-applies. FLUX
negative-prompt honesty: the field is now hidden entirely for FLUX (its
pipeline call doesn't accept `negative_prompt` at all — guidance-free, CFG
locked to 0), not just silently dropped; `deriveParams` also guards against
ever emitting it for FLUX as defense-in-depth. **Real gap found and
deliberately scoped out:** the cold one-shot generation path
(`core/generate.py`'s `generate_image()`, called from
`image_session.run_cold_job()`) never forwards `job.params` to Kaggle at
all — only `{"prompt": prompt}` is sent. This is a pre-existing, systemic gap
predating this whole Q1 plan (it silently defeats Q1.1's resolution
snapping, Q1.3's tuned CFG/scheduler, and this step's negative-prompt/seed
work for any generation that lands on the cold path rather than a warm
session) — NOT fixed here, since it's not seed-specific and is a much larger
surface than one Q1.4 step warrants. Seed generator code was added ONLY to
the two warm-session templates, correctly not to the two cold templates
(confirmed: no `seed` string anywhere in either cold `.ipynb`). Flagged as a
follow-up item — see `workspace/plan/imageLab/open_items.md` (needs a new
entry) or a fresh plan step; not tracked as a numbered Q-step yet. New
template-grep test (`test_session_template_serve_loop_honors_seed`, both
SDXL and FLUX) + 2 new backend param-passthrough tests (warm + cold storage
round-trip, cold test's docstring explicitly documents the gap above) + 5
new frontend tests. 499 backend tests green (up from 496), 13 frontend tests
(up from 8); `tsc`/`npm run build` clean. code-reviewer PASS (0
CRITICAL/WARN; verified the scoping decision against the real code, verified
seed correctly reaches both inference branches on both models, verified the
`forcedSeed` nonce pattern has no stale-closure/infinite-loop risk). No
security-auditor run (notebook + param-plumbing edit, no secrets/config/auth
touched). Not yet live-verified against real Kaggle — this closes out all of
Q1's correctness fixes (Q1.1-Q1.4); Q1.5's combined fixed-seed A/B benchmark
is next. See `workspace/plan/imageLab/phase_Q1_generation_fixes.md` §Q1.4
and `dev_log.md`'s 2026-07-16 "imageLab Q1.4" entry.

**imageLab Q1.3 — Scheduler + tuned defaults — DONE (2026-07-16).** Third
correctness fix in the Q1 pass: neither SDXL notebook configured a scheduler
(library default), and CFG defaulted to 7.5 — too high for photoreal output.
Both SDXL templates (cold `image_sdxl/notebook.ipynb` + warm-session
`image_sdxl_session/notebook.ipynb`) now configure DPM++ 2M SDE Karras
(`DPMSolverMultistepScheduler.from_config(pipe.scheduler.config,
use_karras_sigmas=True, algorithm_type="sde-dpmsolver++", euler_at_final=True)`)
right after the Q1.2 VAE assignment and before the pipeline moves to cuda — the
documented <50-step stability recipe. CFG default changed 7.5→5 (the photoreal
sweet spot) in both notebooks' inference calls, including BOTH the text2img and
img2img branches of the session template's serve loop. SDXL steps default (30)
was already correct pre-existing — no change needed there. FLUX untouched
throughout: its notebooks already hardcode `guidance_scale=0.0` regardless of
any param sent (guidance-free distillation), so nothing to fix. `ImageModel`
gained an informational `scheduler: str = "default"` field (`"sdxl" →
"dpmpp_2m_sde_karras"`) — explicitly documented as not consumed anywhere
(templates are static `.ipynb` files, not generated from this registry).
Frontend: new `DEFAULT_GUIDANCE` map (mirrors `DEFAULT_STEPS`) makes the
guidance-scale slider default model-aware; added a "3–5 = more photoreal" hint
for non-FLUX models and a "20–40 recommended" note on the steps range. New
template-grep tests in both `test_kaggle_cold_templates.py` and
`test_kaggle_session_templates.py` (scheduler presence + ordering + tuned CFG
value, scoped to SDXL-only, explicit absence asserted on FLUX) + 3 new frontend
tests. 496 backend tests green (up from 494), 8 frontend tests (up from 5);
`tsc`/`npm run build` clean. code-reviewer PASS (0 CRITICAL/WARN, 2 informational
NOTEs on the untyped `scheduler` field — accepted, no action needed). No
security-auditor run (notebook template + data-field edit, no secrets/config/
auth touched). Not yet live-verified against real Kaggle — this closes out Q1's
correctness fixes; Q1.4 (seed control) is next, then Q1.5's combined fixed-seed
A/B benchmark. See `workspace/plan/imageLab/phase_Q1_generation_fixes.md` §Q1.3
and `dev_log.md`'s 2026-07-16 "imageLab Q1.3" entry.

**imageLab Q1.2 — fp16 VAE fix (black-image killer) — DONE (2026-07-16).** Second
root cause of the user's image-quality report: both SDXL Kaggle notebook templates
loaded the stock fp16 SDXL VAE, which overflows fp16 precision (>65504 activations
→ inf/NaN) and produces random black/broken decodes. Fixed in both the cold
one-shot template (`image_sdxl/notebook.ipynb`, cell `ac47af57`) and the
warm-session template (`image_sdxl_session/notebook.ipynb`, cell-2): load
`madebyollin/sdxl-vae-fp16-fix` via `AutoencoderKL.from_pretrained(...,
torch_dtype=torch.float16)` and assign `pipe.vae = vae` BEFORE the pipeline moves
to cuda, so the fixed VAE travels to GPU with the rest of the pipeline. Loud
`[pawn]` log line on load, matching the notebooks' existing diagnostic convention
(interim runtime download per the plan's acceptable option — not yet added to the
bundled Kaggle dataset). FLUX templates deliberately untouched (different VAE
architecture, unaffected). New `backend/tests/test_kaggle_cold_templates.py`
(mirrors the existing session-template test pattern) + a new test in
`test_kaggle_session_templates.py`, both asserting the fix is present + correctly
ordered before `.to("cuda")` on SDXL templates only, and absent from FLUX's. 494
backend tests green (up from 488). code-reviewer PASS (0 findings — verified VAE
assignment ordering, cell-0 invariant untouched, JSON validity, FLUX isolation).
No security-auditor run (notebook template edit, no secrets/config/auth touched).
Not yet live-verified against real Kaggle — folded into Q1.5's combined
fixed-seed benchmark once Q1.3/Q1.4 land. See
`workspace/plan/imageLab/phase_Q1_generation_fixes.md` §Q1.2 and `dev_log.md`'s
2026-07-16 "imageLab Q1.2" entry.

**imageLab Q1.1 — SDXL-native resolution buckets (headline quality fix) — DONE
(2026-07-16).** Root cause of the user's "half-generated/deformed bodies" report:
`AdvancedParams.tsx`'s aspect-ratio dropdown sent SD1.5-era sizes (512×512,
576×1024, 768×576) — off-bucket for SDXL, which is trained on ~1024²-area
buckets. Replaced with the six SDXL-native buckets (1:1→1024×1024,
3:4→896×1152, 4:5→832×1216, 4:3→1152×896, 16:9→1344×768, 9:16→768×1344),
model-aware (`bucketsFor(modelId)`, SDXL/FLUX share the table today — all
values are /16-aligned so FLUX's flexible architecture is satisfied too — but
each model row owns its own reference, not one hardcoded global). Frontend
default aspect ratio changed from square 1:1 (512) to portrait 3:4 (896×1152).
Added a server-side snap-to-nearest-bucket guard (`image_models.snap_resolution`,
nearest by aspect-ratio distance, zero/negative-dimension-safe) applied in both
`image_session.create_cold_job` and `submit_session_job` before the DB insert —
protects old cached frontends and direct API callers from ever sending an
off-bucket size again. `resolution_buckets` added to `ImageModel` as data (not
code). 20 new/changed backend tests (488 total, up from 476) + 5 new frontend
vitest tests; `tsc`/`npm run build` clean. code-reviewer PASS (1 WARN fixed:
`snap_resolution` guarded against a `ZeroDivisionError` on
zero/negative-height input). No security-auditor run (pure data/param-clamping
logic, no secrets/config/auth touched). Not yet live-verified against a real
Kaggle SDXL session — that's Q1.5's fixed-seed A/B benchmark, still open. See
`workspace/plan/imageLab/phase_Q1_generation_fixes.md` §Q1.1 and `dev_log.md`'s
2026-07-16 "imageLab Q1.1" entry.

**Composer rework (2026-07-16) — DONE.** Three changes to `MessageInput.tsx`: (1) the `+` button's separate "Attach PDF"/"Attach image" flows merged into one "Attach files" file picker (`.pdf,.txt,.png,.jpg,.jpeg,.webp,.gif`), classified client-side and routed to the existing `onUpload`/`onUploadImage` callbacks, invalid formats rejected with an alert. (2) The model-switcher dropdown removed from the composer entirely — model choice now comes solely from the Settings page's `defaultModel` (no per-chat override); `ChatPage.tsx`/`ProjectPage.tsx` dropped their now-dead `selectedProvider` state. (3) New `ModePicker.tsx` (Fast / Pro / Create Image) took the old model-switcher's slot as a real backend routing hint, not cosmetic: `ChatRequest.mode_hint` short-circuits `graph.py`'s `classify_node` — `fast`→direct-answer, `pro`→full agent planning, `image`→agent loop with `difficulty="light"` so `plan_node` skips straight to a single tool-calling turn (`generate_image` bound whenever Kaggle creds exist). Mode id is `'pro'` (not `'research'`) end to end. Backend rebuilt (`docker compose up -d --build backend` — code isn't volume-mounted, only `backend/data` is) before trusting the test run. Full backend suite green (476/476), `tsc`/build clean. See `dev_log.md`'s 2026-07-16 "Composer rework" entry.

**Project UX round (2026-07-16) — DONE, live-verified via Chrome.** Three user-requested changes: (1) "New project" now opens a required-name/optional-description dialog (`NewProjectDialog.tsx`) — a project is never created nameless. (2) Creating a chat from a project's own composer is now race-free: new `createProjectChat` awaits create→move server calls in order and sets `activeConvId` before navigating, replacing the old draft+fire-and-forget-moveChat path that could leave the chat standalone (and, via a stale-activeConvId bug, spawn a second orphaned draft so the message never reached the project chat). Live-verified: message lands in a chat scoped `('project', pid)`, indexed under `scope_type='project'`. (3) The Chats sidebar now lists ALL chats — standalone as the bare title, project-attached as "Project / Title" (routing to `/project/:pid/chat/:id`, with a "Remove from project" kebab action). `tsc`/build clean. See `dev_log.md`'s 2026-07-16 "Project UX" entry.

**Live bug hunt (chat + projects RAG/memory, uploads) — DONE, live-verified via Chrome (2026-07-16).** Root cause of the user's "everything is erroring" report was a Drive N+1 read pattern in `list_conversations`/`list_projects`/`list_project_chats` (2 sequential Drive round-trips per chat/project folder, no concurrency) — with 30 real chats this took 48.8s, over the backend's 45s request-timeout middleware, causing widespread 504s (deletes silently failing while the UI optimistically hid them, uploads timing out, threadpool exhaustion). Fixed with a parallel `DriveStorage.read_files_in_folders()` fan-out (8 workers) — same case now 10.4s. Also fixed a real "new chat in project routes outside it" bug: a `moveChat` sync-queue op can race the chat's own lazy server-side creation and 404 on its first try; added `PermanentSyncError` handling in the sync queue that only gives up after 3 retries (not the first 404), since giving up immediately reproduced the exact bug live. PDF upload, image vision Q&A, chat-scoped isolation, and project-scoped sharing all verified working end-to-end after these fixes. Cleaned up ~30 real leftover chats the user believed were already deleted (they weren't — the deletes had been silently 504ing) plus all test data from this session. 476 backend tests green, `tsc`/build clean. See `dev_log.md`'s 2026-07-16 "Live bug hunt" entry.

**Real Kaggle image gen verified end-to-end + chat image UX fixes — DONE, live-verified (2026-07-16).** Local dev `cloudflared` tunnel restarted and `POSTGREST_PUBLIC_URL` updated — a chat-triggered `generate_image` now completes for real (confirmed in Image Lab's own Generations list). Root-caused and fixed *why* the image never showed up live in chat: `observation` was never sent over SSE at all, only attached to a message after the whole turn finished — added a new `tool_result` SSE event (`events.py`/`graph.py`/`routes/chat.py`/`client.ts`) dispatched the instant a tool call resolves, wired into `ChatPage.tsx`'s trace/segment state live (this also makes the earlier cache-precedence backfill mostly redundant for new turns, kept as a safety net). Also moved the image chip out of the collapsible tool-call card into the main bubble below the reply text (`TraceView.tsx`'s new `findImageJobIds`, rendered from `Message.tsx`), and added a Download link (`ImageJobChip.tsx`, matching Image Lab's own pattern). 1 new test, full suite green (476); `tsc`/build clean. Live-verified: a robot-playing-chess prompt showed reply text → real generated image → working Download button, all live in one stream, no reload, not nested in any collapsed section. See `dev_log.md`'s 2026-07-16 tunnel-restart entry.

**Chat F-11 — attach-image (vision Q&A) + forced-SDXL/session generate_image — DONE, live-verified (2026-07-16).** Composer's attach button is now a `+`/kebab menu: "Attach PDF" (unchanged) and new "Attach image" (sends the image + text to a vision-capable model for a one-turn Q&A, not RAG-indexed, image bytes never persisted). New `direct_answer_node` branch handles this — `classify_node` short-circuits image-attached turns straight to it, skipping the text-heuristic router entirely. `llm_core`/`normalize` needed zero changes (both already pass `messages` through opaquely, closing a prerequisite gap `plan_vision_prompt_enhancement.md` had flagged). `generate_image` (F-1) is now hardcoded to `sdxl` and always starts/reuses a 30-minute warm session — the cold-one-shot path is gone from this tool entirely. Also fixed: `deepseek-r1`'s mislabeled `supports_tools` (was leaking malformed tool-call text), and a real router gap (no image-generation keyword trigger meant `generate_image` could never be invoked via the fast path at all). 12 new tests, full suite green (472); `tsc`/build clean. Live-verified: a chat-triggered SDXL job showed up in Image Lab's own Generations list, confirming cross-platform session/job sharing for real, not just by code inspection. Two follow-ups flagged, both out of scope for this pass: the user's cloudflared tunnel behind `POSTGREST_PUBLIC_URL` needs a restart (real Kaggle image render currently fails on a DNS error), and a pre-existing frontend cache-precedence gap where a same-session chat's tool-call preview can show stale args instead of the result on reload. **Second bug found live after this entry was first written:** the closing-synthesis-hallucination fix initially only nudged the heavy-turn closing-synthesis call, missing light-agentic turns (short image-gen prompts) where the tool loop's own next iteration *is* the final answer — still hallucinated a fake `sandbox:/mnt/data/...` markdown image link. Fixed by moving the `_IMAGE_GEN_SYNTHESIS_NUDGE` system-message injection to right after the `generate_image` tool observation is recorded inside `execute_node`'s tool loop, not gated on `difficulty` — covers both paths from one insertion point. Live-reverified: "generate an image of a dog playing fetch" now correctly replies "I'm generating the image now. It will appear automatically in the chat once it's ready." with no fabricated link. Full backend suite green (475). See `plan/chat/phase_F11_chat_io_formats.md` §7.

**Chat F-10 — Projects gallery page + project descriptions — DONE, live-verified by the user (2026-07-16).** New `/projects` gallery page (`ProjectsGalleryPage.tsx`: sort by last-updated/name, search, responsive card grid showing name + description + date) reached by clicking the sidebar's "Projects" label (collapse toggle split into its own chevron so that behavior wasn't lost). Projects gained a `description` field end-to-end (Drive storage, routes, frontend types/client/sync-queue), editable via a new "Edit details" modal on `ProjectPage`'s kebab menu (Name + Description; Archive intentionally skipped per the user). Also fixed, found live while testing this: `ModelSwitcher.tsx`'s dropdown always opened upward and could overflow off-screen — now flips direction and caps its height based on the trigger's actual available space. Full backend suite green (467); `tsc`/build clean. See `plan/chat/phase_F10_projects_gallery_page.md` §6.

**F-2 (search-tab ModelSwitcher) — closed as not-a-bug (2026-07-16).** User's concrete concern (some models missing from the switcher despite a Groq key) traced live: the missing models all share OpenRouter — unconfigured — as their sole provider; both the frontend picker and the backend's `pick_model_by_capability` are correctly and consistently gated on the same BYOK key check. No code changes.

**Chat F-1 — chat-side generate_image agent tool — DONE (2026-07-16, automated verification only).** New `agent/tools/generate_image.py` lets the chat agent generate images through Image Lab's existing Kaggle job layer (warm session first, cold one-shot fallback), gated on a new `key_store.has_kaggle_creds`; new `components/ImageJobChip.tsx` polls the job and renders it inline in `TraceView.tsx`. Found and fixed a real cross-module race mid-build (code-reviewer WARN): the tool's first draft duplicated `routes/generate.py`'s own cold-job lock/bg-task bookkeeping as a separate module-level copy, so a cold run triggered from chat and one from Image Lab for the same model could still clobber the same single-writer Kaggle kernel slug. Fixed by centralizing it into `core/image_session.py` (`spawn_cold_job_bg`), shared by both entry points now. 12 new/updated tests, full backend suite green (464); `tsc`/build clean. Not yet live-verified against a real Kaggle account. See `plan/chat/phase_F1_image_generation.md` §4.

**Chat auto-title fix — DONE (2026-07-16, user-requested from a live screenshot).** Every chat was silently stuck on the literal "New Chat" — root cause: `routes/chat.py`'s `generate_title` called `pick_model_by_capability("fast")` without `user_id`, so it could pick a model the user holds no key for; the follow-up `chat_stream` call failed on the missing key, the exception was swallowed, and the hardcoded fallback never actually reflected the prompt. Fixed: `user_id` now passed through; new `core/title.py`'s `derive_fallback_title` (no LLM call, whitespace-collapsed + word-boundary-truncated) replaces the bare `"New Chat"` fallback, so a chat always gets a real prompt-derived name even when every model call fails. 8 new tests, full suite green.

**Chat F-6 — Groq priority in the model resolver — DONE (2026-07-16, automated verification only).** `resolver.py`'s `pick_model_by_capability` now prefers Groq-endpoint-having models within a capability level when the user holds a Groq BYOK key (large rate limits, fast generation) — affects orchestrator, execute-loop, final-synthesis, and subagent picks (all route through this one function). The plan's premise that `ModelEntry` itself carries a `provider` field was wrong (only `EndpointEntry` does; a model can span several providers via its endpoints) — implemented via a new `Resolver._has_groq_endpoint(model_id)` check instead, feeding a stable sort ahead of the existing usable-endpoint fallback loop (untouched, so rate-limited/keyless Groq endpoints still correctly fall through). 2 new tests, full backend suite green (445). code-reviewer PASS. Live verification needs the user's own Groq key in Settings — entering API keys is a standing prohibited action for this session. See `plan/chat/phase_F6_groq_default.md` §4.

**Chat F-8 — sync warning banner relocated to the sidebar bottom — DONE, live-verified (2026-07-16).** `Sidebar.tsx`'s offline/unsynced-changes banner moved from directly under the Search input to directly above the User Profile Card, so it no longer pushes the Projects/Chats lists down. Straight cut-paste, `tsc --noEmit`/`npm run build` clean, live-verified via Chrome (temporary force-render, reverted). See `plan/chat/phase_F8_sync_warning_relocation.md` §4.

**Chat F-7 — agent half-generation/empty-reply fix — DONE, live-verified (2026-07-16).** Root cause: on a heavy turn's clean stop, `execute_node` appended the orchestrator's discarded draft as a trailing `assistant`-role message right before the mandatory closing-synthesis call — some providers (Gemini's OAI-compat layer) reject/empty-out a completions request whose tail message is already assistant-authored, producing a silent empty reply after "Composing final answer". Fixed in `backend/app/agent/graph.py`: that draft is now a non-terminal `system` context note instead; the closing-synthesis call is wrapped in the same try/except-and-fall-back-to-loop-draft pattern the tool loop already used; a shared `_EMPTY_REPLY_FALLBACK` apology closes the residual double-failure gap (loop never ran + synthesis also failed) in both `execute_node` and `verify_node.accept()`. 6 new tests, full backend suite green (443). Live-verified via Chrome: a real heavy/research query — including a genuine mid-flight provider failover — synthesized a full detailed answer end to end. See `plan/chat/phase_F7_agent_half_generation_fix.md` §4.

**Chat F-9 — sidebar scroll bug + project/chat row styling + sticky section headers — DONE, live-verified (2026-07-16).** Build order is now chat → imageLab (videoLab deferred to the end, see `plan/README.md`); F-9 is the first chat step. Live-verified via Chrome against the real `docker compose watch` stack: the shared `flex-1 min-h-0 overflow-y-auto` scroll region (`Sidebar.tsx`) correctly reaches chats hidden behind expanded projects while header/actions/profile stay pinned; the nested chat row's quieter active state holds. User requested one more live UI tweak this session: lock the "Projects"/"Chats" section-label rows to the top while their lists scroll underneath — added `sticky top-0 z-10 bg-theme-surface` to both labels (`ProjectSection.tsx`, `Sidebar.tsx`), confirmed live. `tsc --noEmit` + `npm run build` clean. See `plan/chat/phase_F9_sidebar_scroll_and_project_ui.md` §5.

**FLUX CUDA OOM fix (I-1) — DONE, merged + live-verified (2026-07-15).** `worktree-flux-oom-fix` (commit `ac1390b`, `max_memory={0:"13GiB",1:"13GiB"}` cap + `local_files_only=True` on both FLUX notebook templates) merged into `dev`; branch deleted. Also cleaned up the stale `docs/deployment-plan` branch (merged, deleted) and a stale remote-only `origin/imageLab` ref (already fully merged) — only `dev`/`main` remain. Full 438-test backend suite green post-merge. Live-verified same day: a real Kaggle FLUX.1-schnell generation completed successfully over a freshly-reconnected `cloudflared` tunnel, no CUDA OOM. (A first attempt failed, but root cause was an unrelated stale tunnel URL/network issue, not this fix; a separate slow-generation report traced to the UI's Inference Steps slider being manually set to 45 — FLUX.1-schnell is distilled for ~4 steps.) See `plan/imageLab/open_items.md` I-1 and `dev_log.md`'s 2026-07-15 branch-cleanup entry.

**Planning (2026-07-15): videoLab + videoLab 2.0 plans written; plan folder triaged and streamlined; F-3 docs fix applied. No code changes.** New plans: `workspace/plan/videoLab/` (8 files, phases V1–V6 — Kaggle-free-tier video generation merging imageLab's delivery mechanism with BEAM's video knowledge; default model Wan2.2 TI2V-5B via Diffusers) and `workspace/plan/videoLab/v2/` (9 files, phases P1–P7 — compute-unconstrained Higgsfield-level tier: BYOK hosted SOTA APIs via fal/Replicate, RunPod/Modal serverless ComfyUI workers, preset registry, post-production chain, cost ledger with hard budget stops). Plan-folder triage: `plan_open_issues_2026-07-14.md` and `plan_imagelab_session_issues.md` verified ~95% complete against the dev tree and archived into `implemented_phases/` (`..._resolved.md` / `..._history.md`); the genuinely-open remnants now live in `plan/plan_imagelab_open_items.md` (headline: I-1 FLUX CUDA OOM — fix exists on `worktree-flux-oom-fix`, still unmerged pending live Kaggle verification); `plan_findings.md`'s 5 raw ideas code-verified and converted into `plan/plan_feature_additions_2026-07-15.md` (F-1 chat image-gen agent tool recommended; F-2 search-tab ModelSwitcher fix recommended, needs a lock-vs-switch call; F-3 done this session; F-4/F-5 parked with assessments). F-3 (docs-only) executed: `decisions/project_overview.md` + `implemented_phases/phase_10_drive_mandatory.md` now state the settled wording — Drive is the only *durable* backend (source of truth); Postgres/pgvector is a derived, rebuildable search index. **Also (same date): imageLab quality plan** at `workspace/plan/imageLab/` (Q1–Q4) — root-caused the user's "bad/unreal/half-generated images" report to SD1.5-era resolution sizes in `AdvancedParams.tsx`, stock fp16 SDXL VAE (black-image overflow), and no configured scheduler; phases cover correctness fixes, photoreal checkpoint rows (Juggernaut/RealVis), LLM prompt enhancer + negatives/presets, and hires-fix/face-detailer polish, all on the existing Kaggle pipeline; `plan_imagelab_open_items.md` moved to `plan/imageLab/open_items.md`. Full record: `dev_log.md` 2026-07-15 entry.

**Deployment (2026-07-14, round 9): `dev` -> `main` promoted and deployed live to the `pawn` Oracle VM -- Phases A/M/N/O/P + Image Lab fixes now in production.** Per `workspace/plan/deployment.md`. Sequence: pushed 27 previously-local-only `dev` commits to `origin/dev` first (real data-loss risk independent of deployment -- fixed regardless). Fresh pre-flight gate re-run (438 backend tests, clean `tsc`/build, both compose configs valid) before promoting. `scripts/promote-to-main.sh` ran clean (122 files, no doc leaks onto `main`) -- commit `f7263f5`, pushed to `origin/main`. On the VM (`ubuntu@144.24.119.184` via `keys/pawn_oci.key`, confirmed working -- the deploy-access key lives in `keys/`, not `secrets/`): took a full `pg_dump` backup first (86MB), then applied the 3 pending manual migrations in dependency order (`2026-07_memory_scoping.sql` -> `2026-07_doc_search_kind_return.sql` -> `2026-07_image_sessions_stop_requested_at.sql`; the third was already applied from an earlier ad-hoc fix, no-op). **The memory_scoping migration drops/recreates `memory_chunks` -- prod's pre-Phase-M memory history was wiped, not migrated; explicitly approved (no real users yet).** One real snag: `git pull` partially failed on `backend/data/registry/{models,endpoints}.json` (root-owned on disk from the backend container's bind-mount writes, `ubuntu` user couldn't unlink) -- fixed with `sudo chown`, then the VM was left in an inconsistent half-updated state (working tree had new content, `HEAD` hadn't advanced) requiring `git reset --hard origin/main` to cleanly resolve (ran only after explicit user confirmation, since it's a destructive command an auto-mode safety classifier correctly flagged). Rebuilt frontend (`npm ci && npm run build`) and backend (`docker compose ... up -d --build`) -- clean startup, `Application startup complete`, zero errors/exceptions in logs since restart, `/health` returns `{"status":"ok"}` both locally and over public HTTPS, and the live site serves the exact freshly-built JS bundle hash. **FLUX OOM fix deliberately excluded from this promotion** (still Kaggle-unverified, PR #2 stays unmerged on `dev` -- see `plan_imagelab_session_issues.md`) -- documented, not shipped. **Still needs the user:** the deeper feature-level verification checklist in `deployment.md`'s §8/§6 that needs a real login (OAuth round-trip, Drive link, a real Kaggle image-gen job, tool-calling/doc_search/project-scoping smoke tests) -- infra-level checks (health, HTTPS, bundle serving, clean logs) all pass, but nobody has exercised the new Phase A/M features against prod yet.

**Bugfix (2026-07-14, round 8): FLUX CUDA OOM on generate, re-applied from a previously-drafted-then-reverted fix.** `device_map="balanced"` was packing GPU 0 to the brim (12.95/14.56GiB) on FLUX model load, leaving no headroom for inference-time activations — every generate call OOMed even though the model itself loaded successfully. A `max_memory` cap fix was drafted (`84c0a4d`) then reverted (`d96c1c6`) on 2026-07-05 solely because it was never verified on real Kaggle hardware, not because it was disproven. Re-applied unchanged in substance to both FLUX templates' cell-2 `FluxPipeline.from_pretrained(..., device_map="balanced")` call: `max_memory={0: "13GiB", 1: "13GiB"}` forces the dispatcher to leave ~1.5GiB headroom per T4; also added `local_files_only=True` to skip an unnecessary Hub round-trip (SDXL's templates already had this, FLUX's never did). Confirmed cell 2 was untouched by the 2026-07-14 round-7 dead-session-detection work (which only touched cells 0/1/3), so this was still the exact pre-fix state. The warm-session serve loop already wraps each job's `pipe(...)` call in its own try/except, so the OOM was never crashing the kernel — it was silently failing every generate job forever with an `error` status, since GPU 0 stayed packed for the session's whole life. Both notebooks re-validated as well-formed JSON, every cell still `compile()`s clean, 438 backend tests green (no test changes needed — `test_kaggle_session_templates.py` doesn't assert on this cell's source). **Not independently verified on real Kaggle hardware** — still needs a live FLUX warm-session generate to confirm; blocked on the same local-network issue (college proxy) as the rest of this round's local testing. Full detail: `workspace/plan/plan_imagelab_session_issues.md`'s FLUX CUDA OOM section.

**Feature/fix (2026-07-14, round 7): Image Lab dead-session detection, from `plan_imagelab_session_issues.md`'s active implementation plan.** Closes the user-reported "warm session starts, Kaggle notebook stops abruptly, app stuck on 'Warming' forever" bug — two independent legs. **Backend:** new `kaggle.kernel_status(username, api_token, kernel_name)` probes Kaggle's `/kernels/status` directly (previously only used on the cold-job path, never for warm sessions); wired into `image_session.get_session_status()`'s warmup branch via a throttled `_kernel_probe()` helper (`IMAGE_SESSION_KAGGLE_PROBE_INTERVAL_SECONDS=30`, `IMAGE_SESSION_STARTUP_PROBE_AFTER_SECONDS=60`, `IMAGE_SESSION_RUNNING_NO_HEARTBEAT_TIMEOUT_SECONDS=180`) — a dead/terminal kernel now flips to a precise error in ~60-90s instead of the old 900s wall-clock-only fallback (kept as the backstop for when the probe itself has no info — no creds, Kaggle API down, or the kernel is legitimately still `queued`). **Notebooks** (`image_sdxl_session`/`image_flux_session`, cell-0 kept byte-identical): `patch_session`/`patch_job` were fire-and-forget yet could still raise on a network error, silently killing the run before its own error report landed — this is the exact live-observed failure (dead dev tunnel's `gaierror` out of cell-1's first `patch_session` call). Replaced with a shared never-raising `_rest_patch` (one retry, loud `[pawn]` kernel-log lines, detects silently-rejected 0-row writes), wrapped cell-1's pip install in try/except, decoupled the supervisor's heartbeat from read success, added a 600s total-unreachability self-exit (`os._exit(1)`) so an unreachable kernel doesn't burn GPU quota until Kaggle's ~12h cap. **Frontend:** Warming pill now shows substatus + live elapsed time (`Warming · loading model · 1m 21s`) instead of a bare "Warming". New `test_kaggle_session_templates.py` (9 tests) + 13 new/updated `test_image_session.py` tests + 5 new `kernel_status` tests in `test_generate.py`. 438 backend tests green (up from 415, confirmed twice), `tsc`/`npm run build` clean. Live-verified via Chrome with mocked backend responses (deliberately did not start a real Kaggle session/spend GPU quota without asking) — both the elapsed-time pill and the probe-detected-error message render correctly. **Still needs the user:** a live smoke test against a real Kaggle kernel (their creds + a restarted dev tunnel) and checking the Kaggle kernel log for the new `[pawn]` lines. Prod deploy of the notebook-template changes stays gated on a real deployment session. Plan docs consolidated: `plan_imagelab_dead_session_detection.md` merged into `plan_imagelab_session_issues.md` (now the single canonical doc); `plan_open_issues_2026-07-14.md` §1 replaced with a pointer to it.

**Cleanup (2026-07-14, round 6): §3 of `plan_open_issues_2026-07-14.md` — three small hygiene fixes, no behavior change.** (1) Removed the vestigial `EndpointEntry.secret` field entirely — `schemas.py`, `seed.py`'s `INITIAL_ENDPOINTS`, the live `data/registry/endpoints.json`, and `test_rate_limiter.py`'s constructions all cleaned together (never read anywhere; `Resolver` only ever uses the per-user BYOK key via `key_store`). (2) `conversations_drive.py`'s 5 broad `except (json.JSONDecodeError, Exception): pass` sites now log the actual exception to stderr before falling through to the same existing return/pass — simplified the redundant exception tuple to plain `Exception`, zero change to control flow (a transient Drive error was silently indistinguishable from "not found"; now it's at least visible in logs). (3) `routes/memory.py`'s `_delete_scope_chunks` gained the same try/except-and-log pattern as its sibling `_delete_chunks` in `conversations.py` (best-effort — `memory_chunks` is a rebuildable derived index). 415 backend tests green (no new tests needed — pure logging additions, no new observable behavior). Backend rebuilt and confirmed booting clean; live-verified the registry schema change via the model switcher UI (per-model provider lists render correctly).

**Bugfix (2026-07-14, round 5): deterministic Drive root resolution, from `plan_open_issues_2026-07-14.md` §2.2.** `storage/drive.py`'s `get_or_create_root()` queried Drive's `files.list` with no `orderBy` and `pageSize=1` — without an explicit order Drive gives no ordering guarantee, so a user with more than one pre-existing "PAWN" root folder (from before the `drive_factory` concurrency race was fixed, commit `2146b07`) could have different DriveStorage instances resolve to *different* roots across calls, silently seeing different subsets of their own chats/projects. Fixed: now orders by `createdTime` ascending, `pageSize=10`, always picks the oldest folder deterministically (most likely to hold the most history), and logs a stderr warning (user ID + every folder ID found) when duplicates exist — visible now, not silent, without touching any data. New `backend/tests/test_drive_storage.py` (6 tests; `DriveStorage` had zero direct unit coverage before this — `_build_service` mocked to avoid real Google API calls). 415 backend tests green (up from 409). **Still needs the user:** actually merging the two real "PAWN" folders' contents in Drive — moving/reconciling files needs manual judgment about conflicts, not safely automatable (unchanged from the original finding); the fix above should make the visible symptom far less confusing even before that manual merge happens.

**Bugfix (2026-07-14, round 4): O.1 mid-loop double-answer, from `plan_open_issues_2026-07-14.md` §2.1.** A heavy/research turn where the orchestrator's own tool-loop iteration cleanly stopped with a complete answer used to stream that text live, then O.1's mandatory closing-synthesis call independently re-answered the same question — both ended up concatenated in one message as two similar-but-differently-worded answers. Fixed in `agent/graph.py`'s `execute_node`: heavy-turn loop iterations now defer (buffer, never dispatch) their own content via a new `defer_loop_content` flag — flushed as one chunk if a further tool call follows (preserves Phase N's "thinking before a tool call" interleaving), discarded entirely on a clean stop (the closing synthesis becomes the sole visible answer, as O.1 always intended). Light (agentic) turns unaffected. Net-positive side effect: a mid-stream failure during a now-buffered heavy-turn loop iteration safely falls through to a fresh closing-synthesis attempt instead of hard-failing the turn, since nothing was shown to the user yet. 5 existing tests updated, 1 recontextualized to light difficulty, 2 new regression tests added in `test_agent.py`. 409 backend tests green (`pytest -n auto`, confirmed twice — ruled out an unrelated one-off SQLite/xdist lock flake). Live-verified against the real dev stack: a calculator-triggering heavy prompt produced exactly one tool call and exactly one answer, no leaked mid-loop text.

**UI polish (2026-07-14, round 3):** closes the queued "render sources as a link icon instead of the full URL text" request. `Message.tsx`'s `MarkdownContent` now detects bare-URL autolinks (visible text === href, via a new `textOf` helper flattening the anchor's children) and swaps them for an icon-only link (new `LinkIcon` in `components/icons/index.tsx`, `theme-text-muted` styling matching the rest of the icon set) instead of printing the raw URL; a real anchor with actual link text (e.g. `[Example Site](url)`) is untouched. A new `_SOURCE_WRAPPER_RE` strips the `(source: <url>)` parenthetical wrapper the researcher subagent's prompt tells it to emit (`subagents.py`'s `"(source: <url>)"` binding instruction) down to the bare URL first, so only the icon remains with no `"(source:"` noise around it. `tsc --noEmit` + `npm run build` clean. Live-verified against the real running dev stack (`docker compose`, port 5174) with a forced test prompt: `(source: https://example.com)` rendered as icon-only with the wrapper text gone; `(source: [Example Site](url))` kept its normal blue link text and the surrounding "(source: ...)" text, exactly as designed since that's real anchor text, not a bare-URL autolink.

**Bugfix (2026-07-14, round 2):** F-1 (the "unexpected error" crash after heavy failover) and the full pytest gate both diagnosed from real logs the user pasted back — both had a different root cause than the prior session assumed. F-1: `agent/graph.py`'s `direct_answer_node`/`final_node` each had an unguarded `resolver.pick(model_id, user_id=user_id)` "peek" (only for a cosmetic provider-name UI event) that could raise `NoEndpointError` and kill the whole turn even when the real call right below it (`chat_stream`, which fails over across every fallback model) would likely have succeeded — fixed by guarding both peeks; `NoEndpointError` isn't a `ProviderError` subclass so it was also falling into `routes/chat.py`'s generic catch-all, now gets its own honest message. Pytest gate: the "expected green in Docker, sandbox-only langchain-core artifact" claim was wrong — the real 16 failures are `sqlite3.OperationalError: unable to open database file`, because every test's `client` fixture builds a real `AsyncSqliteSaver` against the same `checkpoints.db` on `docker-compose.yml`'s Windows bind mount, and `pytest -n auto`'s parallel workers all hit it at once (a known SQLite/bind-mount locking issue). Fixed in `tests/conftest.py`: each xdist worker now gets an isolated temp `PAWN_DATA_DIR`. Committed as `ea765df`. Full detail: `workspace/status/dev_log.md`'s second 2026-07-14 entry. **Still needs the user:** re-run `docker compose exec backend pytest -n auto` to confirm.

**Bugfix (2026-07-14, round 1):** the "agent replies feel like two separate blocks" report was a real bug, not a styling nit — `ChatPage.tsx`'s `onProviderSwitch` still spliced a standalone `role:'notice'` chat bubble on every failover, a pre-A.8 mechanism (Step R4) never removed once A.8's `TraceView` started rendering the same event inline. Removed; failover now renders solely inside the trace, same bubble as the reply. Also: `Message.tsx`'s `break-all` narrowed to `break-words` (was force-breaking prose mid-word); `remark-gfm` found missing from `package-lock.json` entirely (present in `package.json`, used by table rendering) — `npm ci` would have failed to resolve it, fixed via `npm install`. Purple assistant-bubble color investigated and confirmed to be the user's own theme accent, not a defect — left alone. `tsc -b` + `vite build` both verified clean. Committed on `dev` as `bc77ba0`. Full detail: `workspace/status/dev_log.md` 2026-07-14 entry, `workspace/plan/gap_audit_2026-07-14.md` F-3–F-7. Still open (need the user's real Docker stack): F-1's backend traceback, full `pytest -n auto` gate, remaining A.9/M.7 live checklist items.

**Bugfix (2026-07-13):** duplicate "PAWN" root folders in Drive — `core/drive_factory.get_drive_for_user` had a concurrent cache-miss race (check-then-act around `_CACHE_LOCK`) where several requests missing the cache at once (e.g. right after Drive linking) each built their own `DriveStorage` and each independently raced `get_or_create_root()`'s find-or-create, both finding no folder yet and both creating one. Fixed with a per-user `threading.Lock` serializing the build (double-checked cache read so waiters reuse the winner's instance). New `backend/tests/test_drive_factory.py` (4 tests, regression-covers the race). 368 backend tests green (up from 364). **Still needs the user:** the two duplicate folders already in Drive from before this fix must be manually merged/cleaned up — not touched automatically.

**Docs (2026-07-13):** `deployment.md` rewritten — it was written assuming PAWN would share Enma's existing VM (hard rules about never touching `/opt/enma`, Enma health re-checks, etc.), but the real migration (`dev_log.md`'s 2026-07-05 entry) found Oracle's Always-Free pool split across separate instances, so PAWN ended up on its own dedicated VM (`pawn`, `144.24.119.184`) instead — the shared-VM framing never actually applied and was actively misleading for anyone using this as the runbook for a future update. Stripped the Enma-coexistence sections, dropped §4.3's now-dead provider-key secret generation step (matches the BYOK cleanup above), kept everything still-needed for a real redeploy (release/rollback workflow, verification checklist, the Nginx SPA-routing + CSP config with its two live-found gotchas). `docker-compose.prod.yml`'s header comment had the same stale "second isolated app on the shared Enma VM" framing — corrected to match.

**Cleanup (2026-07-13):** removed the dead pre-BYOK shared-secret path. `Resolver.__init__` used to accept a `secrets: Dict[str, str]` param (`self._secrets`) populated from 6 Docker-secret-backed provider API keys (`config.GEMINI_API_KEY`/`CEREBRAS_API_KEY`/`GROQ_API_KEY`/`HUGGINGFACE_API_KEY`/`GITHUB_API_KEY`/`OPENROUTER_API_KEY`) — but `_resolve_key()` only ever calls `key_store.get_key(user_id, ep.provider)` (the per-user BYOK key from Settings); `self._secrets` was never read anywhere. Removed: the 6 `config.py` constants, the `secrets` dict + param threading in `app_initializer.py`/`resolver.py`, the 6 secret entries from both `docker-compose.yml` and `docker-compose.prod.yml`, and the 6 real+`.example` files from `secrets/`. Updated 8 test files that constructed `Resolver(..., secrets={...})`; `test_keys.py`'s two resolver tests rewritten (they explicitly asserted BYOK wins over a shared secret that no longer exists). 369 backend tests green (same count — no tests added/removed, only rewritten); both compose files validate. **Found but not yet removed:** `EndpointEntry.secret` (in `registry/schemas.py`, populated in `registry/seed.py` for every endpoint) is the same vestige one layer deeper — defined and populated, never read anywhere in the app. Left alone this pass since it also touches the live `data/registry/endpoints.json` data file, not just code.

**Code+test audit of A.9/M.7 live-verification checklists (2026-07-13):** 10 parallel read-only audits against the two pending checklists (Phase A's A.9, 8 items; Phase M's M.7, 7 items) — see `dev_log.md`'s matching entry for the full per-item PROVEN/PARTIALLY PROVEN/GAP breakdown. **One real bug found and fixed:** `routes/chat.py`'s persist block never wrote a top-level `citations` field on the persisted assistant message (only `trace`), but the frontend reads `message.citations` directly — so citation source chips silently vanished after a genuine page reload despite surviving within the live SSE session. Fixed: `assistant_msg_dict["citations"]` now set whenever the graph's final state has any, mirroring the existing trace "absent not empty" rule. New `test_chat_agent_path_persists_top_level_citations`. 369 backend tests green (up from 368); `tsc --noEmit` clean. **One real gap left open (not fixed, flagged for later):** A.9-7 — `normalize.chat_complete` (used by the agent tool loop) has no `on_provider_switch` callback at all, unlike `chat_stream`, so an in-loop provider failover can never emit a `provider_switch` event today — a missing feature, not just a missing test.

Active step: **Phase A — Chat Agent Refinement, A.1–A.9 code-complete (2026-07-13); only A.9's live verification checklist remains, pending with the user.** `workspace/plan/plan_chat_agent_refinement.md` replaces the hand-rolled ReAct JSON action protocol with native OpenAI-compatible tool/function calling, adds internet access, scoped doc retrieval, model routing, a rebuilt orchestrator, preset subagents, and trace persistence — registered in `build_tracker.md` as A.1–A.9. **A.1 (native tool calling in the provider layer) done:** `llm_core.chat_complete`/`normalize.chat_complete` (non-streaming, tool_calls-capable, same failover pattern as the untouched `chat_stream`), `ModelEntry.supports_tools`, `resolver.pick_model_by_capability(require_tools=...)`. **A.2 (tool layer) done:** new `agent/tools/` package (`base.py`/`registry.py`/`execute.py`/`calculator.py`/`get_datetime.py`), `TOOL_TIMEOUT_SECONDS=20`; a CRITICAL DoS in the calculator's `**` exponent handling was found by code review and fixed (bounded exponent/expression length + `asyncio.to_thread` offload). **A.3 (internet access) done:** BYOK `tavily`/`brave` search keys; `agent/tools/web_search.py` (Tavily preferred, Brave fallback) + `agent/tools/fetch_url.py` (SSRF-guarded via `ipaddress` + per-redirect re-check, `trafilatura` extraction); mandatory security-auditor PASS (DNS-rebinding TOCTOU accepted as a documented residual per the plan's hostname-recheck design); citation plumbing (`citation_event`, `onCitation`, source chips) built, now emitted by A.6's execute loop and A.7's subagent loop. **A.4 (doc_search replaces whole-doc injection) done:** `upload.py` chunks+indexes docs into scoped RAG (`kind='document'`) via new `index_document_task`, draft-chat lazy-create rule implemented; `chat.py`'s whole-doc system-message injection deleted entirely; new `doc_search`/`search_memory` tools split by `match_kind`; `rebuild_index` extended to re-derive document chunks from `PAWN/uploads/`, discoverable even after a full Postgres wipe via a new Drive-persisted `attached_docs` record on each chat's meta.json; `postgres/schema.sql` + a new migration extend `match_scoped_chunks`/`search_scoped_chunks` to return `kind`/`doc_id`. **A.5 (model router) done:** new `core/router.py` — heuristic-first `classify()` exactly per the plan's thresholds/keyword sets/`ROLE_LEVELS`, LLM fallback tier (fails toward `heavy`/`needs_agent=True` on any error), `resolve_final_model()` implementing the user-override rule; now wired into `agent/graph.py`'s `classify_node` (A.6). **A.6 (orchestrator graph v2) done:** `agent/graph.py` rebuilt around `classify -> direct_answer (needs_agent=False, zero-overhead fast path) | plan -> execute (budgeted tool loop) -> final`; old ReAct nodes/`parser.py`/`routing.py` deleted entirely (not kept alongside). `execute_node` runs the tool loop (`AGENT_MAX_ITERATIONS=8`, `AGENT_MAX_TOKENS=24000`, budget exhaustion → "answer with what you have" nudge), emits `memory_hit`/`citation` events per hit; `final_node` streams via the untouched `chat_stream` with a compact tool-log digest (not raw observations), respecting the user's explicit model pick. `llm_core`/`normalize`'s `chat_complete` gained `tool_choice` passthrough + attached `usage`; `events.step_event` gained an `agent` field. **A.7 (preset subagents) done:** new `agent/subagents.py` — exactly three presets (`researcher`: web_search+fetch_url gated on a search key, `summarizer`/`coder`: no tools) exposed as `delegate_<name>(task)` tools; `run_subagent` runs its own bounded loop (`SUBAGENT_MAX_ITERATIONS=5`) sharing the parent's token budget, awaited strictly inline inside `execute_node`'s loop (no `create_task`/`gather`, ever); nested tool_log/citations merge into the parent's, tagged `agent: "<name>"` for A.8's nested trace rendering; subagents get no `delegate_*` tools, enforced both structurally (no preset exposes one) and at runtime (`run_subagent` rejects a delegate-shaped call if one ever appeared). New shared `agent/oai_tools.py` (`to_oai_tool`/`extract_citations`) avoids a graph↔subagents circular import. New `key_store.has_search_key()` de-duplicates the search-key-gating check that was drifting across three call sites. 359 backend tests green (up from 344); frontend build clean. **A.8 (trace persistence + frontend) done:** `constants.TRACE_MAX_ENTRIES=50`; new `routes/chat.py::_build_trace(tool_log, citations)` reads the graph's final checkpointed state (`await graph.aget_state(config)`) after the SSE stream ends and flattens it into a persisted `{kind: "tool"|"citation", agent, ...payload}` trace, newest-50-survive, attached only when non-empty (direct-answer path gets no `trace` key at all). Frontend: `types.ts`'s `TraceEntry` union backs both the persisted and live-SSE trace; new `components/TraceView.tsx` (extracted from `Message.tsx`) renders the locked "Claude-app style" presentation — present-tense tool labels flipping to past-tense+elapsed via a new `settleRunningTrace` helper in `ChatPage.tsx`, nested subagent grouping, auto-collapse to a "N steps · M tool calls · K sources · Xs" summary row; citation chips split into `components/CitationChips.tsx`; `useConversationStore.ts`'s cache round-trip now carries `trace`/`citations` (previously dropped there). 364 backend tests green (up from 359); `tsc`/`build` clean. **A.9 (tests, review, live verify) code/automated parts done:** mandatory security-auditor PASS across the full A.1-A.8 stack (SSRF guard, BYOK key handling, tool-escape/depth-guard boundaries, no-secret-leakage-into-trace, no-XSS-in-TraceView all confirmed; one non-blocking hardening comment added to `execute.py`). code-reviewer 1st pass FAIL → fixed: a CRITICAL snake_case/camelCase mismatch (`elapsed_ms` vs `elapsedMs`) silently broke elapsed-time display for every reloaded tool-use message, fixed by normalizing at the `client.ts` API boundary; 2 WARNs fixed (onToolCall's regex not matching delegation labels; a documented-and-accepted live-only cosmetic limitation around nested-subagent elapsed-time settling). Re-verified 364 backend tests + `tsc`/`build` clean. **A.9's live verification checklist (plan §A.9, 8 items) needs the user's own BYOK/search keys and a browser — handed over as a numbered manual list, not yet run.** Phase A is code-complete; A.9 stays open until the user confirms the live checklist.

Phase M — memory scoping is done (2026-07-13, all of M.1–M.7's coding + automated verification complete). `workspace/plan/plan_memory_scoping.md` drops the always-cross-chat memory tier for strict per-chat/per-project isolation via a two-container model (standalone chats + projects). **Only outstanding item: M.7's live verification checklist** (plan §M.7 items 1-7 + a re-index check from the embedding-model swap below) needs a real Drive-linked stack and the user in the loop — see `build_tracker.md`'s M.7 entry for the exact pending list.

M.1 (schema + migration): `postgres/schema.sql`'s `memory_chunks` redefined with `scope_type`/`scope_id`/`chunk_id`/`kind`/`doc_id`/`msg_index` columns and a `unique(user_id, chunk_id)` idempotency constraint; old exclude-semantics SQL functions replaced with `match_scoped_chunks`/`search_scoped_chunks` (strict scope equality); `postgres/migrations/2026-07_memory_scoping.sql` applied to local dev Postgres; `memory/index.py`'s `add_chunk` re-signatured to upsert on `(user_id, chunk_id)`.

M.2 (Drive storage layer): `storage/drive.py` gains `move_item`; `storage/conversations_drive.py` retargeted to `PAWN/conversations/chats/{conv_id}/` (from the old flat `PAWN/conversations/{conv_id}/`) with a project-aware `_locate_conv_folder`, per-chat `rag_chunks.jsonl` helpers, and an automatic one-time legacy-folder migration (layout-inferred, no flag file); new `storage/projects_drive.py` (full project CRUD + two-way `move_chat`, folder placement alone determines scope). 180 backend tests green (up from 165).

M.3 (chunker + write path): new `memory/chunker.py` (`chunk_turn`, fixed-size overlapping chunks, `MEMORY_CHUNK_TOKENS=400`/`MEMORY_CHUNK_OVERLAP_TOKENS=50`) and `memory/indexer.py` (`resolve_scope` with an in-process `SCOPE_CACHE_TTL_SECONDS=300` cache derived from Drive folder placement, `index_turn_task` scheduled as a background task from `chat.py`'s persist-turn block — chunks a turn, writes `rag_chunks.jsonl` to Drive **before** any Postgres write, a Drive failure aborts with zero Postgres rows — then `rebuild_index` for scope-wide re-derivation from Drive). `routes/conversations.py`'s `DELETE` now also deletes a chat's Postgres `memory_chunks` rows. `memory/summarize.py`'s stale `add_chunk` call is now routed through `index_turn_task`. **Both M.1/M.2 transitional gaps for the write path are now closed** — every turn and every rolling summary indexes into Drive + Postgres under the chat's current scope. 199 backend tests green (up from 180). See `dev_log.md` 2026-07-13 for the full M.3 entry, including one real id-vs-name scope bug caught by tests before review.

M.4 (retrieval rewrite + agent wiring): `memory/retrieve.py` rewritten to `retrieve(query, user_id, scope_type, scope_id, top_k=MEMORY_TOP_K)` (`MEMORY_TOP_K=4`), querying `match_scoped_chunks`/`search_scoped_chunks` (strict scope equality) — the M.3 write-path gap this closes. `agent/graph.py`: `load_context_node` no longer auto-retrieves at graph start (now a no-op; `retrieved_memory` starts `[]`); `search_memory_node` is the sole retrieval call site, using the scoped signature, guarded so stateless chats (no resolved scope) never query Postgres even if the agent tries; `AgentState` gains `scope_type`/`scope_id`. `routes/chat.py` resolves scope once per request via M.3's `indexer.resolve_scope` and threads it into the graph. `events.memory_hit_event` gains additive `scope`/`source_conv_id`; frontend shows a scope badge on project-sourced memory hits (`types.ts`/`client.ts`/`ChatPage.tsx`/`Message.tsx`). **Memory retrieval is now fully live and scope-isolated** — the write path (M.3) and read path (M.4) are both closed; a chat's own history, or a project's shared history, is retrievable, and nothing crosses a scope boundary (proven by a dedicated cross-scope-miss test). 203 backend tests green (up from 199); `npm run build` clean.

M.5 (projects backend API + two-way chat moves): new `routes/projects.py` — full project CRUD (idempotent create, list with `chat_count`, rename, cascade delete) plus `POST`/`DELETE /projects/{id}/chats/{conv_id}` (move in/out). Both move directions relocate the Drive folder **before** updating Postgres `scope_type`/`scope_id` (Drive is authoritative) and evict the in-process scope cache (`indexer.evict_scope`) so the next resolution sees the new placement immediately; both are idempotent and reject moving into a second project while already in one (409). New `memory/locks.py` (`get_conv_lock`) — a per-`(user, conv)` `asyncio.Lock` now held by BOTH `index_turn_task` and every move/cascade-delete operation, so an in-flight index write and a scope-mutating move/delete can never interleave. 219 backend tests green (up from 203). code-reviewer PASS (1 WARN fixed: cascade delete now holds every contained chat's lock, closing an orphan-Postgres-row race). security-auditor PASS (0 findings, run proactively given the destructive cascade-delete surface — confirmed all Drive ops are implicitly user-scoped and all SQL is parameterized + `user_id`-scoped). **M.3→M.5 close the entire write+read+management loop for memory scoping** — chats and projects can be created, chatted in, retrieved from (scope-isolated), and moved between each other, all correctly. See `dev_log.md` 2026-07-13 for the full M.5 entry.

Prior: D.8 fully complete — migrated off the paid bridge onto the permanent free-tier Ampere instance, `pawn-temp` terminated.** The background retry loop succeeded 2026-07-04 (attempt 183) and provisioned `pawn` (`144.24.119.184`, 1 OCPU/6GB Ampere A1, ARM64) as its own dedicated instance (not shared with Enma — Enma's Always-Free pool turned out to be split across separate VMs, not one shared host). Migrated data-preserving: Docker+Node installed fresh, `main` cloned, secrets copied verbatim from `pawn-temp` (same `encryption_secret`/`jwt_secret` so existing encrypted BYOK keys/Drive tokens kept working), `pg_dump`/restore of all 6 tables (verified matching row counts), DuckDNS repointed by the user, fresh Let's Encrypt cert issued via `certbot --nginx`. One real bug found: `docker-compose.prod.yml`'s CPU limits (`1.5/1.0/0.5`) assumed 2 vCPUs (true of `pawn-temp`'s x86 hyperthreaded OCPU) and broke outright on Ampere A1's 1 real vCPU (no SMT) — rescaled to `0.6/0.3/0.1`, fixed on `main`. User verified login/chat/load in-browser on the new instance, then explicitly authorized immediately terminating `pawn-temp` (a final local backup was taken first — `backups/pawn-temp-final-2026-07-05/`, gitignored — before running `oci compute instance terminate`). No more paid-instance billing risk.

Full `deployment.md` §7 verification checklist passed live: HTTPS health, no CSP violations, full Google OAuth round-trip (Drive-linked — the one path untestable locally), BYOK chat streaming, and a real Kaggle SDXL image generation through the PostgREST rendezvous.

**4 real bugs found and fixed during this first live deploy** (all captured back into `deployment.md` so the pending migration won't repeat them):
1. Oracle's stock Ubuntu image's host **iptables only allows SSH (22)** by default — the OCI Security List already permitted 80/443, but the host itself still rejected everything else, so the app was completely unreachable externally until an explicit `iptables -I INPUT` rule was added and persisted.
2. `/pgrst/`'s Nginx `client_max_body_size` defaulted to 1MB — the warm Kaggle kernel's PATCH write-back of a finished base64 image (1-3MB) got silently **413**'d, leaving every image-gen job stuck at "running" forever with no error surfaced anywhere in PAWN's own UI. Fixed: `client_max_body_size 20m;`.
3. `get_session_status()`'s cold-start timeout (300s/5min) was too short — a live SDXL cold start (deps install + multi-GB weight download/load) ran past 8 minutes without failing, but PAWN auto-killed the session and reaped its jobs as "session ended"/"terminated unexpectedly" before the kernel got a chance to finish. Raised to a named constant, `IMAGE_SESSION_STARTUP_TIMEOUT_SECONDS = 900`.
4. **CSP `img-src` gap**: `default-src 'self'` doesn't implicitly cover the `data:` scheme, and no `img-src` directive existed — every Image Lab thumbnail/lightbox (`<img src="data:image/...;base64,...">`) was silently blocked by the browser with no console-visible error beyond a broken image icon. Fixed in both the backend's `SecurityHeadersMiddleware` and the static frontend's own Nginx `location /` block (which needed its own full copy of the security headers in the first place — Nginx doesn't inherit them from proxied routes).

**Also found and fixed:** `scripts/promote-to-main.sh` was silently dying before its final `git commit` on every real run — both actual promotions needed manual completion. Root cause: a `while read` loop reading from a pipe always exits 1 on EOF regardless of what it processed (a well-known bash gotcha), and under `set -e` with no `|| true` guard that killed the script immediately after doc-stripping, every time, despite the merge itself always resolving cleanly. Fixed and verified end-to-end against a throwaway clone.

`plan_drive_mandatory.md` Phases 1-4 all DONE (closed 2026-07-04 — code-reviewer + security-auditor gap closed on the combined Phase 1-3 diff, both PASS, 4 WARN fixes applied: stale comment, missing error logging in `drive_factory.py`/`auth.py`, raw exception text leaking to clients in `upload.py`/`chat.py` genericized). 152 backend tests green.

**Deployment plan simplified 2026-07-04 — dropped the two-environment staging-first deploy.** `dev` stays local-only, never deployed to the VM; only `main` deploys to prod (`pawnai.duckdns.org`). Rationale: PAWN has no public user base yet (Google OAuth consent screen is Testing-mode with an explicit allowlist), so D.6's local pre-deploy gate substitutes for a dedicated staging box. Local dev and prod now **share one Google OAuth client** (both `localhost` and `pawnai.duckdns.org` redirect URIs registered on it) and the same Google account(s) for login — but database/secrets stay **separate** per environment (own local Postgres + own `encryption_secret`/`jwt_secret` for dev, own set on the VM for prod), so a bad local test can never touch real prod data. Accepted tradeoff: local dev is x86, the VM is ARM64, so any ARM-specific issue surfaces for the first time at the actual prod deploy, not a disposable staging box — judged acceptable given the small, allowlisted user base today. `plan_deployment.md` D.1-D.7 now marked `[x]` (were previously out of sync with `build_tracker.md`); D.6b (staging stack) dropped; D.7/D.8 rewritten prod-only. `deployment.md` itself rewritten prod-only too — the staging section is fully removed, so the runbook now matches the plan exactly. A known pre-existing gap — permissive `pawn_anon` Postgres RLS on `image_sessions`/`image_jobs`, not scoped per-user — must close before ever flipping the OAuth consent screen from Testing to public (tracked, not blocking this deploy).

Phase D (Production Deployment): D.1-D.8 all done — Supabase fully replaced by self-hosted Postgres+pgvector+PostgREST; hardcoded localhost values killed; frontend build URL fixed; `scripts/promote-to-main.sh` clean-`main` mechanism (fixed 2026-07-04); pre-deploy gate green; `deployment.md` runbook + parameterized `docker-compose.prod.yml`; first live deploy executed and verified (2026-07-04, on the temporary `pawn-temp` bridge — see above). **Remaining:** migrate to the permanent free-tier Ampere instance once capacity opens up. **UX follow-up done:** "Connect Google Drive" control in Settings — backend `GET /auth/drive/status` (verifies real Drive usability via a cheap `get_or_create_root`, not just token presence) + a Drive row first in the API-keys card (Connected/Not-connected badge, Connect/Reconnect button reusing the OAuth `login()` flow). 157 backend tests green, build clean. Phase 3 P3-1 encryption FOUNDATION done (crypto module, session, salt endpoint, vitest) but its passphrase gate was removed from the auth flow — unwired to anything, pure friction. Full encrypt/decrypt-on-write wiring still DEFERRED (conflicts with server-side LLM/RAG/summarization — see implemented_phases/phase_8_encryption.md). Mobile readiness pass (all 7 fixes) done.
Phase: dev/main — imageLab merged into dev, dev merged into main (2026-06-30). All Phase W, img2img, and Phase 6 UI work is now on main. imageLab branch deleted. Next: migrate PAWN to the permanent free-tier instance once Ampere capacity opens up.

---

### Phase A — A.1: native tool calling in the provider layer (plan/plan_chat_agent_refinement.md) — 2026-07-13

- `backend/app/core/llm_core.py` — new `chat_complete(url, model, messages, headers, tools=None, tool_choice="auto") -> dict`, non-streaming sibling to `stream_llm` (untouched), same provider detection/wire format; malformed 200 responses raise a clear `ProviderError` instead of a raw `KeyError`.
- `backend/app/core/normalize.py` — new `chat_complete(model_id, messages, resolver, rate_limiter, user_id=None, tools=None) -> dict`, mirrors `chat_stream`'s two-level failover (endpoint-level, then cross-model) via a new `_complete_one_model` helper; imports llm_core's version aliased as `_chat_complete_llm`.
- `backend/app/registry/schemas.py` — `ModelEntry.supports_tools: bool = True`; set explicitly on every entry in `data/registry/models.json` and `seed.py`'s `INITIAL_MODELS`.
- `backend/app/resolver/resolver.py` — `pick_model_by_capability` gains `require_tools: bool = False`.
- New `backend/tests/test_chat_complete.py` (8 tests). 235 backend tests green (up from 227). code-reviewer PASS (1 WARN fixed); build-validator PASS.

### Phase A — A.2: tool layer (plan/plan_chat_agent_refinement.md) — 2026-07-13

- New `backend/app/agent/tools/` package — `base.py` (`ToolSpec`/`ToolContext`), `registry.py` (`get_tools(ctx)`, currently returns only the two always-on tools — `web_search`/`search_memory`/`doc_search` gating deferred to A.3/A.4), `execute.py` (`run_tool` — `asyncio.wait_for` + never-raise `TOOL_ERROR` wrapping), `calculator.py`, `get_datetime.py`.
- `backend/app/constants.py` — `TOOL_TIMEOUT_SECONDS = 20`.
- **CRITICAL fixed:** the calculator's AST evaluator originally let an unbounded `**` exponent (e.g. `99999999999999 ** 99999999999999`) through as valid grammar — a synchronous resource-exhaustion DoS the `asyncio.wait_for` timeout couldn't preempt since the computation never yields to the event loop. Fixed with `_MAX_POW_EXPONENT=1000`/`_MAX_EXPRESSION_LENGTH=200` bounds checked before computing, plus `asyncio.to_thread` offload as defense-in-depth.
- New `backend/tests/test_agent_tools.py` (20 tests). 265 backend tests green (up from 235). code-reviewer: 1st pass FAIL → fixed → re-verified PASS; build-validator PASS.

### Phase A — A.3: internet access (plan/plan_chat_agent_refinement.md) — 2026-07-13

- `backend/app/core/key_store.py` — `VALID_PROVIDERS` gains `tavily`/`brave` (same encrypted BYOK storage as LLM keys). `frontend/src/components/ApiKeysSection.tsx` — "Search (optional)" key group.
- `backend/app/agent/tools/web_search.py` — Tavily `POST` (preferred) / Brave `GET` fallback; `backend/app/agent/tools/fetch_url.py` — `httpx` + `trafilatura`, SSRF-guarded (`guard_url`: scheme allowlist, hostname resolved + checked against private/loopback/link-local/reserved/multicast/unspecified ranges including IPv4-mapped-IPv6, re-checked per redirect hop up to `max_redirects=3`).
- `backend/app/agent/tools/registry.py` — `fetch_url` always-on; `web_search` gated on a configured search key.
- `backend/app/events.py` — `citation_event(url, title)` (plumbing only; not yet emitted — A.6 wires it into the execute loop). Frontend: `client.ts` `onCitation`, `ChatPage.tsx` de-duped citation collection, `Message.tsx` source chips (http(s)-scheme-filtered hrefs).
- New `backend/tests/test_agent_tools_search.py` (21 tests: provider-mocked search, SSRF matrix, key-gating). 286 backend tests green (up from 265). code-reviewer PASS (2 WARN fixed); **mandatory security-auditor PASS** (0 CRITICAL; DNS-rebinding TOCTOU accepted as documented residual); build-validator PASS.

### Phase A — A.4: doc_search replaces whole-doc injection [Phase M] (plan/plan_chat_agent_refinement.md) — 2026-07-13

- `backend/app/routes/upload.py` — accepts optional `conversation_id`; lazy-creates the conversation if missing (draft-chat rule) so a doc upload always has a scope; schedules `memory/indexer.py`'s new `index_document_task` via `BackgroundTasks`.
- `memory/indexer.py` — `index_document_task` chunks (reuses `chunk_turn`), embeds, and writes directly to Postgres (`kind='document'`, `doc_id`) — not to `rag_chunks.jsonl`, since `PAWN/uploads/<doc_id>.txt` is the rebuild source for documents. `rebuild_index` extended to re-derive document chunks per scope. New `conversations_drive.add_attached_doc`/`get_attached_docs` persist `{doc_id, filename}` on each chat's `meta.json` (Drive) so rebuild survives a full Postgres wipe.
- `memory/index.py`'s `add_chunk` gains `kind`/`doc_id`; `memory/retrieve.py`'s `retrieve()` gains `match_kind` (was hardcoded `"message"`); `agent/graph.py`'s old ReAct `search_memory_node` now passes `match_kind="message"` explicitly to preserve behavior.
- `postgres/schema.sql` + new migration `2026-07_doc_search_kind_return.sql` — `match_scoped_chunks`/`search_scoped_chunks` now also return `kind`/`doc_id`; applied live.
- `backend/app/routes/chat.py` — whole-doc system-message injection deleted entirely; `doc_id` stays on `ChatRequest` but is now inert.
- New `agent/tools/doc_search.py` (`match_kind='document'`, filename-prefixed via `get_attached_docs`) and `agent/tools/search_memory.py` (`match_kind='message'`); `registry.py` adds both only when `ctx.scope_type is not None`.
- Frontend: `client.ts`'s `uploadDoc(file, conversationId?)`; `ChatPage.tsx`'s `handleUpload` promotes the draft first, mirroring `handleSend`.
- Tests updated/added across `test_upload.py`, `test_indexer.py` (+6), `test_rag.py` (2 updated + 1 new cross-scope document isolation test), `test_agent.py` (1 assertion), new `test_agent_tools_docs.py` (11 tests). 304 backend tests green (up from 286). code-reviewer PASS (0 CRITICAL/WARN); build-validator: 1st pass FAIL (missing cross-scope doc isolation test) → added → re-verified.

### Phase A — A.5: model router (plan/plan_chat_agent_refinement.md) — 2026-07-13

- New `backend/app/core/router.py` — `classify(messages, has_doc, has_tools_likely, resolver=None, rate_limiter=None, user_id=None, has_search_key=False) -> RouteDecision`. Heuristic tier exact per plan (heavy triggers: length > `ROUTER_HEAVY_CHAR_THRESHOLD=1500`, fenced code block, 8-keyword heavy set, doc attached, prior turn used tools; light: length < `ROUTER_LIGHT_CHAR_THRESHOLD=200` and none of the above); ambiguous band defers to one `chat_complete` LLM fallback call (fast level), any failure defaults `heavy`/`needs_agent=True`. `needs_agent` = heavy OR a URL present OR (search key configured AND a time-sensitive keyword matches). `ROLE_LEVELS` dict added to `constants.py`. New `resolve_final_model(difficulty, user_model_id, resolver, user_id=None)` — explicit user model pick always wins for the final answer.
- Self-contained this session — not yet wired into `agent/graph.py` (that's A.6). New `tests/test_router.py` (29 tests). 333 backend tests green (up from 304). code-reviewer PASS; build-validator PASS.

### Phase A — A.6: orchestrator graph v2 (plan/plan_chat_agent_refinement.md) — 2026-07-13

- `backend/app/agent/graph.py` rebuilt end to end: `classify_node` (calls A.5's `router.classify`, writes `difficulty`/`needs_agent`) → `direct_answer_node` (`needs_agent=False`, one `chat_stream` call, zero step/plan events — the fast path) | `plan_node` (one `chat_complete(tool_choice="none")` producing a ≤5-line plan, emitted as a `step` event, skipped for `difficulty=="light"`) → `execute_node` (the tool loop: `chat_complete(tools=...)` each iteration, tool_calls run via A.2's `run_tool`, stops on no tool_calls / `AGENT_MAX_ITERATIONS=8` / `AGENT_MAX_TOKENS=24000`, budget exhaustion appends a "budget exhausted — answer with what you have" system nudge; emits `memory_hit`/`citation` events per hit) → `final_node` (streams via the untouched `chat_stream` on `resolve_final_model()`, digesting `tool_log` into one compact system message rather than the raw transcript).
- `backend/app/agent/parser.py`/`backend/app/agent/routing.py` (`build_agent_prompt`, `route_action`) **deleted** — the old `load_context`/`agent`/`search_memory`/`ask_model` nodes are gone, not kept alongside.
- `AgentState` rewritten: `messages`, `user_id`, `conversation_id`, `user_model_id`, `has_doc`, `scope_type`/`scope_id` (Phase M), `difficulty`, `needs_agent`, `plan`, `tool_log`, `tokens_used`, `citations`, `final_answer`.
- `llm_core.chat_complete`/`normalize.chat_complete` gain a `tool_choice` passthrough and attach `usage` onto the returned message dict (additive, non-breaking) so the execute loop can track `AGENT_MAX_TOKENS`. `events.step_event` gains `agent: str = "main"` (subagent names arrive in A.7); `routes/chat.py`'s AgentState wiring updated for the new shape, dispatch table gains a `citation` branch.
- `backend/tests/test_agent.py` fully rewritten (old ReAct tests removed, not ported) — covers classify routing, the direct-answer zero-overhead path, plan skip/cap/failure, the execute tool loop (success, unknown tool, malformed tool-call JSON, iteration cap, token-budget cap), and final digest/model-override behavior.
- code-reviewer found 2 WARN, both fixed: (1) the `search_memory`/`doc_search` hit parser used per-line `^...$` anchors, silently truncating any retrieved chunk whose text itself spanned multiple lines — rewritten as `_memory_hit_lines` (marker-to-next-marker span, preserves embedded newlines), 3 new regression tests added; (2) `plan_node`/`execute_node` caught a bare `except Exception` around `chat_complete` — split into `(ProviderError, NoEndpointError)` vs generic `Exception` with distinct log labels (same never-raises behavior, clearer logs). A first attempt at fix #2 also flipped `budget_exhausted=True` on the execute-loop's exception path, which broke a pre-existing test (`test_chat_truncates_context_to_last_10_messages`, 11→12 messages) by always appending the budget nudge on any provider error — reverted that part, kept only the clearer logging.
- 344 backend tests green (up from 333) via `docker compose exec backend pytest` (needed an explicit `docker compose build backend` first — `backend/tests/` isn't bind-mounted/watched, same gotcha A.1's dev-log entry already flagged). code-reviewer PASS; build-validator PASS (all 7 plan criteria verified line-by-line against the diff). No security-auditor run (pure orchestration logic reusing A.1-A.5's already-audited tool/search/SSRF surfaces).

### Phase A — A.7: preset subagents (plan/plan_chat_agent_refinement.md) — 2026-07-13

- New `backend/app/agent/subagents.py` — `SUBAGENTS` dict, exactly three presets: `researcher` (tools: `fetch_url` always + `web_search` gated on a configured Tavily/Brave key, level `subagent_researcher`), `summarizer` (no tools, level `subagent_summarizer`), `coder` (no tools, level `subagent_coder`, heavy). `delegate_tool_specs()` builds the three `delegate_<name>(task: str)` OAI tool schemas appended to the orchestrator's own toolset. `run_subagent(name, task, ctx, tokens_used) -> dict` runs a bounded tool loop (`SUBAGENT_MAX_ITERATIONS=5`), sharing the parent's single `AGENT_MAX_TOKENS` counter (threaded in/out, never reset or double-counted).
- `backend/app/agent/graph.py`'s `execute_node` special-cases any `delegate_`-prefixed tool_call, routing it to `run_subagent` directly (bypassing the generic `run_tool` dispatch, since a subagent's result must feed `tokens_used`/`tool_log`/`citations` back into `AgentState`, not just return a string) — strictly sequential, `await`ed inline in the same loop, no `create_task`/`asyncio.gather` anywhere (locked product decision #6, verified by grep). The subagent's own nested `tool_log` entries (tagged `agent: "<name>"`) splice in right after its `delegate_<name>` entry (tagged `agent: "main"`); its citations merge into the parent's deduped list.
- **Depth guard (max depth 1):** no preset's `tools_fn` ever returns a delegate tool — and, per a code-reviewer WARN, `run_subagent`'s own dispatch loop now also explicitly rejects any delegate-shaped tool_call at runtime (`TOOL_ERROR: subagents cannot delegate further`), so the guard isn't just true-by-omission.
- New shared `backend/app/agent/oai_tools.py` (`to_oai_tool`/`extract_citations`) — pulled out of `graph.py`'s private functions so `subagents.py` can reuse them without a graph↔subagents circular import.
- New `backend/app/core/key_store.has_search_key(user_id)` — a second code-reviewer NOTE flagged the "has a tavily/brave key" check duplicated verbatim across the main tool registry, the new researcher subagent, and `classify_node`; factored into one helper, all three call sites updated.
- New `backend/tests/test_subagents.py` (15 tests): preset count/shape, depth guard (structural omission + runtime rejection regression), researcher gating with/without a key, delegate tool spec shape, unknown-subagent error, no-tool-calls path, shared-budget accumulation, iteration cap, already-exhausted-parent-budget short-circuit, never-raises-on-upstream-failure, delegate-prefix constant consistency, and full `execute_node` wiring (delegate bypasses generic dispatch, trace merges, tokens accumulate correctly across parent+subagent calls).
- 359 backend tests green (up from 344) via `docker compose exec backend pytest` after a rebuild. code-reviewer PASS (2 WARN fixed, both above); build-validator PASS (all 9 plan criteria verified against the diff, 359/359 live pytest run). No security-auditor run (delegation reuses A.1-A.5's already-audited tool/search/SSRF surfaces; purely in-process orchestration, no new secrets/auth/outbound-HTTP surface).

### Phase A — A.8: trace persistence + frontend (plan/plan_chat_agent_refinement.md) — 2026-07-13

- `backend/app/constants.py` — `TRACE_MAX_ENTRIES = 50`. New `backend/app/routes/chat.py::_build_trace(tool_log, citations)` — after the SSE stream finishes, fetches the graph's final checkpointed state via `await graph.aget_state(config)` (the compiled graph already carries an `AsyncSqliteSaver` checkpointer from Phase 1.5) and flattens `AgentState.tool_log`/`citations` into `{kind: "tool"|"citation", agent, ...payload}` entries, newest-`TRACE_MAX_ENTRIES`-survive (oldest dropped). Attached to the persisted assistant record only when non-empty — the direct-answer fast path never gets a `trace` key at all. `conversations_drive.append_messages`/`load_messages` and `GET /conversations/{id}` needed zero changes (generic JSON passthrough).
- `frontend/src/types.ts` — new `TraceEntry` union (`kind`: step/tool/citation/model_call/memory_hit/provider_switch), used for both the persisted (reload) trace and the richer live-only kinds streamed via SSE. `PersistedMsg` gains `trace`/`citations`.
- `frontend/src/api/client.ts` — `StreamChatCallbacks.onStep` now also carries `agent` (previously dropped despite being in the SSE payload since A.6); new `onToolCall(name, agent)` fires alongside `onStep` for `"Calling X"`/`"Delegating to X"`-shaped labels, extracting a clean tool/subagent name. `fetchConversation` normalizes the backend's snake_case `elapsed_ms` → `elapsedMs` at the API boundary (a code-reviewer CRITICAL from A.9, see below).
- New `frontend/src/components/TraceView.tsx` (extracted from `Message.tsx` per frontend.md's ~150-line rule) — the "Claude-app style" presentation locked with the user this session: muted activity lines above the darker reply while streaming; present-tense tool labels via a friendly name lookup ("Searching the web…", "Reading page…", etc.) that flip to past-tense + elapsed seconds once "settled"; nested/indented subagent grouping; auto-collapse to a "N steps · M tool calls · K sources · Xs" summary row on stream completion (collapsed by default for historical/reloaded messages, chevron re-expands).
- `frontend/src/pages/ChatPage.tsx` — new `settleRunningTrace`/`appendTraceEntry` helpers; a tool-shaped step starts `status: "running"` + `startedAt`, settled (`status: "done"`, `elapsedMs` computed) the instant the next trace-worthy event arrives — correct given the strictly-sequential agent loop (at most one entry is ever running).
- New `frontend/src/components/CitationChips.tsx` (also extracted from `Message.tsx`) — kept outside/independent of the collapsible trace block, per plan.
- `frontend/src/store/useConversationStore.ts` — `toPersisted`/`fromPersisted` now carry `trace`/`citations` through the localStorage cache round-trip (previously dropped there, a known pre-A.8 gap the plan called out explicitly); `backgroundLoadDetail`'s server-fetch mapper does too.
- New tests in `backend/tests/test_chat.py` (5): `_build_trace`'s kind-mapping and newest-survive capping, the direct-answer path persisting no `trace` key, and a full `/chat` → Drive-persisted-message round trip via a forced heavy/tool-call path. 364 backend tests green (up from 359); `tsc --noEmit` + `npm run build` clean.

### Phase A — A.9: tests, review, live verify (plan/plan_chat_agent_refinement.md) — 2026-07-13

- Full backend suite (364) + frontend `tsc`/`build` gates green.
- **security-auditor (mandatory per plan) ran against the full A.1-A.8 stack end to end, not just this session's diff — PASS.** Confirmed: SSRF guard + IPv4-mapped-IPv6 handling unchanged/correct; BYOK search keys never leak through any exception path; tool-call dispatch can't escape the per-request registry; the subagent depth guard holds both structurally and at runtime; no tool arg/observation can carry a decrypted secret into the newly-persisted `trace`; `TraceView`/`CitationChips` render all trace text as plain JSX (no `dangerouslySetInnerHTML`), citation hrefs stay scheme-filtered. One non-blocking WARN fixed — `backend/app/agent/tools/execute.py`'s `TOOL_ERROR: {e}` catch-all now feeds persisted, API-served data, not just a transient stream; added a comment flagging this for future tool authors. A.3's DNS-rebinding TOCTOU residual remains accepted, unchanged.
- **code-reviewer 1st pass FAIL — 1 CRITICAL, fixed:** the backend persists `elapsed_ms` (snake_case) but `types.ts` declared `elapsedMs` (camelCase) with no mapping on the reload path — every reloaded historical tool-use message silently lost its elapsed-time display, and `tsc` couldn't catch it since `fetchConversation`'s return type is asserted, not runtime-validated. Fixed in `client.ts`: `fetchConversation` now normalizes each entry's `elapsed_ms` → `elapsedMs` at the API boundary. 2 WARNs fixed: `onToolCall`'s regex only matched `"Calling X"`, never `"Delegating to X"`, despite `ChatPage.tsx` treating both as tool-shaped steps — unified the two regexes and cross-referenced them by comment so they can't drift again. A live-only cosmetic WARN (a "Delegating to X" entry settles early — as soon as the subagent's own first nested step arrives — understating the outer delegation's displayed elapsed time for that turn) was assessed and left as a documented, accepted limitation: the persisted trace is unaffected (the backend times the whole delegate call server-side via `time.monotonic()`), and a correct fix needs per-agent-group running-state tracking, a bigger change than this self-correcting gap warrants right now. Re-verified: 364 backend tests + `tsc`/`build` clean after all fixes.
- **Live verification checklist (plan §A.9, 8 items) confirmed 2026-07-14** via `claude-in-chrome` against the user's real running stack — see `gap_audit_2026-07-14.md` §§F/J/K and `dev_log.md`'s 2026-07-14 entry. **A.9 marked `[x]` in `build_tracker.md`.**
- **Phase A is code-complete and live-verified (A.1–A.9).** Not yet promoted to main — the user's call.

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

### Phase D — D.1: kill hardcoded localhost values (plan/plan_deployment.md) — 2026-07-03

- `backend/app/config.py` — `CORS_ORIGINS`, `FRONTEND_URL`, `OAUTH_REDIRECT_URI`, `CSP_CONNECT_SRC` added as plain `os.getenv(name, default)` module constants (non-secret deployment URLs, not routed through `read_secret`); defaults exactly match the prior hardcoded localhost values so `docker compose up` locally is unaffected.
- `backend/app/main.py` — CORS `allow_origins` built from `CORS_ORIGINS.split(",")` (whitespace/empty-entry safe); raises `ValueError` at startup if `*` is ever present (guards against an operator accidentally enabling wildcard CORS).
- `backend/app/routes/auth.py` — `_FRONTEND_URL`/`_REDIRECT_URI` now sourced from `config.FRONTEND_URL`/`config.OAUTH_REDIRECT_URI` instead of hardcoded strings.
- `backend/app/middleware/security.py` — CSP `connect-src` now interpolates `config.CSP_CONNECT_SRC`.
- New `backend/tests/test_deployment_config.py` (6 tests: defaults, env-var override via `importlib.reload`, CORS allow/reject, CSP default, wildcard-rejection guard). 148 backend tests green; `docker compose config` still validates.
- code-reviewer PASS (2 WARN fixed: a `finally`-block test-pollution bug where reloading `app.config` while overrides were still set left the module polluted for later tests; a doc comment clarifying `CSP_CONNECT_SRC` is space-separated, not comma-separated like `CORS_ORIGINS`). security-auditor PASS (1 WARN fixed: added the `*` wildcard guard).

### Phase D — D.2: fix frontend build-time API URL (plan/plan_deployment.md) — 2026-07-03

- `frontend/.env.example` — `VITE_API_URL` port fixed 8000 → 8001 (doc-only, matches actual dev backend port).
- New committed `frontend/.env.production` — `VITE_API_URL=https://pawnai.duckdns.org`. Confirmed embedded correctly in the production build bundle (`vite build` output contains the domain string). Vite only loads `.env.production` in `production` mode (`vite build` default); local `npm run dev` reads `.env`/`.env.development`, so no local-dev regression.
- `npm run build` clean. code-reviewer PASS (1 NOTE: `client.ts`'s hardcoded fallback default is still `:8000`, pre-existing and out of scope — only hit if `VITE_API_URL` is entirely absent).

### Phase D — D.3+D.4: Supabase → self-hosted Postgres+pgvector+PostgREST (plan/plan_deployment.md) — 2026-07-03

- **Driver choice:** psycopg3 (sync), not asyncpg — every existing Supabase call site was a sync function behind `run_in_threadpool` (~25 call sites across 6 route/module files); psycopg3 preserves that shape untouched, avoiding a much larger async ripple.
- `backend/app/db/postgres_client.py` (new, replaces deleted `supabase_client.py`) — per-call `psycopg.connect()` (no pool; cheap on a local Docker network, already cheaper than the old HTTPS round-trip to Supabase's cloud), `fetchone`/`fetchall`/`execute`, plus a `transaction()` context manager for atomic multi-statement sequences.
- `backend/app/config.py` — `SUPABASE_URL/SERVICE_KEY/ANON_KEY` → `POSTGRES_DSN` (secret) + `POSTGREST_PUBLIC_URL` (non-secret, D.4's Kaggle-payload URL).
- `routes/auth.py`, `core/key_store.py`, `core/drive_factory.py`, `memory/index.py`, `memory/retrieve.py` — Supabase `.table()/.rpc()` calls rewritten as parameterized SQL (`%s` placeholders). `retrieve.py`'s two SQL-function calls need explicit `::vector`/`::int` casts (Postgres can't implicitly cast a plain array to `vector` in a function-call argument context — found via live-Postgres integration testing, not caught by mocks). `drive_factory.py` re-stringifies a `timestamptz` read back to ISO (psycopg returns a native `datetime`, but `DriveStorage.__init__` expects a string).
- `core/image_session.py` — full rewrite to SQL. psycopg returns native `uuid.UUID` for `uuid` columns, so return points are wrapped in `str()`; `_parse_ts` now accepts native `datetime` as well as ISO strings; `Json(...)` wraps dict params for `jsonb` columns. `start_session`/`extend_session`/`submit_session_job` wrap their read-then-write sequences (evict+insert, liveness-check+update, liveness-check+insert) in `transaction()` to close a race window a code reviewer flagged. D.4 part: the Kaggle-payload dict now injects `postgrest_url` instead of `supabase_url`/`anon_key` — the backend's own `POSTGRES_DSN` (full table access) is never constructed into or injected into any Kaggle payload.
- `postgres/schema.sql` (directory renamed from `supabase/` — no longer accurate once Supabase was dropped) — added `create extension if not exists pgcrypto;` (was missing; breaks `gen_random_uuid()`), folded `image_jobs.params jsonb not null default '{}'` directly into the table definition (previously only in a separate `add_image_jobs_params.sql` meant for manual apply via the Supabase SQL editor — with Postgres now self-bootstrapping via `docker-entrypoint-initdb.d`, that manual step had no automatic equivalent and the column would never have been created; **this was a CRITICAL bug caught by code review** before merge, now fixed and deleted the redundant file), added a `pawn_anon` Postgres role (NOLOGIN, idempotent `DO $$ ... $$` creation) with `GRANT usage/select/insert/update` on `image_sessions`/`image_jobs` only, and retargeted the existing RLS policies from Supabase's built-in `anon` role to `pawn_anon` — same permissive, single-user-trial posture as before (scoped per-session JWT remains a documented, deferred follow-up, unchanged decision from Phase W).
- New `postgres/init_pawn_anon.sh` — a `docker-entrypoint-initdb.d` shell script (runs after `schema.sql`) that sets `pawn_anon`'s password from the `postgrest_anon_password` Docker secret via `psql -v anon_pw=... <<-'EOSQL' ... :'anon_pw' ... EOSQL` (SQL-literal-quoted substitution, not shell/string interpolation — verified injection-safe) and grants LOGIN; a `.sql` init file can't read a secret file directly, hence the separate script.
- `docker-compose.yml` — new `postgres` service (`pgvector/pgvector:pg16`, healthcheck via `pg_isready`, named volume `pawn_postgres_data`, mounts `schema.sql`+`init_pawn_anon.sh` into `docker-entrypoint-initdb.d`, host port **5433** not 5432 — avoids colliding with a sibling local project's Postgres container, discovered live while testing) and `postgrest` service (`postgrest/postgrest:v12.2.3`, `PGRST_DB_URI: "@/run/secrets/postgrest_db_uri"`, `PGRST_DB_ANON_ROLE: pawn_anon`, no host port at all — internal only, reached over HTTPS via Nginx in D.7). `backend` now `depends_on: postgres: condition: service_healthy` and gets a new `POSTGREST_PUBLIC_URL` env var (blank locally — a remote Kaggle kernel can't reach a local dev machine either way, same limitation Supabase had).
- `backend/requirements.txt` — dropped `supabase`, added `psycopg[binary]>=3.1` and `pgvector>=0.3.0`.
- `secrets/` — dropped 3 Supabase `.example` files (and deleted the real, gitignored, now-unreferenced Supabase secret files), added `postgres_password`/`postgres_dsn`/`postgrest_anon_password`/`postgrest_db_uri` (`.example` templates + real generated values for local dev, mirroring how `encryption_secret`/`jwt_secret` were pre-generated in MA-1).
- 3 Kaggle session notebooks (`session_poc`, `image_flux_session`, `image_sdxl_session`) — payload field renamed `supabase_url`/`anon_key` → `postgrest_url`; `REST` now points directly at `POSTGREST_URL` (no `/rest/v1` prefix, unlike Supabase's gateway); `apikey`/`Authorization` headers dropped entirely — anonymous PostgREST requests get the `pawn_anon` role automatically via `PGRST_DB_ANON_ROLE`.
- Fixed an unrelated pre-existing bug found while testing: `frontend/.dockerignore` didn't exist, so the frontend's Docker build context (which is `./frontend`, not the repo root) pulled in the host's `frontend/node_modules` wholesale — a broken symlink there (`node_modules/.bin/why-is-node-running`) crashed BuildKit. Added `frontend/.dockerignore`.
- **148 backend tests green** — rewrote `conftest.py` (env vars), `test_rag.py`, `test_image_session.py`, `test_image_jobs.py`, `test_keys_kaggle.py` to mock the new `fetchone`/`fetchall`/`execute`/`transaction` functions instead of a chained Supabase-client fake (a simpler mock surface than before). `npm run build` clean (backend-only migration).
- **Live-verified beyond mocks:** brought up real `postgres`+`postgrest`+`backend`+`frontend` containers from an empty volume. Confirmed: schema + role-init scripts run cleanly; `pgvector`/`pgcrypto`/UUID/jsonb/timestamptz round-trips all work correctly through psycopg; `match_memory_chunks`/`search_memory_chunks` resolve with the `::vector`/`::int` casts; PostgREST connects and serves both anonymous **reads and writes** to `image_sessions` as `pawn_anon` (and correctly returns 401 on DELETE, matching its grants — least privilege confirmed working); backend `/health` and the frontend both respond. This live pass is *ahead of* D.6's dry-run requirement, not a replacement — D.6 still needs a full BYOK-key + memory-retrieval + real Kaggle-job pass before the D.7/D.8 live deploy.

### Plan: Drive-Mandatory Storage — Phase 1+2 (plan/plan_drive_mandatory.md) — 2026-07-03

Triggered by a passphrase-gate 500 from a Drive-scope gap; rather than patch just that route, Google Drive became the only storage backend for user data everywhere — no local-filesystem fallback anywhere in the app.

- `backend/app/core/drive_factory.py` — new `require_drive_for_user(user_id)` (raises `NotConfiguredError`, HTTP 412 `{"detail":...,"code":"not_configured"}`, when Drive isn't linked) and `call_drive(fn, *args)` (translates ANY failure inside a Drive operation — API error, insufficient OAuth scope, revoked/expired grant — into that same clear error, instead of an unhandled 500). Both reuse the existing `NotConfiguredError` pattern already used for "user must configure X" cases (e.g. missing Kaggle creds) — no new exception class needed.
- Removed every `if drive: ... else: local_storage...` branch: `routes/crypto.py` (dropped `_local_get_or_create_salt`/`_LOCAL_SALT_DIR`), `routes/conversations.py`, `routes/upload.py`, `routes/chat.py`, `memory/summarize.py`. Deleted the now-dead `backend/app/storage/conversations.py` and `backend/app/storage/documents.py`.
- `chat.py` only requires Drive when a request actually needs storage (`conversation_id` or `doc_id` present) — pure stateless chat (no persistence, no doc context) still works with no Drive link, since it never touches storage.
- Background tasks (`auto_title_background_task`, `summarize_conversation_task`) fail soft (log to stderr, return early) rather than raising — there's no HTTP response to attach a 412 to mid-background-task.
- New `backend/tests/fake_drive.py` — an in-memory `FakeDriveStorage` implementing DriveStorage's low-level primitives (`get_or_create_root`, `get_or_create_folder`, `find_file`, `upload_text`, `download_text(_by_name)`, `list_subfolders`, `delete_file`), so tests run the real `conversations_drive.py`/`documents_drive.py` logic against a fake in-memory tree. Rewrote `test_conversations.py`, `test_upload.py`, `test_summarize.py`, `test_rag.py`, `test_crypto.py` to patch `app.core.drive_factory.get_drive_for_user` (patching it at its defining module affects every route, since `require_drive_for_user` resolves it by bare name at call time). New tests cover the 412 not-configured path. `test_chat.py`/`test_agent.py` needed no changes.
- **Verified manually against the live stack** (full `docker compose up --build`), not the automated pytest suite this pass (skipped per user instruction) — confirmed: stateless chat unaffected, conversations/uploads/salt work when Drive is linked, and Drive-unavailable requests return the clear 412 instead of a 500.
- **Related fixes found during manual testing (not originally scoped):**
  - Removed the Phase 3 passphrase gate from the auth flow entirely (`App.tsx`'s `AuthGate` no longer wraps routes in `<PassphraseGate>`; deleted `frontend/src/pages/PassphraseGate.tsx`) — it unconditionally blocked the whole app after login, but the actual encrypt/decrypt-on-write wiring was deferred (see `implemented_phases/phase_8_encryption.md`), so it derived a key nothing downstream used. The crypto module (`frontend/src/crypto/*`) and backend `GET /crypto/salt` endpoint stay in the codebase, unused, ready for when encryption is properly wired up.
  - Renamed `supabase/` → `postgres/` (`schema.sql` + `init_pawn_anon.sh`) — the old name was actively misleading once Supabase was fully dropped in D.3/D.4. Updated `docker-compose.yml`'s two volume mounts and every remaining doc/docstring reference describing current (not historical) state. Verified live: a fresh Postgres volume still bootstraps correctly (pgcrypto extension, `pawn_anon` role with LOGIN, `image_jobs.params` column) from the renamed files.

### Mobile readiness (implemented_phases/phase_7_mobile_readiness.md) — 2026-07-03

- All 7 fixes applied: user bubble `max-w-[70%] sm:max-w-[50%]`; hamburger hit area `p-3.5 -m-2`; delete-confirm buttons `h-8 min-w-[48px] text-sm`; conversation search enabled (case-insensitive title filter + "No matching chats" state; mini-sidebar search button opens the drawer); trace row `flex-wrap gap-y-1`; code blocks `text-sm sm:text-xs`; settings colour swatches `w-8 h-8`.

### Phase 3 — P3-1 encryption foundation (implemented_phases/phase_8_encryption.md) — 2026-07-03

- `frontend/src/crypto/index.ts` — WebCrypto AES-256-GCM, PBKDF2-SHA256 600K, non-exportable key, encrypt/decrypt + base64/salt helpers.
- `frontend/src/crypto/session.ts` — per-tab key held in memory only (no storage); initSession/getKey/hasKey/clearSession.
- `frontend/src/pages/PassphraseGate.tsx` — gate after auth/before app; fetches salt, derives key. Wired in `App.tsx`. `AuthContext.logout()` clears the key. `client.ts` gains `fetchSalt()`.
- Backend `GET /crypto/salt` (`routes/crypto.py`, registered in `main.py`) — stores/returns the public PBKDF2 salt in `PAWN/.salt` on Drive (local fallback `<DATA_DIR>/salts/<user>.salt`), idempotent.
- Tests: 7 vitest crypto tests + backend `tests/test_crypto.py` (3). `tsc -b` + `vite build` clean. `vitest` added as devDep.
- DEFERRED: encrypting on every write / decrypting on every read — incompatible with current server-side LLM streaming, RAG, summarization, auto-titling (all read plaintext). Needs a product decision before wiring.

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
- [x] Real SDXL warm serve-loop (imageLab, Phase W / W.3) (load once via `AutoPipelineForText2Image` → serve loop → PNG, `via kaggle:sdxl-session`) instead of echo text; registry repointed to `image_sdxl_session` notebook (GPU, slug `pawn-sdxl-session`); 134 tests green (2026-06-29). Both SDXL + FLUX warm sessions are real now.
- [x] Session startup observability + liveness fixes + per-model panels (imageLab, Phase W / W.4–W.6) — Notebooks patch `installing`→`loading_model`→`ready` at phase boundaries; `_LIVE_STATUSES` extended; `SessionBar` shows phase-specific messages. Heartbeat stale threshold raised 30→90 s (fixes false "Session ended" during FLUX inference). `create_cold_job` blocks if a warm session is live (prevents GPU slot waste). Kaggle GPU limit surfaced as actionable message. Tab switcher replaced with always-mounted stacked `ModelPanel` components — each panel owns its own jobs poll, `SessionBar`, `ImageGenerator`, and `GenerationsPanel` (fixes session state loss on tab switch). Commit: 5728b9e.
- [x] Image generation parameter controls (imageLab, Plan 1 / IP-1–IP-4) — `image_jobs.params JSONB` column (migration: `supabase/add_image_jobs_params.sql`); `ImageJobParams` Pydantic model; `create_cold_job` + `submit_session_job` store params; style suffix applied on backend before storing; SDXL + FLUX warm-session notebooks read `params` from job row (steps/guidance/size/negative_prompt); `AdvancedParams` component in `ImageLabPage` (collapsible, checkbox-per-param: aspect ratio, inference steps, guidance scale, negative prompt, style preset); FLUX guidance-free note in UI; `runGenerate`/`submitSessionJob` in `client.ts` accept optional `params`. 136 backend tests green; npm run build clean.
- [x] Generations panel fixes (imageLab, Plan 1.0) — Fix 1: header shows `N running · M queued` split (amber running, muted queued). Fix 2: gen-time column: live elapsed ⏱ ticker (1 s tick via `setInterval`) for running jobs, fixed `Xm Ys` from `started_at→done_at` for done/error jobs; `started_at` added to `_JOB_LIST_COLUMNS` + `list_jobs` dict + `JobResult`. Fix 3: style preset pill from `params.style_preset` (inverted label map in panel). Fix 4: clipboard copy button per row (checkmark for 1.5 s). Fix 5 (backend): `reap_stale_jobs` now also fails **running** session jobs for heartbeat-stale/expired sessions (`_is_alive()` check extended to cover externally killed notebooks); `params` added to `_JOB_LIST_COLUMNS`. View + Download stacked vertically at far right of each row. 136 backend tests green; npm run build clean.
- [x] Image refinement / img2img (imageLab, Plan 2 / IR-1–IR-3) — `ImageJobParams` gains `strength` + `init_image_b64` fields; `GenerateRequest` + `SessionJobRequest` gain `init_image_b64` + `init_job_id`; `_resolve_init_image()` helper resolves direct upload or existing job (user-scoped); strength defaults to 0.6 when init image is provided. SDXL + FLUX warm-session notebooks add img2img branch: `AutoPipelineForImage2Image.from_pipe(pipe)` for SDXL, `FluxImg2ImgPipeline(**pipe.components)` for FLUX (reuses loaded weights, no extra load). Frontend: `ImageGenerator` converted to `forwardRef` exposing `triggerRefine`; `+ Add source image` upload button with chip preview; Refine button on each done image row in `GenerationsPanel`; Strength slider auto-appears in AdvancedParams when init image attached; `runGenerate` + `submitSessionJob` accept `initImageB64`. Each `ModelPanel` owns its own `GenerationsPanel` (with `onRefine`). Backend tests: 4 new tests covering direct b64, init_job_id resolution, missing job, and default strength. npm run build clean.
- [x] **Phase M — Memory scoping, code-complete (2026-07-13)**: standalone chats + projects each get strictly isolated RAG memory (schema/scoped-SQL, Drive `chats/`+`projects/` layout with automatic legacy migration, chunker+indexer write path, scoped `retrieve()` + agent wiring, `routes/projects.py` CRUD + two-way move, full projects UI with collapsible sidebar sections + 4 confirm dialogs + `/project/:projectId` routing, `routes/memory.py` rebuild/clear surfaced via kebab menus). Embedding model swapped `text-embedding-004` to `gemini-embedding-2` (768-dim, same schema) after finding the old model had been dead since 2026-01-14. 227 backend tests green, `tsc`/`npm run build` clean. **Live-verification checklist (real Drive-linked stack) still pending — not yet confirmed working end-to-end by the user.**
- [x] Phase 6 UI — URL-based routing + global dark mode toggle (imageLab, Phase 6). Migrated from boolean flag view-switching to `react-router-dom`. New files: `AppContext.tsx` (cross-route state: theme, models, prefs), `pages/Layout.tsx` (Sidebar + Outlet + global dark mode toggle), `pages/ChatPage.tsx` (chat logic extracted from AppContent), `pages/SettingsPageWrapper.tsx`, `pages/ImageLabPageWrapper.tsx`. `App.tsx` reduced to 44 lines. `Sidebar.tsx` uses `useNavigate`/`useLocation` internally. Dark mode toggle moved to Layout — now visible on every route (chat, imagelab, settings). tsc zero errors; npm run build clean.
- [x] Settings page layout update — Restructured settings page to 3 responsive vertical columns for desktop viewports. Refined responsiveness of BYOK API key inputs and vertical Kaggle input fields; grouped bubble color presets into horizontally scrollable carousels. tsc zero errors; npm run build clean.
- [x] Settings page layout polish & API keys row alignment — Reverted global theme toggle to a single animated micro-interaction button. Refactored Settings Page columns (Appearance & Defaults) to stack controls, preventing boundary overflow on narrow column sizes. Corrected sliding theme selector background alignment calculation in ThemeToggle.tsx to handle gaps. Made detailed theme switcher responsive (hiding labels and adjusting padding on medium columns/viewports). Refactored Profile card rows (Display Name, Email, Actions) to stack vertically to avoid overflow. Restructured ApiKeysSection.tsx cards into separate rows for Title, Description, Status (Configured badge and Remove button placed at opposite corners with flex-wrap justification), and Inputs, converting credentials guide descriptions to interactive helper icons that toggle info boxes when clicked/tapped. Reduced outer spacing and card paddings (p-4 to p-3, gap-6 to gap-4, px-6 to px-4) across the Settings page. tsc zero errors; npm run build clean.
- [x] imageLab cold-start + quality fixes (2026-07-05) — `kaggle_templates/image_sdxl/notebook.ipynb`'s warmup path (used by `/generate/connect`) skipped nothing and reinstalled pip deps on every "Connect" click (~1-2 min wasted); now short-circuits on `prompt == "warmup"` like FLUX's template already did. FLUX's session + cold notebooks dropped the blanket `pip install -U` (forced a full upgrade-resolve on every fresh ephemeral container) in favor of a `diffusers>=0.30.0` floor (the version that added `FluxPipeline`) with no forced upgrade otherwise. `AdvancedParams.tsx`'s inference-steps slider default is now model-aware (`initialAdvanced(modelId)`: 30 for SDXL matching its real notebook default, 4 for FLUX.1-schnell) instead of one flat `20` that undercut/overshot both. `npm run build` clean; no backend test assumed the old notebook cell contents. Orphaned Kaggle kernel `pawn-image-flux-1-schnell` cleanup still pending (needs the user's own Kaggle account, not reachable from this session).

---

### Phase M — M.1: memory-scoping schema + migration (2026-07-13)

- `postgres/schema.sql` — `memory_chunks` redefined (drop+recreate): `chunk_id uuid` (idempotency key), `scope_type`/`scope_id` (`'chat'`/conv_id or `'project'`/project_id — hard isolation boundary), `conv_id` (provenance), `kind`/`doc_id` (pre-provisioned for the follow-on `plan_chat_agent_refinement.md` document indexing, Phase M only writes `kind='message'`), `msg_index`, `unique(user_id, chunk_id)`. Old `match_memory_chunks`/`search_memory_chunks` (exclude-active-conv semantics) dropped; new `match_scoped_chunks`/`search_scoped_chunks` (strict equality on `scope_type`/`scope_id`, optional `match_kind` filter) added.
- New `postgres/migrations/2026-07_memory_scoping.sql` — same end state, for manual apply on an already-initialized volume (`schema.sql` only auto-runs on a fresh volume). Applied to local dev Postgres; live-verified via `\d memory_chunks` / `\df`.
- `backend/app/memory/index.py` — `add_chunk(user_id, scope_type, scope_id, conv_id, chunk_id, msg_index, text, embedding)`, upserts via `on conflict (user_id, chunk_id) do update`.
- `backend/tests/test_rag.py` — two `add_chunk` tests updated to the new signature + new `test_add_chunk_upserts_idempotently_on_chunk_id`. 165 backend tests green.
- **Known transitional gap (accepted, closes in M.3/M.4):** `memory/retrieve.py` still calls the now-dropped function names (fails soft → `[]`); `memory/summarize.py`'s `add_chunk` call site still uses the old 4-arg form (fails soft → TypeError caught). Both documented inline + in `dev_log.md`.

### Phase M — M.2: Drive storage layer, new chats/projects layout (2026-07-13)

- `backend/app/storage/drive.py` — new `move_item(item_id, new_parent_id, old_parent_id)` (single `files().update(addParents=..., removeParents=...)` call, lock-guarded, invalidates the folder/file-ID caches — mirrors `delete_file`'s cache-invalidation pattern).
- `backend/app/storage/conversations_drive.py` — retargeted from flat `PAWN/conversations/{conv_id}/` to `PAWN/conversations/chats/{conv_id}/`; new `_locate_conv_folder` finds a chat wherever its scope currently places it (chats/ or projects/{pid}/ — folder placement alone is the scope, no membership table); new `load_rag_chunks`/`append_rag_chunks` per-chat helpers (`rag_chunks.jsonl`, same full-file-rewrite pattern as `messages.jsonl`); automatic one-time legacy-folder migration (`PAWN/conversations/{conv_id}/` → `chats/{conv_id}/`, detected purely from folder layout — no flag file — logs each move to stderr).
- New `backend/app/storage/projects_drive.py` — full project CRUD (`create_project` idempotent on a client-generated id, `list_projects`, `get_project_meta`, `rename_project` json-only/no folder move, `delete_project` cascade via Drive's own recursive folder delete, `list_project_chats`) + `move_chat` (thin wrapper over `drive.move_item`, symmetric — used for both move-in and move-out).
- `backend/tests/fake_drive.py` gains `move_item`. New `backend/tests/test_projects_drive.py` (15 tests): new-chat-under-chats, migration + idempotency, project CRUD, cascade delete, move-in/move-out both directions (incl. a moved chat's writes still landing correctly, not silently recreating a stray folder), `rag_chunks.jsonl` roundtrip. 180 backend tests green.
- **Bug found + fixed during code review:** the legacy-migration "already checked" memo was originally a module-level `set` keyed by `id(drive)` — since `DriveStorage` instances are TTL-cached per user and evicted/GC'd, CPython can reuse a freed instance's memory address for a new object, which could silently skip a real user's migration forever (their old chats would just vanish from the chat list, no error). Fixed by storing the flag as an attribute directly on the `drive` instance (`getattr`/`setattr(drive, "_pawn_legacy_migration_checked", ...)`) instead.
- **Known limitation, accepted:** nothing calls `load_rag_chunks`/`append_rag_chunks`/`move_chat`/project CRUD yet outside tests — M.3 (chunker/indexer) and M.5 (projects API + move endpoints) are what actually wire these into request flow. M.2 is pure storage-layer plumbing.

### Phase M — M.3: chunker + write path, indexing every turn (2026-07-13)

- New `backend/app/memory/chunker.py` — `chunk_turn(turn_msgs, msg_index_start)` splits each message into fixed-size overlapping character chunks (`MEMORY_CHUNK_TOKENS=400`/`MEMORY_CHUNK_OVERLAP_TOKENS=50` in `app/constants.py`, token count approximated as `len(text)//4`); empty/whitespace-only messages produce no chunks.
- New `backend/app/memory/indexer.py`: `resolve_scope(user_id, conv_id, drive=None)` — resolves ('chat', conv_id) or ('project', project_id) via a new `conversations_drive.resolve_conv_scope` Drive-folder walk, cached in-process (thread-locked dict, `SCOPE_CACHE_TTL_SECONDS=300`), `evict_scope` exposed for M.5's moves. `index_turn_task(user_id, conv_id, scope, turn_msgs)` — background task scheduled from `chat.py`'s persist-turn block (same place `auto_title_background_task`/`summarize_conversation_task` are scheduled): chunks the turn, appends to the chat's own `rag_chunks.jsonl` on Drive **first**, then embeds each chunk and upserts into Postgres under the resolved scope. Drive write failure aborts before any Postgres write (no orphan index rows); a per-chunk embed failure is caught and skipped, not fatal. `rebuild_index(user_id, scope_type, scope_id)` deletes a scope's Postgres rows and re-derives them from Drive (walks every member chat for project scope).
- `backend/app/routes/chat.py` — schedules `index_turn_task` inside the existing `if req.conversation_id and success and user_msg_dict and assistant_text:` block; stateless chats (`conversation_id=None`) never reach it.
- `backend/app/routes/conversations.py` — `DELETE /conversations/{id}` now also deletes that chat's Postgres `memory_chunks` rows via new `_delete_chunks` (best-effort, logged not raised — closes a pre-existing gap where delete left Postgres untouched).
- `backend/app/memory/summarize.py` — the stale 4-arg `add_chunk` call (M.1's documented gap) now routes the rolling summary through `index_turn_task` instead.
- New `backend/tests/test_chunker.py`, `backend/tests/test_indexer.py`; +1 test in `test_conversations.py`. Covers: chunk-splitting incl. overlap boundaries; `resolve_scope` standalone/project/missing/cache-hit/cache-evict; `index_turn_task` via FakeDrive + mocked `embed`/`add_chunk` for chat scope, project scope, stateless no-op, Drive-unavailable no-op, **Drive-write-failure aborts before any Postgres write** (the core invariant), partial-embed-failure isolation; `rebuild_index` for both scopes; delete-cleans-chunks. 199 backend tests green (up from 180).
- **Bug found + fixed before code review (caught by the new tests):** `conversations_drive.resolve_conv_scope` initially returned a project chat's scope as `("project", <Drive's internal folder id>)` instead of `("project", <project_id>)` — project folders are named `<id>` only, so the logical project_id is the folder's `name`, not its Drive `id`. Fixed; both M.1/M.2's write-path transitional gaps are now closed.

### Phase M — M.4: retrieval rewrite + agent wiring (2026-07-13)

- `backend/app/memory/retrieve.py` — rewritten to `retrieve(query, user_id, scope_type, scope_id, top_k=MEMORY_TOP_K)` (`MEMORY_TOP_K=4` new in `app/constants.py`); queries `match_scoped_chunks`/`search_scoped_chunks` (strict `scope_type`/`scope_id` equality) instead of the dropped exclude-semantics functions; RRF fusion logic unchanged.
- `backend/app/agent/graph.py` — `load_context_node` is now a pure no-op (`return {}`), no longer auto-retrieving at graph start; `search_memory_node` is the sole retrieval call site, using the new scoped signature and guarded on `scope_type`/`scope_id` both being truthy (stateless chats never reach Postgres even if the agent picks `search_memory`); its `memory_hit` custom event now carries `scope`/`source_conv_id`. `AgentState` gains `scope_type`/`scope_id`. Agent prompt's `search_memory` action description reframed as an escape hatch, not a per-turn habit.
- `backend/app/routes/chat.py` — resolves scope once per request via M.3's `memory.indexer.resolve_scope(user_id, conv_id, drive)` (only when `conversation_id` present) and threads `scope_type`/`scope_id` into the graph inputs; the `memory_hit` SSE dispatch forwards `scope`/`source_conv_id`.
- `backend/app/events.py` — `memory_hit_event(summary, scope="", source_conv_id="")`, additive (only appears in the JSON payload when non-empty).
- Frontend: `types.ts`'s `TraceEvent` gains `scope`/`sourceConvId`; `client.ts`'s `onMemoryHit` callback threads them; `ChatPage.tsx` carries them into trace state; `Message.tsx` shows a badge only on `scope === 'project'` memory-hit cards, naming the source chat. `npm run build` clean.
- New/updated tests: `test_agent.py`'s `test_load_context_node_no_longer_retrieves` (asserts `retrieve`/`adispatch_custom_event` never called), `test_search_memory_node` (new signature + scope in the emitted event), new `test_search_memory_node_stateless_never_queries`. `test_rag.py`: all `retrieve()` calls updated to the scoped signature; new `test_retrieve_cross_scope_miss_isolation_guarantee` — **the core isolation test of this entire plan**; new `test_retrieve_project_scope_shared_across_member_chats`; `test_chat_yields_memory_hit_events` reworked into a scripted-mock full `/chat` round-trip (the agent must now choose to search, it's no longer automatic); new `test_stateless_chat_never_queries_memory`. 203 backend tests green (up from 199).
- code-reviewer PASS (0 CRITICAL, trivial NOTE fixed — stale `match_memory_chunks` reference in a `postgres_client.py` comment). Both the write path (M.3) and read path (M.4) of Phase M's memory scoping are now fully live.

### Phase M — M.5: projects backend API + two-way chat moves (2026-07-13)

- New `backend/app/routes/projects.py` (registered in `main.py`): `POST /projects` (client-generated id, idempotent), `GET /projects` (list + `chat_count`), `PATCH /projects/{id}` (rename), `DELETE /projects/{id}` (cascade — Drive folder + `memory_chunks` for that project scope), `POST`/`DELETE /projects/{id}/chats/{conv_id}` (move in / move out).
- Move semantics (both directions): Drive relocate (`storage.projects_drive.move_chat`) always **before** the Postgres `update memory_chunks set scope_type=..., scope_id=...`; `memory.indexer.evict_scope(user_id, conv_id)` called after, so the next `resolve_scope()` sees the new placement immediately, not a stale cache entry. Both idempotent (already-there/already-standalone short-circuits to 200, no mutation); moving into a second project while already in one is a 409, not silent corruption.
- New `backend/app/memory/locks.py` — `get_conv_lock(user_id, conv_id)`, a per-`(user, conv)` `asyncio.Lock` (module-level dict, mirrors `routes/generate.py`'s existing per-`(user,model)` lock). `memory/indexer.py`'s `index_turn_task` now holds this lock for its entire body; both move endpoints and cascade delete hold it too — an in-flight index write and a scope-mutating move/delete can never interleave.
- New `backend/tests/test_projects.py` (16 tests): CRUD, idempotent create, move-in/move-out both directions (Drive placement via `resolve_conv_scope` + exact Postgres SQL/params), idempotency, 409 conflict, 404s, cascade delete (Drive + PG), post-move-out scope-cache eviction, a moved chat's next `index_turn_task` call resolving to its current scope. 219 backend tests green (up from 203).
- **Bug found + fixed during code review:** `DELETE /projects/{id}`'s cascade delete originally took no lock at all — an in-flight `index_turn_task` write for a chat inside the project could land a Postgres row *after* the Drive folder (and that scope) was already gone, an orphan `rebuild_index` can never repair (nothing left on Drive to rebuild from). Fixed: cascade delete now lists every contained chat, acquires all their locks via `AsyncExitStack`, and holds them through both the Drive delete and the Postgres delete.
- security-auditor PASS (0 findings) — run proactively (this diff doesn't literally touch secrets/config/auth, but the plan's own M.7 guidance calls for it on new user-scoped route modules with destructive endpoints). Confirmed: every Drive operation is implicitly scoped to the caller's own Drive account (a raw project_id/conv_id from another user's account just 404s inside the caller's own tree — no code path accepts a raw Drive file ID from the client), every Postgres statement carries `user_id = %s`, all SQL parameterized. One pre-existing, out-of-diff informational note logged for later: `DriveStorage.find_file`'s query-string escaping uses Python `repr()` rather than proper Drive-query escaping (bounded blast radius, no cross-tenant risk).

### Phase M — embedding-model fix: swap dead text-embedding-004 → gemini-embedding-2 (2026-07-13)

- **Gap found while wrapping up M.6**: Google shut down `text-embedding-004` (2026-01-14) — every embed call in the running app had been failing (fail-soft, see below) since then, meaning any real usage during that window produced `memory_chunks` rows with no/broken embeddings, or (for the indexer's per-chunk try/except) simply skipped chunks silently.
- `backend/app/memory/embed.py`'s `_gemini_embed` now calls `gemini-embedding-2` (`outputDimensionality: 768` — a Google-recommended Matryoshka-truncated dimension that the model auto-normalizes; no manual normalization needed/added). `postgres/schema.sql`'s `memory_chunks.embedding vector(768)` column comment updated to match — **no schema/migration change**, the dimension itself (768) was already correct and unchanged.
- Registry: `text-embedding-004` model + its endpoint marked `active: false` (kept, not deleted, for history); new `gemini-embedding-2` model (type `embedding`, visibility `internal`) + its google endpoint added, both `active: true`.
- `backend/tests/test_registry.py` updated for two internal embedding entries (one deactivated, one active) instead of the old single-entry assertion. 226 backend tests green at this point (pre-M.6-test-addition count).
- **Known follow-up, deferred to M.7's live checklist (not the plan's original scope, but the same category of "needs the real stack"):** any real chat's `memory_chunks` rows written while the old model was dead need a `POST /memory/rebuild` per affected scope to re-embed them via `gemini-embedding-2` from the Drive `rag_chunks.jsonl` source of truth (Drive is authoritative — nothing was lost, just not yet indexed in Postgres).

### Phase M — M.6: frontend — projects UI + move flows (2026-07-13)

- `frontend/src/types.ts`/`api/client.ts`: `Project` type, `ConversationMeta.project_id?`; `SyncOp` union extended with exactly `'createProject' | 'renameProject' | 'deleteProject' | 'moveChat'` (plan-specified names); `getProjects`/`createProject`/`renameProject`/`deleteProject`/`moveChatToProject`/`removeChatFromProject`/`rebuildMemory`/`clearMemory` client helpers (no inline `fetch` elsewhere, per frontend.md).
- `useConversationStore.ts` remains the single owner — gains a `projects` list + the project/move mutators (optimistic, mirroring how conversations already work; no separate project store). `syncQueue.ts` gains the four new op kinds with the same optimistic/backoff/404-as-success behavior as existing ops; a `moveChat` targeting `projectId: null` (move-out) carries a `fromProjectId` resolved once at first-enqueue time (see the CRITICAL fix below). `conversationCache.ts` persists `projects` alongside conversations; a pre-Phase-M cache with no `projects` field is treated as "none yet," not corrupt.
- New `components/ProjectSection.tsx` (collapsible Projects block) / `ProjectRow.tsx` (one project + its expandable chat list) — split out of `Sidebar.tsx` per frontend.md's 150-line rule. New shared `components/KebabMenu.tsx` (one-level submenu dropdown, used by both chat and project rows) and `components/ConfirmDialog.tsx` (shared blocking modal).
- Four blocking confirm dialogs in `Sidebar.tsx`: add-to-project, remove-from-project, delete-project (lists every contained chat), and clear-memory (added during review — see below). Standalone chat kebab gains an "Add to project ▸" submenu; every chat/project kebab gains a "Memory ▸" submenu (Clear memory / Rebuild memory index) — surfaced there, **not in Settings**, per the plan.
- New routes `/project/:projectId` (`pages/ProjectPage.tsx` — name header, chat list, new-chat-in-project) and `/project/:projectId/chat/:id`; `ChatPage.tsx` keeps both the URL and the store's resolved scope in sync in both directions (selecting a chat from the sidebar routes correctly; a chat whose scope changes mid-session re-routes without a jarring reload).
- New backend `routes/memory.py` (registered in `main.py`): `POST /memory/rebuild` (calls M.3's `rebuild_index`), `POST /memory/clear` (wipes both the scope's Postgres `memory_chunks` rows and the Drive `rag_chunks.jsonl` file(s) — both layers, so a clear can't resurrect via a later rebuild). Both 404 on an unknown scope, 400 on an invalid `scope_type`. `routes/conversations.py`'s `GET /conversations` now calls a new `conversations_drive.list_all_conversations` so the sidebar can render every chat (standalone + project-scoped) with its `project_id` in one round trip instead of one call per project.
- **New-chat-in-project deviation from the plan's literal wording (documented in code):** the plan describes a draft "born in project scope, no move needed," but M.5 never added a dedicated create-inside-project endpoint (only move in/out on an existing chat) — implemented instead as the existing lazy-create draft flow followed by an immediate `moveChat` op, which is behaviorally equivalent (the sidebar shows it under the right project immediately; the backend call sequence is create-then-move rather than a single call).
- Gate: `tsc --noEmit` zero errors, `npm run build` clean, 227 backend tests green (`docker compose exec backend pytest`, `test_memory_routes.py` (7 new) + 1 new test in `test_conversations.py` for the tagged-list-endpoint change).
- **code-reviewer (via build-step skill) found and this pass fixed:**
  - **CRITICAL:** `syncQueue.ts`'s `moveChat` coalescing recomputed `fromProjectId` from the store's live ref on *every* re-enqueue for the same conv, not just the first — since the ref reflects the op's own already-applied optimistic update, a second rapid remove-from-project (double-click, or a re-render landing between two enqueue calls) would read the project as already-cleared (`null`) and overwrite the correct, previously-captured source project id. The queued op would then silently no-op at drain time (`run()`'s both-falsy branch), so the UI showed "removed from project" while the backend never received the `DELETE /projects/{id}/chats/{conv_id}` call — a real isolation leak (the project's siblings would keep retrieving from a chat the UI claimed was no longer shared). Fixed: `fromProjectId` is now captured once, only when a queue entry is first created, and preserved across coalesced re-enqueues.
  - **WARN:** the plan's M.6 text says "Clear memory" gets a confirm dialog (same as the other three destructive-ish flows), but the first pass wired it directly to the kebab click with no gate — a single misclick inside a hover-revealed menu would irreversibly wipe a scope's indexed memory. Fixed: added the fourth `ConfirmDialog` (destructive-styled) alongside the other three.
  - **NOTE (deferred, low severity, out of this step's scope):** `conversations_drive.py`'s pre-existing `except (json.JSONDecodeError, Exception): pass` pattern (several call sites) swallows any error, not just parse errors — relied on by `memory.py`'s new 404 resolution, so a transient Drive error there would look identical to "not found." `memory.py`'s own Postgres delete (`_delete_scope_chunks`) has no try/except, unlike `conversations.py`'s sibling `_delete_chunks` pattern for the same class of derived-index cleanup. Both noted for a future pass, not fixed here (out of M.6's stated scope, and low severity — a rebuildable index, not user data loss).
- No security-auditor run (same call as M.4 — no secrets/config/auth touched).

### Phase M — M.7: tests, review, live-verify checklist (2026-07-13, automatable parts only)

- Full backend suite green (227 tests), frontend `tsc`/`npm run build` clean, code-reviewer run via build-step skill on the M.6 diff (see above). No security-auditor needed for the same reason as M.4/M.5/M.6.
- **The plan's live-verification checklist (§M.7 items 1-8) was run 2026-07-14** via `claude-in-chrome` against the real Drive-linked stack — see `gap_audit_2026-07-14.md` §§J/K/L and `build_tracker.md`'s M.7 entry. M.7 marked `[x]`.

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

- ~~Free-tier Ampere instance retry loop~~ — **RESOLVED 2026-07-04/05.** Succeeded on attempt 183 (`2026-07-04T17:54:11Z`); the new `pawn` instance (`144.24.119.184`) was provisioned and prod fully migrated onto it 2026-07-05. `pawn-temp` (the paid bridge) has been terminated — no more Universal Credits billing risk. See `dev_log.md` 2026-07-05 entry for the full migration record.
- ~~Permissive `pawn_anon` RLS on `image_sessions`/`image_jobs`~~ — **FIXED 2026-07-04.** `/pgrst/` was a public, unauthenticated endpoint where any caller (no PAWN account needed) could read/write any user's session or job rows. Closed by wiring up the existing (previously inert) `session_token` — the Kaggle kernel now sends it as an `X-Session-Token` header on every PostgREST call, and RLS policies on both tables require it to match before permitting SELECT/UPDATE. Applied to `postgres/schema.sql`, both warm-session notebook templates, and live-migrated onto `pawn-temp`'s running Postgres. Verified: no/wrong token → `[]` (nothing leaked), correct token → only that session's own rows; user manually confirmed a real session-start + generation still works end-to-end. This was the blocker for ever flipping the OAuth consent screen from Testing to public — now clear on that front (see `plan_deployment.md`/`build_tracker.md` for any other pre-public checklist items).
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
- **imageLab:** `machineShape: NvidiaTeslaT4` always provisions a **2× T4 (2×16 GB)** box — treated as a hard rule (the FLUX A.1 plan shards across both cards). The earlier note that dual-T4 was "unreachable" (issue #821) is retired. First Generate after a deploy holds the HTTP request open through the warmup wait (per-user lock already serializes this).
- ~~imageLab FLUX perf (top deferred item)~~ — **RE-SCOPED 2026-07-05.** The old "~820s/image, no optimization chosen" framing predates Phase W and is stale: `ImageGenerator.tsx`'s `handleGenerate` already auto-starts (or reuses) a warm session on every Generate click, so the slow cold-start (pip install + dataset mount + model load) is a one-time cost per session (30-120 min, user-chosen), not a per-image cost — repeat images in a session are fast. Fixed two real, still-live inefficiencies in that one-time cost: (1) FLUX's session + cold notebooks ran `pip install -U` unconditionally on every fresh container, forcing a full upgrade-resolve even when Kaggle's base image already ships a compatible version — replaced with a `diffusers>=0.30.0` floor (the version that added `FluxPipeline`) and no forced upgrade on `transformers`/`accelerate`/etc.; (2) SDXL's `/generate/connect` "warmup" (just verifies the Kaggle connection) was still running the full pip-install cell every time — `generate.py`'s own comment already flagged this — now skips it like FLUX's template already did. Remaining candidate (pre-baked deps in the Kaggle dataset image itself, cutting cold-start further) is real but unstarted — would need packaging a second Kaggle dataset with preinstalled wheels.
- ~~SDXL image quality not yet tuned~~ — **CHECKED 2026-07-05.** The warm-session notebook's actual generation defaults (30 steps, guidance 7.5, 1024×1024) already match standard SDXL recommendations — nothing to fix there. The real bug was upstream: `AdvancedParams.tsx`'s inference-steps slider had one flat default (20) shared across models regardless of which model was selected, undercutting SDXL's own 30-step default and overshooting FLUX.1-schnell's 4-step one if a user enabled the slider without moving it. Fixed via `initialAdvanced(modelId)` — SDXL now defaults to 30, FLUX to 4.
- **imageLab orphan kernel:** the old mismatched FLUX title created a stray `pawn-image-flux-1-schnell` notebook on Kaggle (now unused — title is derived from the slug). Safe to delete manually. Not deleted 2026-07-05 — needs the user's own Kaggle account access (BYOK credentials aren't reachable/decryptable from outside the running app).
- ~~Phase M live verification pending~~ — **DONE 2026-07-14.** M.7's checklist (legacy-tree migration, cross-chat isolation, cross-project sharing, add/remove-from-project retrieval transitions, cascade delete, manual-truncate + rebuild) run against the real Drive-linked stack via `claude-in-chrome`. See `gap_audit_2026-07-14.md` §L and `build_tracker.md`'s M.7 entry.
- ~~Embedding gap re-index needed~~ — **DONE 2026-07-14**, folded into the M.7 truncate+rebuild drill above: `memory_chunks` fully truncated and rebuilt per scope via the real UI, all restored chunks have healthy `gemini-embedding-2` embeddings.
- **Two low-severity code-review NOTEs deferred from M.6** (not fixed, judged out of scope/low-severity): `conversations_drive.py`'s `except (json.JSONDecodeError, Exception): pass` pattern (several call sites, pre-existing) swallows any error, not just parse errors — a transient Drive error would look identical to "not found" to `memory.py`'s new 404 checks. `memory.py`'s `_delete_scope_chunks` has no try/except unlike the sibling `_delete_chunks` pattern in `conversations.py` for the same class of derived-index cleanup.
- ~~imageLab warm sessions unusable from local dev~~ — **FIXED 2026-07-14.**
  `POSTGREST_PUBLIC_URL` has been blank in dev since the D.3/D.4 Supabase→
  self-hosted-Postgres migration (a real regression — Supabase's URL was
  always public, self-hosted PostgREST isn't). Fixed with a dev-only,
  profile-gated `cloudflared` tunnel service (`docker compose --profile
  tunnel up -d cloudflared`) + `docker-compose.override.yml.example`. Also
  fixed: the UI silently swallowed session start/extend/stop errors instead
  of showing them; `image_sessions.stop_requested_at` (added to schema.sql
  by `472a170`, 2026-07-05) had no migration for already-initialized
  volumes, added one and applied it locally — **check if prod's volume
  needs the same migration.** Full record: `workspace/plan/
  plan_imagelab_session_issues.md`'s 2026-07-14 section.
- **imageLab production notebook auto-fail — diagnosed, not fixed
  (2026-07-14):** the notebook silently loses its own error/heartbeat
  reports when PostgREST rejects a write — `patch_session()`/`patch_job()`
  in both warm-session notebook templates never check the HTTP response
  (`.raise_for_status()` only exists on the two read functions). Deliberately
  not fixed yet (user instruction: don't touch prod-affecting code outside a
  real deployment session). Fix sketch in `plan_imagelab_session_issues.md`.

---

## Agents to Update This File

After every completed step, update:
1. "Last updated" date
2. "Active step" to the next step
3. Add new items to "What's Built"
4. Check off items in "What's Working"
5. Add any deferred issues
