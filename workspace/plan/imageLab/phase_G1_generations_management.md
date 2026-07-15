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
   input pre-filled with the current prompt, with Save/Cancel (Enter/Escape). Scope is
   **prompt text only** this pass (not params/style/aspect) per the user's literal ask;
   params editing can be a later follow-up if wanted.

## 4. Backend changes

**Files:** `postgres/migrations/2026-07_image_jobs_queue_pos.sql` (new),
`backend/app/core/image_session.py`, `backend/app/routes/generate.py`, both warm-session
notebooks (`image_flux_session`, `image_sdxl_session`), tests.

1. **Migration:** `alter table image_jobs add column if not exists queue_pos double precision;`
   + `create index if not exists image_jobs_queue_pos_idx on image_jobs (session_id, queue_pos);`
2. **`image_session.py`:**
   - `delete_job(user_id, job_id) -> bool` — `delete from image_jobs where id=%s and
     user_id=%s and status != 'running' returning id`. Returns `False` (→ 409) if 0 rows
     (either not found, not owned, or currently running).
   - `edit_job_prompt(user_id, job_id, prompt) -> bool` — `update image_jobs set prompt=%s
     where id=%s and user_id=%s and status='queued' returning id`. `False` (→ 409) if the
     job already started between the user opening the editor and hitting Save.
   - `reorder_queue(user_id, session_id, job_ids: list[str]) -> bool` — validates every id
     in `job_ids` belongs to `user_id` + `session_id` + `status='queued'` (reject if any
     mismatch/missing — stale client state), then in one transaction sets
     `queue_pos = 1000 * (index+1)` per the given order.
3. **`routes/generate.py`:**
   - `DELETE /generate/job/{job_id}` → `delete_job`; 404/409 domain exception (per
     `exceptions.py` convention, registered handler — no bare try/except in the route) if it
     returns `False`.
   - `PATCH /generate/job/{job_id}` (body: `{prompt: str}`) → `edit_job_prompt`; same
     404/409 handling.
   - `POST /generate/jobs/reorder` (body: `{session_id: str, job_ids: list[str]}`) →
     `reorder_queue`; 409 on any validation failure.
4. **Notebooks:** `next_job()`'s `order` param in both `image_flux_session` and
   `image_sdxl_session` templates changes from `"created_at.asc"` to
   `"queue_pos.asc.nullslast,created_at.asc"` — one-line change, re-verify with the
   existing template JSON/compile tests.

**Tests:** new `tests/test_generate_job_management.py` — delete (queued/done/error succeed,
running rejected, wrong-user rejected), edit (queued succeeds, non-queued rejected), reorder
(happy path re-sequences correctly, rejects a job_id from another session/user/status).
Existing `test_kaggle_session_templates.py` covers the notebook one-liner via its
compile-cleanliness assertions — extend it with a grep for `queue_pos.asc` in both
session templates.

## 5. Frontend changes

**Files:** `frontend/src/api/client.ts`, `frontend/src/components/GenerationsPanel.tsx`,
`frontend/src/types.ts`, tests.

1. **`client.ts`:** `deleteJob(jobId)`, `editJobPrompt(jobId, prompt)`,
   `reorderQueue(sessionId, jobIds)` — same `postJson`/fetch pattern as the existing job
   functions; surface backend 409s as thrown errors the panel can catch and show inline.
2. **`types.ts`:** `JobResult` gains `queue_pos?: number | null`.
3. **`GenerationsPanel.tsx` (`JobRow`):**
   - Replace the current single top-right copy button with a **3-icon action row** (copy,
     edit, delete — icons only, no text, existing copy-check animation preserved), rendered
     conditionally per status per §1.4 above (running: copy only; queued: all three; done/
     error: copy + delete). Delete is always last/rightmost in the row.
   - Delete icon → opens the shared `ConfirmDialog` ("Delete this generation?" /
     "Remove from queue?" copy varies by status) → `deleteJob` → optimistic removal from the
     local `jobs` list (parent already re-polls; no need to wait for the next poll tick).
   - Edit icon (queued only) → swaps the prompt `<span>` for an `<input>`, Save/Cancel
     buttons appear in place of the icon row; Save calls `editJobPrompt`; on 409 show a
     small inline "already started" message and revert to read-only.
   - Up/down reorder arrows on queued rows only (per design decision §3.2/3.3 — gated on
     the layout split being approved).
4. If §3.3's queue/history split is approved: extract a `QueueSection` (queued jobs,
   ascending `queue_pos`/`created_at`, arrows) rendered above the existing history list in
   `GenerationsPanel`'s return; otherwise, arrows go directly on queued rows in the existing
   single newest-first list.

**Tests:** `GenerationsPanel.test.tsx` (new or extended) — icon visibility per status,
delete confirm flow, edit save/cancel, reorder arrow calls. Mock `client.ts` per project
convention.

## 6. Gates

- Backend: new + full suite green (`docker compose exec backend pytest -n auto`).
- Frontend: `tsc --noEmit` + `npm run build` clean; component tests green.
- Cross-stack gate applies here (new routes + request/response shapes) — both stacks' gates
  required per `testing.md`.
- Manual live check (real Kaggle warm session): queue 3 jobs, reorder so #3 runs first,
  confirm it actually generates first; edit a queued prompt, confirm the generated image
  matches the edited text not the original; delete a queued job, confirm it never runs;
  attempt delete on a running job, confirm no delete icon is shown.

## 7. Open questions for the user before building

1. Approve or reject the **Queue/History split** layout (§3.3) — this is the only part that
   changes existing panel structure rather than purely adding controls.
2. Up/down arrows acceptable for v1, or is drag-and-drop a hard requirement?
3. Is prompt-only edit sufficient for v1, or does "edit queued prompt" need to reach params
   (aspect ratio/steps/style) too?
