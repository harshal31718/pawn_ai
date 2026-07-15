# Phase G1 — Generations Tab: Delete, Edit, Reorder Queue

**Status:** PLANNED (not started). **Branch:** `dev`. **Folder:** `workspace/plan/imageLab/`
**Date:** 2026-07-15. **Requested by user**, feature (not quality) — sits alongside the
Q-phases, not inside them.

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

## 3. Design decisions (flag for user confirmation before building)

1. **Reorder mechanism:** add a nullable `queue_pos double precision` column to `image_jobs`.
   Dequeue query becomes `order=queue_pos.asc.nullslast,created_at.asc` (untouched rows keep
   FIFO-by-created_at behavior). A reorder action recomputes `queue_pos` for **every** queued
   job in that session (spaced integers, e.g. 1000/2000/3000...) in one backend call — simpler
   and safer than per-move fractional-index math for queues this small (typically single
   digits).
2. **Reorder UI:** recommend **up/down arrow buttons** on queued rows (swap with neighbor),
   not drag-and-drop — frontend rules disallow new UI libraries, and hand-rolled HTML5
   drag/drop is meaningfully more code/risk for a queue that's rarely more than a handful of
   items. Drag-and-drop can be a follow-up if the user wants it after using arrows.
3. **Queued-section display:** to make "rearrange" visually meaningful, propose splitting
   the panel into two blocks: a small **"Queue"** block at the top (queued jobs only, sorted
   by dequeue order ascending — i.e. next-up first — with the reorder arrows), and the
   existing **history list** below (running/done/error, newest-first, unchanged). Without
   this split, queued rows stay interleaved newest-first, and up/down arrows would silently
   change dequeue order without a visible position change — confusing. **Needs explicit
   user sign-off** — it's the one part of this plan that changes existing panel layout, not
   just adds icons.
4. **Delete confirmation:** reuse the existing `ConfirmDialog` component (already used in
   `Sidebar.tsx` for delete-project/delete-chat) rather than `window.confirm()` — one
   shared dialog instance in `GenerationsPanel`, opened with the target job id.
5. **Edit UI:** inline — clicking the edit icon turns line 1's prompt `<span>` into a text
   input pre-filled with the current **raw user prompt** (never the suffixed one), with
   Save/Cancel (Enter/Escape). Scope is **prompt text only** this pass (not params/style/
   aspect) per the user's literal ask; params editing can be a later follow-up if wanted.
