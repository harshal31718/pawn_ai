# Phase G1 — Generations Tab: Delete, Edit, Reorder Queue

**Status:** IN PROGRESS — design finalized 2026-07-17 (see §3/§7), build starting.
**Branch:** `dev`. **Folder:** `workspace/plan/imageLab/`
**Date:** 2026-07-15 (open questions resolved 2026-07-17). **Requested by user**, feature (not
quality) — sits alongside the Q-phases, not inside them.

## 1. Ask (verbatim, structured)

In the Generations tab / panel:
1. **Delete** a generation entry:
   - `done` / `error` rows → delete the row entirely (history entry gone).
   - `queued` rows → remove from the queue (never runs).
   - `running` rows → **no delete option** (can't interrupt an in-flight Kaggle job safely).
2. **Edit** a queued prompt (change the text before it's picked up).
3. **Rearrange** queued prompts (change which one runs next).
4. Icon row on the far right of each job row: **copy prompt, delete, edit** — delete is
   always the rightmost icon. Per status:
   - `queued`: copy, edit, delete (edit not rightmost, delete stays rightmost — so order is
     **copy, edit, delete** left→right)
   - `running`: **copy only** — no edit, no delete icon shown at all (not just disabled)
   - `done` / `error`: copy, delete (no edit — nothing to edit on a finished job)
5. **Settings icon**: if a job was generated with any additional setting (aspect ratio,
   steps, guidance scale, negative prompt, style preset, strength), show a small gear/settings
   icon on the row. Clicking it reveals which additional settings were chosen (read-only).
   No icon at all when the job used pure defaults (nothing to show).
6. **Refine pre-applies settings**: clicking **Refine** on a job must carry that job's
   additional settings into the compose panel's Advanced Settings, pre-filled and pre-enabled,
   not just the source image — today Refine only seeds the init image and clears the prompt;
   the settings the original job used are silently dropped.
7. **Input-image indicator**: if a job was created with a source/init image (upload or
   refine-from-job), show that on the row/tab — e.g. a small "🖼 input image attached" tag —
   so it's visible after the fact which generations were img2img vs. text-to-image.
8. **Prompt = user text only**: everywhere a prompt is displayed, copied, or made editable
   (row line 1, copy button, edit-in-place, lightbox caption, Refine's carried-over prompt),
   it must be exactly what the user typed — never the style-preset suffix keywords
   (`STYLE_SUFFIXES` in `routes/generate.py`) that get appended for the model call today.

## 2. Current state (read first)

- `frontend/src/components/GenerationsPanel.tsx` — `JobRow` already has an inline **copy**
  button (top-right of line 1, clipboard icon) and a far-right vertical stack with
  **Download**/**Refine** (done+image jobs only). No delete, no edit, no reorder anywhere.
- `backend/app/routes/generate.py` — `GET /generate/jobs`, `GET /generate/job/{id}` exist.
  **No DELETE, no PATCH, no reorder route.**
- `backend/app/core/image_session.py` — jobs live in Postgres `image_jobs`; the **Kaggle
  kernel itself** dequeues via PostgREST directly (`next_job()` in both warm-session
  notebooks): `GET .../image_jobs?session_id=eq.X&status=eq.queued&order=created_at.asc&limit=1`.
  **Queue order is FIFO by `created_at` — there is no position/priority column today.**
  This is the load-bearing fact for the reorder feature: reordering means changing what the
  *Kaggle kernel* will pick up next, not just a frontend sort.
- `postgres/schema.sql` `image_jobs` columns: `id, user_id, session_id, model, prompt,
  status, image_b64, mime, via, error, params jsonb, created_at, started_at, done_at`. No
  delete grant needed for `pawn_anon` (Kaggle kernel only ever `select`/`insert`/`update`s
  its own session's rows via RLS) — **delete only ever happens through the backend**, using
  the same Postgres role the rest of the backend uses (not PostgREST/RLS), so no RLS policy
  changes are needed for this phase.
- `_resolve_init_image()` (routes/generate.py) copies a source job's `image_b64` into the
  *new* job at creation time — it does not keep a live reference. **Deleting a `done` job
  later never breaks an already-created refine job that used it as a source.** No cascade/FK
  concern.
- **Prompt is already stored suffix-baked-in.** Both `generate_artifact` (line ~142) and
  `session_job` (line ~223) do `prompt = req.prompt.strip(); if params.style_preset: prompt +=
  STYLE_SUFFIXES[...]` **before** calling `create_cold_job`/`submit_session_job` — the `prompt`
  column in `image_jobs` is the model-facing string (raw text + suffix), not the user's literal
  input. There is currently no column that preserves the raw text separately. This is the root
  cause of ask #8 and is a real (small) backend change, not just a frontend display tweak.
- **`params` jsonb already carries every "additional setting".** `ImageJobParams` (width,
  height, num_inference_steps, guidance_scale, negative_prompt, style_preset, strength,
  init_image_b64) is stored via `Json(params.model_dump(exclude_none=True))` at both job-creation
  call sites, and `_JOB_LIST_COLUMNS` already includes `params` in the `GET /generate/jobs` list
  response (`GenerationsPanel.tsx` already reads `job.params?.style_preset` today for the style
  pill). **No backend/schema change needed to detect "has additional settings" or "has an init
  image" — it's already on the wire.** The only backend gap is the raw-prompt column above.
- `AdvancedParams.tsx` keeps its Advanced-Settings state (`AdvancedState`) as internal
  `useState(() => initialAdvanced(modelId))` — there is currently no way for a parent to seed it
  with existing values. `deriveParams(s: AdvancedState): ImageParams` (one-way) exists; the
  inverse (`ImageParams` → `AdvancedState`) does not. This is the gap ask #6 (Refine pre-apply)
  needs to close.
- `ImageGenerator.tsx`'s `triggerRefine` (the `useImperativeHandle` exposed to
  `GenerationsPanel`/`ImageLabPage`) currently only sets `initImage` (preview + jobId +
  label) and clears the prompt — it never touches `advParams`/`AdvancedParams`, so a refine
  today silently drops whatever settings the source job used.

## 3. Design decisions (confirmed with the user 2026-07-17 — final, supersedes the original
proposals below where they conflict)

1. **Reorder mechanism:** add a nullable `queue_pos double precision` column to `image_jobs`.
   Dequeue query becomes `order=queue_pos.asc.nullslast,created_at.asc` (untouched rows keep
   FIFO-by-created_at behavior). A reorder action recomputes `queue_pos` for **every** queued
   job in that session (spaced integers, e.g. 1000/2000/3000...) in one backend call — simpler
   and safer than per-move fractional-index math for queues this small (typically single
   digits). **Confirmed**, unchanged from the original proposal.
2. **Reorder UI:** **up/down arrow buttons** on queued rows, confirmed — no drag-and-drop.
3. **No queue/history split.** User rejected the two-block layout — stays a **single table**.
   Confirmed sort: **queued jobs first (newest-request at top, oldest-queued at bottom) →
   running (if any) → done/error**, all in one list, one status-priority sort replacing the
   current pure `created_at desc`. Within the queued group, "bottom" is next to execute
   (lowest `queue_pos`/oldest `created_at`) — this is why "bottom executes first" reads
   naturally without a separate section. Arrow semantics: a queued row's up/down arrows swap
   its `queue_pos` priority with its **nearest queued neighbor** (skipping over any
   running/done/error rows that may be interleaved by raw `created_at` before the new sort is
   applied — in practice this won't happen since queued rows are now grouped together by the
   status-priority sort, but the reorder logic operates on the queued subset regardless of
   what's rendered between them). Moving a row DOWN moves it closer to executing sooner;
   moving UP delays it.
4. **Delete confirmation:** reuse the existing `ConfirmDialog` component (already used in
   `Sidebar.tsx` for delete-project/delete-chat) rather than `window.confirm()` — one
   shared dialog instance in `GenerationsPanel`, opened with the target job id.
5. **Edit is delete-and-reload, not inline-edit — and reaches full params, not just
   prompt text.** User rejected the original inline-text-input design. Clicking the edit
   icon on a queued row: (a) immediately deletes that job (`deleteJob`, same call the delete
   icon uses), (b) loads its prompt + full `params` into the composer/Advanced panel via the
   **same prefill mechanism built for Refine** (§9 below), minus the source-image attach step
   (edit never carries an image — a queued job has no output yet). The user edits anything —
   prompt, aspect ratio, steps, style, etc. — in the normal composer UI, and the next click on
   Generate creates a brand-new job, which naturally lands at the back of the queue (fresh
   `created_at`, no `queue_pos` set). **No `PATCH /generate/job/{id}` route is needed** — this
   removes an entire backend endpoint from the original plan (§4/§5 below updated accordingly).
   Risk accepted: if the user opens edit and navigates away without regenerating, that job is
   gone (matches the user's explicit choice — "remove it from table" on click, not on submit).
6. **Raw-prompt display reuses the existing `original_prompt` column (Q3.1 pass 2) — no new
   `user_prompt` column.** `original_prompt` is currently only set when the vision-enhancer
   actually ran (`_apply_prompt_enhancement`, `routes/generate.py`); it does NOT capture the
   pre-suffix raw text when enhancement is off/skipped but a style/subject-type suffix still
   gets appended — in that case `prompt` itself is silently mutated with the suffix baked in
   and nothing preserves the original. **Fix:** in both `generate_artifact` and `session_job`,
   capture the pre-suffix text into a local `raw_prompt` variable right after
   `_apply_prompt_enhancement` returns (this already equals the true user-typed text whether or
   not enhancement ran), and pass it through to `create_cold_job`/`submit_session_job` as
   `original_prompt` **whenever it differs from the final (suffixed) `prompt`** — i.e. broaden
   the existing "only set when something actually changed" contract from "enhancement changed
   it" to "enhancement and/or suffix composition changed it." Every place the UI
   shows/copies/carries-forward a prompt reads `job.original_prompt ?? job.prompt` (already
   true today in `GenerationsPanel.tsx`/`ImageGenerator.tsx` from Q3.1 pass 2 — no frontend
   change needed for this specifically). Old rows predating this broadened logic fall back to
   the suffixed `prompt` — **accepted as-is, no backfill** (user confirmed).
7. **Settings icon + popover:** confirmed — click-to-open popover (not always-inline). A small
   gear icon appears on a row only when that job's `params` has at least one of
   `width`/`height` (aspect ratio), `num_inference_steps`, `guidance_scale`, `negative_prompt`,
   `style_preset`, `strength` set (i.e. non-default — `init_image_b64` doesn't count here, it
   drives the separate input-image tag in §8). Clicking opens a small popover (reuse the
   existing lightbox-style click-outside-to-close pattern, no new UI library) listing each set
   value with a human label (aspect ratio via the existing `RATIO_TO_SIZE` reverse lookup,
   style preset via `image_presets`'s label, others as plain "Steps: 30" / "Guidance: 7.5" /
   "Negative: ..." / "Strength: 0.60" lines). Read-only — this is a viewer, not an editor.
8. **Input-image tag:** when `job.params?.init_image_b64` is present, render a small tag on
   the row (e.g. "🖼 input image" — mirrors the `🖼`/`↺` labeling already used in
   `ImageGenerator.tsx`'s init-image chip) so it's visible after the fact that a job was
   img2img. No thumbnail of the *source* image is needed — the row's own thumbnail already
   shows the *output*; this tag is just a badge, not another image fetch.
9. **Refine + Edit share one pre-apply mechanism.** `AdvancedParams` gains a way to be seeded
   with existing values. Cheapest approach given its current all-internal-state design: add an
   `initial?: ImageParams` prop, add a small inverse helper `advancedFromParams(modelId,
   p: ImageParams): AdvancedState` (mirrors `deriveParams`'s field mapping in reverse,
   including the aspect-ratio width/height → `RATIO_TO_SIZE` key lookup and the style-preset
   key→label lookup already used for the settings popover in §7), and initialize
   `useState(() => initial ? advancedFromParams(modelId, initial) : initialAdvanced(modelId))`.
   `ImageGenerator.tsx` gets a new `triggerEdit(job)` imperative handle (alongside the existing
   `triggerRefine`) that sets `refineParams` from `job.params`, prefills the prompt input from
   `job.original_prompt ?? job.prompt`, opens the Advanced panel, but does **not** set
   `initImage` (no source image carried) — `triggerRefine` keeps setting `initImage` as today.
   Both remount `AdvancedParams` via a `key` (e.g. keyed on the job id) since its state only
   seeds on mount.

## 4. Backend changes

**Files:** `postgres/migrations/2026-07_image_jobs_queue_pos.sql` (new),
`backend/app/core/image_session.py`, `backend/app/routes/generate.py`, both warm-session
notebooks (`image_flux_session`, `image_sdxl_session`), tests. **No `user_prompt` column, no
`PATCH` route** — superseded by design decisions §6/§5 above (reuse `original_prompt`,
edit = delete + reload into composer).

1. **Migration:**
   - `alter table image_jobs add column if not exists queue_pos double precision;`
     + `create index if not exists image_jobs_queue_pos_idx on image_jobs (session_id, queue_pos);`
2. **`routes/generate.py`:** in both `generate_artifact` and `session_job`, after
   `_apply_prompt_enhancement()` returns and before the style/subject-suffix `prompt +=` lines,
   capture the pre-suffix value (`raw_prompt = prompt`). After suffix composition, pass
   `original_prompt=original_prompt or (raw_prompt if raw_prompt != prompt else None)` to
   `create_cold_job`/`submit_session_job` — i.e. keep the enhancer's `original_prompt` if it
   ran, otherwise fall back to the pre-suffix text only when a suffix actually changed
   `prompt`. This is a small extension of the existing `_apply_prompt_enhancement` call sites,
   not a new mechanism.
3. **`image_session.py`:**
   - `delete_job(user_id, job_id) -> bool` — `delete from image_jobs where id=%s and
     user_id=%s and status != 'running' returning id`. Returns `False` (→ 409) if 0 rows
     (either not found, not owned, or currently running).
   - `reorder_queue(user_id, session_id, job_ids: list[str]) -> bool` — validates every id
     in `job_ids` belongs to `user_id` + `session_id` + `status='queued'` (reject if any
     mismatch/missing — stale client state), then in one transaction sets
     `queue_pos = 1000 * (index+1)` per the given order.
4. **`routes/generate.py` new routes:**
   - `DELETE /generate/job/{job_id}` → `delete_job`; 404/409 domain exception (per
     `exceptions.py` convention, registered handler — no bare try/except in the route) if it
     returns `False`.
   - `POST /generate/jobs/reorder` (body: `{session_id: str, job_ids: list[str]}`) →
     `reorder_queue`; 409 on any validation failure.
5. **Notebooks:** `next_job()`'s `order` param in both `image_flux_session` and
   `image_sdxl_session` templates changes from `"created_at.asc"` to
   `"queue_pos.asc.nullslast,created_at.asc"` — one-line change, re-verify with the
   existing template JSON/compile tests.

**Tests:** new `tests/test_generate_job_management.py` — delete (queued/done/error succeed,
running rejected, wrong-user rejected), reorder (happy path re-sequences correctly, rejects a
job_id from another session/user/status). Extend existing job-creation tests to assert
`original_prompt` is set when a suffix (not just enhancement) changes the stored `prompt`, and
stays `None` when neither runs. Existing `test_kaggle_session_templates.py` covers the
notebook one-liner via its compile-cleanliness assertions — extend it with a grep for
`queue_pos.asc` in both session templates.

## 5. Frontend changes

**Files:** `frontend/src/api/client.ts`, `frontend/src/components/GenerationsPanel.tsx`,
`frontend/src/components/AdvancedParams.tsx`, `frontend/src/components/ImageGenerator.tsx`,
`frontend/src/types.ts`, tests.

1. **`client.ts`:** `deleteJob(jobId)`, `reorderQueue(sessionId, jobIds)` — same
   `postJson`/fetch pattern as the existing job functions; surface backend 409s as thrown
   errors the panel can catch and show inline. No `editJobPrompt` — edit never calls the
   backend directly (delete + reuse the composer instead).
2. **`types.ts`:** `JobResult` gains `queue_pos?: number | null` (`original_prompt`/
   `enhanced_prompt` already exist from Q3.1 pass 2).
3. **`GenerationsPanel.tsx` (`JobRow`):**
   - Prompt display/copy/lightbox already read `job.original_prompt ?? job.prompt` (shipped
     in Q3.1 pass 2) — no change needed here beyond the backend broadening in §4.2 above making
     that fallback correct for suffix-only jobs too.
   - Sort: replace the current pure `created_at desc` list sort with a status-priority sort —
     queued (newest-request-first among themselves, i.e. `created_at desc`, but ordered so the
     oldest-queued/lowest-`queue_pos` job renders last within the queued group) → running →
     done/error (`created_at desc`, unchanged). One comparator change in the list-building code,
     no new section/component.
   - Replace the current single top-right copy button with a **3-icon action row** (copy,
     edit, delete — icons only, no text, existing copy-check animation preserved), rendered
     conditionally per status per §1.4 above (running: copy only; queued: all three; done/
     error: copy + delete). Delete is always last/rightmost in the row.
   - Delete icon → opens the shared `ConfirmDialog` ("Delete this generation?" /
     "Remove from queue?" copy varies by status) → `deleteJob` → optimistic removal from the
     local `jobs` list (parent already re-polls; no need to wait for the next poll tick).
   - Edit icon (queued only) → immediately calls `deleteJob` (same as the delete icon), then
     calls the new `triggerEdit(job)` imperative handle on `ImageGenerator` (§5.6 below) to
     load the job's prompt + params into the composer. No inline input, no Save/Cancel state —
     the composer IS the editor.
   - Up/down reorder arrows on queued rows only — call `reorderQueue` with the recomputed
     queued-job-id order; optimistic reorder of the local list, revert on error.
   - **Settings icon** (§3.7/ask #5): a small gear button next to the existing style-preset
     pill, shown when the job's `params` has any of `width`/`height`/`num_inference_steps`/
     `guidance_scale`/`negative_prompt`/`style_preset`/`strength` set. Click toggles a small
     popover (click-outside closes it, same pattern as the existing lightbox) listing each
     set value with a human label.
   - **Input-image tag** (§3.8/ask #7): when `job.params?.init_image_b64` is present, render
     a small "🖼 input image" tag on line 1 or line 2 next to the status chip.
4. Single list, no new section — the sort-comparator change (§5.3 above) groups queued rows
   together (newest-request-first, oldest-queued last) ahead of running/done/error; arrows
   operate directly on queued rows in that same list.
5. **`AdvancedParams.tsx`** (§3.9/ask #6): add an `initial?: ImageParams` prop and an
   `advancedFromParams(modelId, p: ImageParams): AdvancedState` inverse-mapping helper
   (mirrors `deriveParams` in reverse); seed `useState` from it when `initial` is provided.
6. **`ImageGenerator.tsx`** (§3.9): `triggerRefine` — currently only sets `initImage`, clears
   `prompt`, and clears `error` — additionally captures the source job's `params` into a new
   `refineParams` state, passes it to `AdvancedParams` as `initial` (remounted via a `key` on
   the refined job's id so the seed takes effect), and calls `setIsAdvancedOpen(true)` so the
   pre-applied settings are visible without an extra click. New `triggerEdit(job)` does the same
   `refineParams`/`AdvancedParams`-seeding/`setIsAdvancedOpen(true)` work and also sets
   `prompt` from `job.original_prompt ?? job.prompt`, but does **not** touch `initImage` (edit
   never carries a source image).

**Tests:** `GenerationsPanel.test.tsx` (new or extended) — icon visibility per status, delete
confirm flow, edit click → delete-then-triggerEdit call sequence, reorder arrow calls
(including the "move to bottom = sooner" direction), settings-icon visibility/popover content,
input-image tag visibility, sort-order grouping (queued-then-running-then-done/error).
`AdvancedParams.test.tsx` / `ImageGenerator.test.tsx` — refine pre-applies a source job's
params + image into the Advanced panel and opens it; edit pre-applies params + prompt but NOT
an image. Mock `client.ts` per project convention.

## 6. Gates

- Backend: new + full suite green (`docker compose exec backend pytest -n auto`).
- Frontend: `tsc --noEmit` + `npm run build` clean; component tests green.
- Cross-stack gate applies here (new routes + request/response shapes) — both stacks' gates
  required per `testing.md`.
- Manual live check (real Kaggle warm session): queue 3 jobs, use the down arrow to move the
  3rd to the front, confirm it actually generates first; click edit on a queued job, confirm
  it's removed from the table and the composer is pre-filled with its prompt+params, generate
  again and confirm the new job lands at the back of the queue; delete a queued job, confirm it
  never runs; attempt delete on a running job, confirm no delete icon is shown; generate a job
  with a style preset set (no enhancer), confirm the row shows only the raw text (no suffix
  keywords) while the settings popover shows the style preset chosen; run an img2img job,
  confirm the input-image tag appears; click Refine on a job that had non-default settings,
  confirm the Advanced panel opens pre-filled with those exact settings plus the source image.

## 7. Open questions — resolved 2026-07-17

1. ~~Queue/History split~~ — **rejected**, single table, status-priority sort instead (§3.3).
2. ~~Arrows vs. drag-and-drop~~ — **arrows**, confirmed (§3.2).
3. ~~Prompt-only vs. full-params edit~~ — **full params, but via delete-and-reload into the
   composer, not inline editing** (§3.5) — broader scope than originally proposed, but less
   new backend surface (no `PATCH` route at all).
4. ~~Popover vs. always-inline settings~~ — **popover**, confirmed (§3.7).
5. ~~Old-row fallback~~ — **accept as-is, no backfill** (§3.6) — moot anyway now that this
   reuses the existing `original_prompt` column rather than a new migration-gated one.