6. **Raw prompt storage:** add a nullable `user_prompt text` column to `image_jobs`. Both
   creation call sites store the trimmed, un-suffixed `req.prompt` into `user_prompt` in the
   same insert that writes the suffixed string into `prompt` (unchanged — `prompt` stays the
   model-facing value the Kaggle kernel/cold-job worker actually sends, so generation behavior
   doesn't change). Every place the UI shows/copies/edits/carries-forward a prompt reads
   `user_prompt`, falling back to `prompt` only for rows created before this migration (best
   effort — old rows can't be losslessly un-suffixed). `edit_job_prompt` (§4) writes the new
   text to `user_prompt` **and** recomputes `prompt` = new text + style suffix (from the job's
   own stored `params.style_preset`, if any) so the dequeued job still generates with the
   suffix intact.
7. **Settings icon + popover:** a small gear icon appears on a row only when that job's
   `params` has at least one of `width`/`height` (aspect ratio), `num_inference_steps`,
   `guidance_scale`, `negative_prompt`, `style_preset`, `strength` set (i.e. non-default —
   `init_image_b64` doesn't count here, it drives the separate input-image tag in §8). Clicking
   opens a small popover/tooltip (reuse the existing lightbox-style click-outside-to-close
   pattern, no new UI library) listing each set value with a human label (aspect ratio via the
   existing `RATIO_TO_SIZE` reverse lookup, style preset via the existing
   `STYLE_PRESET_LABEL_MAP`, others as plain "Steps: 30" / "Guidance: 7.5" / "Negative: ..." /
   "Strength: 0.60" lines). Read-only — this is a viewer, not an editor.
8. **Input-image tag:** when `job.params?.init_image_b64` is present, render a small tag on
   the row (e.g. "🖼 input image" — mirrors the `🖼`/`↺` labeling already used in
   `ImageGenerator.tsx`'s init-image chip) so it's visible after the fact that a job was
   img2img. No thumbnail of the *source* image is needed — the row's own thumbnail already
   shows the *output*; this tag is just a badge, not another image fetch.
9. **Refine pre-apply mechanism:** `AdvancedParams` gains a way to be seeded with existing
   values. Cheapest approach given its current all-internal-state design: add an
   `initial?: ImageParams` prop, add a small inverse helper `advancedFromParams(modelId,
   p: ImageParams): AdvancedState` (mirrors `deriveParams`'s field mapping in reverse,
   including the aspect-ratio width/height → `RATIO_TO_SIZE` key lookup and the style-preset
   key→label lookup already used for the settings popover in §7), and initialize
   `useState(() => initial ? advancedFromParams(modelId, initial) : initialAdvanced(modelId))`.
   `ImageGenerator.tsx`'s `triggerRefine` sets a new `refineParams` state alongside `initImage`
   and passes it as `AdvancedParams`'s `initial` prop, force-remounting `AdvancedParams` with a
   `key` (e.g. keyed on the refined job's id) since its state only seeds on mount. `triggerRefine`
   also opens the Advanced panel (`setIsAdvancedOpen(true)`) so the pre-applied settings are
   visible immediately, not hidden behind the collapsed `+ Advanced` toggle.

## 4. Backend changes

**Files:** `postgres/migrations/2026-07_image_jobs_queue_pos.sql` (new),
`postgres/migrations/2026-07_image_jobs_user_prompt.sql` (new),
`backend/app/core/image_session.py`, `backend/app/routes/generate.py`, both warm-session
notebooks (`image_flux_session`, `image_sdxl_session`), tests.

1. **Migrations:**
   - `alter table image_jobs add column if not exists queue_pos double precision;`
     + `create index if not exists image_jobs_queue_pos_idx on image_jobs (session_id, queue_pos);`
   - `alter table image_jobs add column if not exists user_prompt text;` — nullable, so
     existing rows are unaffected; `_JOB_LIST_COLUMNS` and the single-job fetch both add
     `user_prompt` to their select list.
2. **`image_session.py`:**
   - `create_cold_job`/`submit_session_job` gain a `user_prompt: str` param (the raw,
     un-suffixed text) written alongside the existing (suffixed) `prompt` at insert time.
     `routes/generate.py` passes `req.prompt.strip()` for this before it appends
     `STYLE_SUFFIXES`.
   - `delete_job(user_id, job_id) -> bool` — `delete from image_jobs where id=%s and
     user_id=%s and status != 'running' returning id`. Returns `False` (→ 409) if 0 rows
     (either not found, not owned, or currently running).
   - `edit_job_prompt(user_id, job_id, prompt) -> bool` — fetches the job's current
     `params.style_preset` first, then `update image_jobs set user_prompt=%s, prompt=%s where
     id=%s and user_id=%s and status='queued' returning id`, where the new `prompt` value is
     `new_text + STYLE_SUFFIXES.get(style_preset, "")` (re-suffixed so the Kaggle dequeue still
     generates with the style applied). `False` (→ 409) if the job already started between the
     user opening the editor and hitting Save.
   - `reorder_queue(user_id, session_id, job_ids: list[str]) -> bool` — validates every id
     in `job_ids` belongs to `user_id` + `session_id` + `status='queued'` (reject if any
     mismatch/missing — stale client state), then in one transaction sets
     `queue_pos = 1000 * (index+1)` per the given order.
3. **`routes/generate.py`:**
   - `DELETE /generate/job/{job_id}` → `delete_job`; 404/409 domain exception (per
     `exceptions.py` convention, registered handler — no bare try/except in the route) if it
     returns `False`.
   - `PATCH /generate/job/{job_id}` (body: `{prompt: str}`) → `edit_job_prompt`; same
     404/409 handling. The body field is the raw user text (frontend never sends the suffix).
   - `POST /generate/jobs/reorder` (body: `{session_id: str, job_ids: list[str]}`) →
     `reorder_queue`; 409 on any validation failure.
   - Both existing job-creation branches (`generate_artifact`, `session_job`) pass the
     pre-suffix `req.prompt.strip()` through as `user_prompt` to the creation calls above.
4. **Notebooks:** `next_job()`'s `order` param in both `image_flux_session` and
   `image_sdxl_session` templates changes from `"created_at.asc"` to
   `"queue_pos.asc.nullslast,created_at.asc"` — one-line change, re-verify with the
   existing template JSON/compile tests.

**Tests:** new `tests/test_generate_job_management.py` — delete (queued/done/error succeed,
running rejected, wrong-user rejected), edit (queued succeeds, non-queued rejected, edit on a
job with a style preset re-suffixes `prompt` while `user_prompt` stays raw), reorder (happy
path re-sequences correctly, rejects a job_id from another session/user/status). Extend
existing job-creation tests to assert `user_prompt` is stored raw while `prompt` carries the
suffix when a style preset is set. Existing `test_kaggle_session_templates.py` covers the
notebook one-liner via its compile-cleanliness assertions — extend it with a grep for
`queue_pos.asc` in both session templates.

## 5. Frontend changes

**Files:** `frontend/src/api/client.ts`, `frontend/src/components/GenerationsPanel.tsx`,
`frontend/src/components/AdvancedParams.tsx`, `frontend/src/components/ImageGenerator.tsx`,
`frontend/src/types.ts`, tests.

1. **`client.ts`:** `deleteJob(jobId)`, `editJobPrompt(jobId, prompt)`,
   `reorderQueue(sessionId, jobIds)` — same `postJson`/fetch pattern as the existing job
   functions; surface backend 409s as thrown errors the panel can catch and show inline.
2. **`types.ts`:** `JobResult` gains `queue_pos?: number | null` and `user_prompt?: string |
   null`.
3. **`GenerationsPanel.tsx` (`JobRow`):**
   - Everywhere the row currently reads `job.prompt` for **display, copy, or the lightbox
     alt/caption**, switch to `job.user_prompt ?? job.prompt` (fallback covers pre-migration
     rows only) per design decision §3.8/ask #8 — this replaces the existing `handleCopy`
     (`navigator.clipboard.writeText(job.prompt ?? '')`) and the `onView(src, job.prompt ...)`
     call.
   - Replace the current single top-right copy button with a **3-icon action row** (copy,
     edit, delete — icons only, no text, existing copy-check animation preserved), rendered
     conditionally per status per §1.4 above (running: copy only; queued: all three; done/
     error: copy + delete). Delete is always last/rightmost in the row.
   - Delete icon → opens the shared `ConfirmDialog` ("Delete this generation?" /
     "Remove from queue?" copy varies by status) → `deleteJob` → optimistic removal from the
     local `jobs` list (parent already re-polls; no need to wait for the next poll tick).
   - Edit icon (queued only) → swaps the prompt `<span>` for an `<input>` pre-filled with
     `job.user_prompt ?? job.prompt`, Save/Cancel buttons appear in place of the icon row;
     Save calls `editJobPrompt` with the raw text; on 409 show a small inline "already
     started" message and revert to read-only.
   - Up/down reorder arrows on queued rows only (per design decision §3.2/3.3 — gated on
     the layout split being approved).
   - **Settings icon** (§3.7/ask #5): a small gear button next to the existing style-preset
     pill, shown when the job's `params` has any of `width`/`height`/`num_inference_steps`/
     `guidance_scale`/`negative_prompt`/`style_preset`/`strength` set. Click toggles a small
     popover (click-outside closes it, same pattern as the existing lightbox) listing each
     set value with a human label.
   - **Input-image tag** (§3.8/ask #7): when `job.params?.init_image_b64` is present, render
     a small "🖼 input image" tag on line 1 or line 2 next to the status chip.
4. If §3.3's queue/history split is approved: extract a `QueueSection` (queued jobs,
   ascending `queue_pos`/`created_at`, arrows) rendered above the existing history list in
   `GenerationsPanel`'s return; otherwise, arrows go directly on queued rows in the existing
   single newest-first list.
5. **`AdvancedParams.tsx`** (§3.9/ask #6): add an `initial?: ImageParams` prop and an
   `advancedFromParams(modelId, p: ImageParams): AdvancedState` inverse-mapping helper
   (mirrors `deriveParams` in reverse); seed `useState` from it when `initial` is provided.
6. **`ImageGenerator.tsx`** (§3.9/ask #6): `triggerRefine` — currently only sets `initImage`,
   clears `prompt`, and clears `error` — additionally captures the source job's `params` into
   a new `refineParams` state, passes it to `AdvancedParams` as `initial` (remounted via a
   `key` on the refined job id so the seed takes effect), and calls `setIsAdvancedOpen(true)`
   so the pre-applied settings are visible without an extra click.

**Tests:** `GenerationsPanel.test.tsx` (new or extended) — icon visibility per status,
delete confirm flow, edit save/cancel (pre-filled with `user_prompt`, not the suffixed
`prompt`), reorder arrow calls, settings-icon visibility/popover content, input-image tag
visibility. `AdvancedParams.test.tsx` / `ImageGenerator.test.tsx` — refine pre-applies a
source job's params into the Advanced panel and opens it. Mock `client.ts` per project
convention.

## 6. Gates

- Backend: new + full suite green (`docker compose exec backend pytest -n auto`).
- Frontend: `tsc --noEmit` + `npm run build` clean; component tests green.
- Cross-stack gate applies here (new routes + request/response shapes) — both stacks' gates
  required per `testing.md`.
- Manual live check (real Kaggle warm session): queue 3 jobs, reorder so #3 runs first,
  confirm it actually generates first; edit a queued prompt, confirm the generated image
  matches the edited text not the original; delete a queued job, confirm it never runs;
  attempt delete on a running job, confirm no delete icon is shown; generate a job with a
  style preset set, confirm the row shows only the raw text (no suffix keywords) while the
  settings popover shows the style preset chosen; run an img2img job, confirm the input-image
  tag appears; click Refine on a job that had non-default settings, confirm the Advanced panel
  opens pre-filled with those exact settings.

## 7. Open questions for the user before building

1. Approve or reject the **Queue/History split** layout (§3.3) — this is the only part that
   changes existing panel structure rather than purely adding controls.
2. Up/down arrows acceptable for v1, or is drag-and-drop a hard requirement?
3. Is prompt-only edit sufficient for v1, or does "edit queued prompt" need to reach params
   (aspect ratio/steps/style) too?
4. Settings popover (§3.7): is a click-to-open popover the right interaction, or would the
   user prefer the settings always visible inline (more row height, no click needed)?
5. Old rows created before the `user_prompt` migration will fall back to displaying the
   suffixed `prompt` (can't be losslessly split back into raw text + suffix) — acceptable, or
   should those rows get a best-effort strip of any matching `STYLE_SUFFIXES` string as a
   one-time backfill?
