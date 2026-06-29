# Plan v5 — Warm/Persistent Kaggle Image Sessions + Unified Job Tracking (Image Lab)

**Branch:** `imageLab` · merges back to `dev` (per project convention).
**Scope (user-confirmed):** Supabase job-queue rendezvous · time + image-cap session limit · Image Lab only (no chat-composer wiring yet).

Two intertwined goals, served by **one** mechanism (durable, server-tracked **jobs**):
1. **Warm sessions** — keep one Kaggle container alive so repeat images are fast (the `idea.md` ask).
2. **Fix the double-submit / lost-result bug** — every generation becomes a durable job the UI tracks from the server, with a **Generations monitor panel**, so a refresh/tab-switch never loses a result or re-enables the button for a duplicate run.

> Builds directly on Milestone A.1 (multi-model SDXL/FLUX live). Targets the top deferred item:
> FLUX ~820 s/image. See `plan_v4_kaggle_image.md` for the A.0/A.1 history this extends.

---

## Context — why this is being built

FLUX (and SDXL) image generation works end-to-end today, but the top deferred item is speed:
**~820 s per FLUX image**. The cause is architectural, not the model — Kaggle's Kernels REST API
is **batch-only**. Every `POST /generate` pushes a fresh kernel version, so Kaggle spins a
**brand-new container** and re-pays the three dominant costs *every single image*:

1. `pip install` deps (~30–60 s)
2. mount the **34 GB** model dataset
3. load the **12 B** model onto the 2× T4 cards (~minutes)

…then runs the 4-step inference, which is actually **fast** (~5–10 s). You can't read a running
kernel's output via the API, so today the only way to get the PNG is to let the whole container
die and fetch `out.png` — paying the full cold start each time.

`idea.md` identifies the only lever that removes the dominant costs: **keep one container alive**.
Load the model once, then serve many prompts fast, on a user-chosen timer. Quote:

> *"most of time is taken by loading model … ask user at first how many images / compile time,
> make sure that notebook is running till that time … next images will be generated faster …
> if stopped and still want to generate, ask to set new timer … or extend the timer … we might
> need a way to close the notebook."*

This is the existing v4 plan's deferred **"Architecture 2"** (live/warm kernel), now made concrete
with a rendezvous that fits PAWN's stack. **Intended outcome:** first image in a session still pays
the ~10 min warm-up, but every image after that returns in **seconds**, with a user-controlled
session timer + image cap, an **Extend** control, and a **Stop** control — all proven in the
isolated Image Lab before it ever touches chat.

### Also fixing: the double-submit / lost-result bug (user-reported, with screenshots)
Today a generate is an **in-flight HTTP request held open for minutes**, whose result lives *only*
in that request's promise + ephemeral React state (`ImageGenerator` in `ImageLabPage.tsx`). So:
- **Refresh or switch tab → the promise is abandoned.** The component remounts with `status='idle'`,
  so the **Generate button is clickable again** → the user fires a **duplicate** run.
- **The completed result is never shown** — even though the Kaggle run finished successfully (the
  user's screenshots show `Pawn Image Sdxl … Successful` / `Pawn Image Flux … Running` in the Kaggle
  events panel while PAWN's UI sits idle with a fresh button).

The backend behaviour is already correct — the per-`(user,model)` lock runs same-model requests
**serially** and different models **in parallel** (visible in those Kaggle events). The gap is purely
that the **frontend has no durable, server-backed view of in-flight/finished generations**. The fix
is the same job layer the warm session needs: **make every generation a durable `image_jobs` row**,
poll it by id, derive button state from the server (not React), and surface everything in a
**Generations monitor panel**. One mechanism fixes the bug *and* powers the warm-session multi-image
flow.

---

## The core problem & the chosen design

A running Kaggle kernel is unreachable through Kaggle's API (no output/logs until it exits). So a
warm kernel needs an **out-of-band channel**. We use **Supabase as a job queue** (PAWN already runs
Supabase live; both PAWN's backend and the Kaggle container can reach it over the internet, so this
works even on localhost dev — no tunnel, no inbound ports).

```
Image Lab ──Start session──▶ POST /generate/session/start
                                   │  (creates image_sessions row + pushes persistent notebook, non-blocking)
                                   ▼
        Kaggle persistent kernel (user's account, 2× T4)
          1. pip install + mount dataset + load model ONCE  (the slow ~10 min)
          2. PATCH session.status='ready' + heartbeat
          3. loop until timer/cap/stop:
               - GET pending job for this session  (Supabase REST / PostgREST)
               - generate (fast, model warm) → PATCH job.status='done', image_b64=<png>
               - PATCH heartbeat each iteration
                                   ▲                         │
        PAWN ── submit prompt ─────┘                         │
        (POST /generate/session/job → poll job → render) ◀───┘
```

Per-image latency after warm-up = inference (~seconds) + one Supabase poll interval (~3 s). The
slow model load happens **once per session**, not once per image.

### Unified job model — every generation is a durable `image_jobs` row
Both generation paths produce the **same** durable job record, so one polling API + one monitor
panel covers everything and the lost-result bug disappears:

| Path | Who runs it | Who writes the result row | When used |
|---|---|---|---|
| **Cold one-shot** | PAWN backend (existing `generate.generate_image` round-trip, now run as a **background task**) | the **backend** (after `kaggle.run_kernel` returns) | no warm session active — a single quick image |
| **Warm session** | the live Kaggle kernel | the **kernel** (PATCHes its own row over Supabase REST) | a warm session is live — fast repeat images |

`POST /generate` (image) stops blocking: it **creates a `queued` job row, returns `{job_id}`
immediately**, and runs the Kaggle round-trip in a fire-and-forget backend task under the existing
per-`(user,model)` lock (so same-model jobs still serialize, different models still parallelize —
exactly today's correct backend behaviour, now *observable*). The frontend polls
`GET /generate/job/{id}` and lists `GET /generate/jobs` — identical shape for cold and warm jobs.
Because state lives in Supabase keyed by `user_id`, a **refresh re-attaches** to in-flight jobs,
finished results **persist**, and the Generate button is **disabled whenever that model already has a
`queued`/`running` job** (server-derived → survives refresh → no duplicate submit). The cube POC
path stays blocking (dev-only, fast).

### Session lifecycle (matches idea.md exactly)
- **Start** → pick duration (30/60/120 min) **and** optional max-image cap → kernel boots, loads, serves.
- **Generate** → insert a job row, poll for the result PNG.
- **Extend** → bump `expires_at`; the kernel reads it each loop and extends its own deadline (bounded by Kaggle's max run time).
- **Stop / close** → set `status='stopping'`; the kernel sees it next loop and exits cleanly (Kaggle has **no hard batch-cancel API**, so stop is cooperative; the internal timer is the hard backstop).
- **Ended (timer/cap/dead)** → UI shows "session ended — start a new one?" (re-push pays the load cost again).

### Security decision (baked in, not asked)
**Never inject Supabase's master `service_key` into a third-party notebook.** PAWN mints a
**per-session, scoped credential** (a short-lived Supabase JWT carrying a `session_id` claim) and
injects *that* + the public **anon key**. RLS policies on the two new tables scope all kernel access
to its own `session_id`. The exact RLS/JWT wiring is the **schema-spike deliverable** of Milestone
W.1 (documented trial fallback: anon-key-open on the two dedicated tables only — acceptable for a
single-user trial, but the scoped JWT is the recommended path for the multi-user app). PAWN's
backend keeps using the service key server-side (bypasses RLS) — unchanged.

---

## Milestones (each provable before the next — mirrors the cube→image strategy that worked)

### W.0 — Prove the persistent-loop assumption (CPU, no model) ⚠️ do this first
The load-bearing risk is *"can a batch-pushed Kaggle kernel run a long-lived internet loop for tens
of minutes?"* De-risk it with the cheapest possible payload, exactly like the cube POC de-risked the
transport:
- A **CPU** persistent notebook (`kaggle_templates/session_poc/`) that loads payload `{session_id,
  supabase_url, anon_key, session_jwt, expires_at, poll_interval}`, PATCHes `status='ready'`, then
  loops: heartbeat + echo any pending job's `prompt` straight into `image_b64` (no model), honoring
  stop/timer.
- Backend: minimal `start_session` + `submit_session_job` + `get_job` against Supabase; push via the
  existing `kaggle.deploy_kernel` (non-blocking single push — already does exactly this).
- **Done =** Start a session in the Lab, submit a "job", watch the kernel pick it up from Supabase,
  echo it back, heartbeat for several minutes, and exit on Stop/expiry. This proves the warm-loop +
  Supabase rendezvous with zero GPU/model variables.

### W.1 — Warm session backend + FLUX persistent notebook + unified job tracking
Swap the echo loop for the real model; build the full session manager + routes + schema. **Also
retrofit the cold one-shot path** to be a durable background job (`POST /generate` → `{job_id}`),
and add `GET /generate/job/{id}` + `GET /generate/jobs`. This is where the lost-result bug is fixed
at the backend.

### W.2 — Image Lab UI (session controls + Generations monitor panel)
Duration/cap picker, live countdown + heartbeat status, generate-within-session, Extend, Stop,
"session ended" re-start prompt. **Plus the Generations monitor panel** (all jobs across models with
status + thumbnails + view/download), **server-derived button state** (disabled while that model has
an active job → fixes the double-submit bug), and re-attach-on-refresh. Cold one-shot Generate stays
as a labelled fallback, now also job-tracked.

---

## Backend changes

### Supabase schema — add to existing `supabase/schema.sql`
```sql
create table if not exists image_sessions (
  id uuid primary key default gen_random_uuid(),
  user_id text not null,
  model text not null,                       -- 'sdxl' | 'flux'
  session_token text not null,               -- random secret the kernel presents
  status text not null default 'starting',   -- starting | ready | stopping | ended | error
  expires_at timestamptz not null,           -- the timer; kernel exits past this
  max_images int,                            -- optional cap (null = time-only)
  images_done int not null default 0,
  heartbeat_at timestamptz,                  -- kernel updates each loop → liveness
  error text,
  created_at timestamptz not null default now()
);
create table if not exists image_jobs (
  id uuid primary key default gen_random_uuid(),
  user_id text not null,                     -- direct ownership (cold jobs have no session)
  session_id uuid references image_sessions(id) on delete cascade,  -- NULL = cold one-shot job
  model text not null,                       -- 'sdxl' | 'flux'
  prompt text not null,
  status text not null default 'queued',     -- queued | running | done | error
  image_b64 text, mime text default 'image/png', via text, error text,
  created_at timestamptz not null default now(),
  started_at timestamptz, done_at timestamptz
);
create index if not exists image_jobs_user_idx on image_jobs (user_id, created_at desc);
create index if not exists image_jobs_session_status_idx on image_jobs (session_id, status);
-- + RLS enable + policies (spike deliverable; see Security decision above):
--   • kernel (anon key + session JWT) → only rows of its own session_id
--   • PAWN backend (service key) → full access, bypasses RLS
```

### New module — `backend/app/core/image_session.py` (session + job manager)
One function per action; all Supabase calls run via `run_in_threadpool` (PERF-1). Uses `get_db()`
(service key — bypasses RLS) for all backend reads/writes.

**Session lifecycle:**
- `start_session(user_id, model, duration_minutes, max_images) -> dict` — validate model via
  `get_image_model` (reuse `core/image_models.py`); evict any prior live session for `(user, model)`;
  insert the `image_sessions` row; mint the scoped session JWT; build payload `{session_id,
  supabase_url, anon_key, session_jwt, model, expires_at, poll_interval, max_images}`; inject it with
  `kaggle.inject_payload` (reuse); push the persistent notebook via `kaggle.deploy_kernel`
  (`enable_gpu=True`, `enable_internet=True`, `dataset_sources=[spec.dataset]`,
  `accelerator=spec.accelerator`) — **non-blocking**, returns immediately. Returns `{session_id, expires_at, status}`.
- `get_session_status(user_id, model) -> dict` — latest row → `{status, expires_at, images_done,
  alive}` where `alive = status in {starting,ready} and heartbeat fresh and now < expires_at`.
- `extend_session(user_id, session_id, add_minutes)` — bump `expires_at` (cap at `IMAGE_SESSION_MAX_DURATION_MINUTES`).
- `stop_session(user_id, session_id)` — set `status='stopping'`.

**Jobs (unified — cold one-shot + warm session):**
- `create_cold_job(user_id, model, prompt) -> job_id` — validate model; if `(user, model)` already
  has a `queued`/`running` job, **return that job's id instead of inserting a duplicate** (idempotency
  guard — the server-side half of "one per model at a time"); else insert a `queued` row (session_id
  NULL) and return its id. Used by the cold path.
- `run_cold_job(job_id)` — the background worker: PATCH `running`/`started_at`; call the existing
  `generate.generate_image(user_id, prompt, model)` (its blocking Kaggle round-trip) in a threadpool;
  on success PATCH `done` + `image_b64`/`via`, on error PATCH `error`. Spawned fire-and-forget from
  the route under the per-`(user,model)` lock so same-model jobs serialize.
- `submit_session_job(user_id, session_id, prompt) -> job_id` — assert session alive; insert a
  `queued` job with that `session_id` (the live kernel will pick it up and write the result).
- `get_job(user_id, job_id) -> {status, image_b64?, mime?, via?, error?, model, prompt, created_at}`.
- `list_jobs(user_id, model?=, limit=20) -> [job…]` — recent jobs for the monitor panel (newest first).
- `reap_stale_jobs(user_id)` — mark `running` jobs whose owner is dead (cold job past a max wall-clock,
  or session-job whose session heartbeat is stale) as `error`, so the panel never hangs on a ghost.

**`core/kaggle.py` needs no new function** — `deploy_kernel` (`kaggle.py:279`) is the "push and don't
wait" primitive for the warm push; the cold path reuses `run_kernel` (`kaggle.py:318`) unchanged
inside `run_cold_job`. The warm path deliberately **bypasses `run_kernel`/`_fetch_output_file`**
(batch-only); warm images arrive via Supabase. Reuse `inject_payload` (`kaggle.py:48`) verbatim.

### Routes — extend `backend/app/routes/generate.py`
All scoped by `request.state.user_id`; Supabase work off-loop. Reuse the per-`(user,model)`
`_lock_for` (`routes/generate.py:29`) to serialize each model's cold runs (and around the `start` push).

**Changed — image generation becomes non-blocking job submission:**
- `POST /generate` with `modality:"image"` → `create_cold_job(...)`, then spawn `run_cold_job(job_id)`
  fire-and-forget (`asyncio.create_task`, which acquires the model lock then `run_in_threadpool`s the
  Kaggle round-trip), and **return `{job_id, status:"queued"}` immediately** (no longer the blocking
  image JSON). `modality:"cube"` stays blocking (dev-only). `/generate/connect` unchanged.

**New — job + session endpoints:**
- `GET  /generate/job/{job_id}` → `get_job` (cold or warm; the frontend polls this)
- `GET  /generate/jobs?model=&limit=` → `list_jobs` (the monitor panel)
- `POST /generate/session/start` `{model, duration_minutes, max_images?}`
- `GET  /generate/session/status?model=`
- `POST /generate/session/job` `{session_id, prompt}` → `{job_id}` (`submit_session_job`)
- `POST /generate/session/extend` `{session_id, add_minutes}`
- `POST /generate/session/stop` `{session_id}`

(Warm + cold jobs share `GET /generate/job/{id}` and `GET /generate/jobs` — the panel doesn't care
which produced them.)

### Persistent notebook — `backend/app/kaggle_templates/image_flux_session/notebook.ipynb`
Clone `image_flux/notebook.ipynb`; keep cell-0 `__PAWN_PAYLOAD_B64__` decode + the
`os.walk("/kaggle/input")` `model_index.json` search. Then:
- **Cell 1** — pip install (`diffusers transformers accelerate sentencepiece protobuf`); `requests` is preinstalled on Kaggle.
- **Cell 2** — load `FluxPipeline` **once** (bf16, `device_map="balanced"`, `vae.enable_tiling()`); on success PATCH `status='ready'` + heartbeat; on failure PATCH `status='error'` + message and exit. Keep the `enable_model_cpu_offload()` try/except crash-guard (hard rule: 2× T4 always present).
- **Cell 3** — the work loop (Supabase REST via `requests`; `apikey: <anon_key>`, `Authorization: Bearer <session_jwt>`):
  ```python
  while True:
      sess = get_session(session_id)                       # status, expires_at, max_images, images_done
      if sess["status"] == "stopping" or now() >= sess["expires_at"] \
         or (sess["max_images"] and sess["images_done"] >= sess["max_images"]):
          patch_session(status="ended"); break
      patch_session(heartbeat_at=now())
      job = next_pending_job(session_id)                   # order by created_at, limit 1
      if not job:
          time.sleep(poll_interval); continue
      patch_job(job, status="running")
      try:
          img = pipe(prompt=job["prompt"], num_inference_steps=4, guidance_scale=0.0,
                     max_sequence_length=256, height=1024, width=1024).images[0]
          patch_job(job, status="done", image_b64=png_b64(img))
          patch_session(images_done=sess["images_done"] + 1)
      except Exception as e:
          patch_job(job, status="error", error=str(e))
  ```
A SDXL session variant is a follow-up (same loop, swap the load/inference cell) — not required for W.1.

### `backend/app/constants.py` — new
`KAGGLE_SESSION_POLL_INTERVAL_SECONDS = 3` (kernel loop), `IMAGE_SESSION_HEARTBEAT_STALE_SECONDS = 30`
(→ dead), `IMAGE_SESSION_MAX_DURATION_MINUTES = 120` (Kaggle run backstop), `IMAGE_JOB_POLL_INTERVAL_SECONDS = 3`
(backend/UI poll for job done).

### `backend/app/config.py` + secrets — new `supabase_jwt_secret`
Add to `config.py` (`read_secret`), `docker-compose.yml` `secrets:` block, and
`secrets/supabase_jwt_secret.example`. Used only to mint the scoped per-session JWT. (User grabs it
from Supabase → Project Settings → API → JWT secret.)

---

## Frontend changes — `frontend/src/` (Image Lab only)

### `components/ImageLabPage.tsx` — the `ImageGenerator` panel becomes job-driven (~lines 376–482)
Replace the "hold one promise in React state" flow with **submit → poll job id → render**:
- **Generate** (cold *or* in-session) → POST returns `{job_id}`; the component **polls
  `getJob(job_id)`** at `IMAGE_JOB_POLL_INTERVAL` until `done`/`error`, then renders (reuse the existing
  `<img data:…base64>` block, ~line 456). No long-held fetch; safe to unmount.
- **Button state is derived from the server jobs list, not local state** — disabled while this model
  has a `queued`/`running` job. After a refresh the list still reports it, so the button stays
  disabled → **no duplicate submit** (the bug). Backend `create_cold_job` also dedups as a backstop.
- A **session bar** above the prompt box for the active model:
  - Duration select (30 / 60 / 120 min) + optional "max images" input + **Start warm session**.
  - While `starting`: "Loading model on Kaggle (~10 min, one-time)…" (existing amber pulse).
  - While `ready`: "🟢 Warm · ⏳ 47:12 left · 3 images" — live countdown from `expires_at`, `images_done`, plus **Extend +30 min** and **Stop**.
  - Generate routes to `submitSessionJob` when a session is live (fast), else cold `runGenerate` ("Generate once (cold ~14 min)").
  - On expiry/dead-heartbeat → inline "Session ended — start a new one?" CTA.
- Persist active `session_id` per model in localStorage (extend the `pawn-kaggle-deployed` pattern,
  ~lines 39–56) so a refresh re-attaches to a live session via `getSessionStatus`.

### New `components/GenerationsPanel.tsx` — the monitor (the "tab showing progress of all generations")
A collapsible panel in `ImageLabPage` (e.g. a right column / toggle) that lists `listJobs()` newest-first:
- Per job: **model badge**, truncated prompt, **status chip** (queued / running + spinner / done / error),
  relative time, and when `done` a **thumbnail** with **View** (reuse a lightbox) + **Download**.
- Polls `listJobs()` while any job is `queued`/`running`; idles otherwise. Survives refresh (server-backed),
  shows cold + warm + cross-model jobs together, and is where a result the user "navigated away from" reappears.

### `api/client.ts` — new helpers (mirror the existing `runKaggleImage`/`connectKaggle` shape, with `authHeaders()`)
- Jobs: `runGenerate(model, prompt) -> {job_id}` (replaces the blocking `runKaggleImage`),
  `getJob(jobId)`, `listJobs(model?, limit?)`.
- Sessions: `startSession(model, durationMin, maxImages?)`, `getSessionStatus(model)`,
  `submitSessionJob(sessionId, prompt)`, `extendSession(sessionId, addMin)`, `stopSession(sessionId)`.

`App.tsx` / `Sidebar.tsx` unchanged (Image Lab arm already exists). `MessageInput.tsx`,
`Message.tsx`, `useConversationStore.ts`, `types.ts` **untouched** (chat = Milestone B, deferred).

---

## Tests (mock Supabase + Kaggle — **no real external calls**, testing rule)

### `backend/tests/test_image_session.py` (warm sessions)
- `start_session` inserts a session row and pushes the persistent notebook with `enable_gpu=True` + the FLUX dataset; returns `session_id`/`expires_at`.
- **Security:** assert the pushed source contains the injected anon key + session JWT (base64 via `__PAWN_PAYLOAD_B64__`) and **never** the Supabase `service_key`.
- `submit_session_job` inserts a `queued` row for the session; `get_job` returns `image_b64` once `done`.
- `get_session_status`: stale heartbeat → `alive=false`; fresh + before expiry → `alive=true`.
- `extend_session` bumps `expires_at` (capped); `stop_session` sets `status='stopping'`.

### `backend/tests/test_image_jobs.py` (unified job tracking — the bug fix)
- `POST /generate {modality:image}` returns `{job_id, status:"queued"}` (no longer blocking image JSON) and schedules the background worker (assert the run is dispatched off-loop, not awaited inline).
- **De-dup:** a second `create_cold_job` for the same `(user, model)` while one is `queued`/`running` returns the **same** job id (no duplicate) — the server half of "one per model at a time".
- `run_cold_job` transitions `queued → running → done` and writes `image_b64`/`via` from a mocked `generate.generate_image`; on raise → `error` with the message.
- `GET /generate/job/{id}` reflects status + image; `GET /generate/jobs?model=` lists newest-first and filters by model.
- Unknown model → 400 (`UnknownModelError`); missing creds surfaces as a job `error` (or 412 on submit).
- Update the existing `test_generate.py` image tests to the new `{job_id}` contract (cube tests unchanged); `test_keys_kaggle.py` stays green.

---

## Verification (end-to-end)

**W.0 (prove the loop, CPU):** Lab → Start session → submit a job → watch the CPU kernel pick it up
from Supabase, echo it back, heartbeat for ~5 min, and exit on Stop. Transport + warm-loop proven.

**Bug fix (cold one-shot job tracking — verify first, it ships in W.1):**
1. Image Lab → SDXL → Generate → **immediately refresh the page**. The job reappears as `running` in
   the **Generations panel** and the Generate button is **disabled** (no duplicate). When the Kaggle
   run finishes, the image shows in the panel — even though you navigated away. ✅ the reported bug.
2. Click Generate twice fast / on two tabs → only **one** run starts for that model (de-dup); a
   different model's Generate runs **in parallel**.

**W.1 + W.2 (live FLUX warm session):**
3. `docker compose up -d --build`; add `secrets/supabase_jwt_secret`; run the new schema in Supabase.
4. Image Lab → **FLUX** → 60 min + cap 10 → **Start warm session**.
5. Status: `Starting → Warm` after the one-time ~10 min load; countdown + heartbeat visible.
6. Generate "a red apple on a wooden table" → returns in **seconds** (not ~14 min). Generate 3 more → each fast, all listed in the panel. ✅ the whole point.
7. **Extend +30** → countdown jumps. **Stop** → status `ended`; confirm in the Kaggle UI the run actually stopped.
8. Let the timer (or the image cap) hit → "session ended — start a new one?" appears.
9. Second Google account → its own session row + own kernel + own jobs, no cross-leak.
10. `docker compose exec backend pytest` green (incl. `test_image_session.py` + `test_image_jobs.py`); `cd frontend && npm run build` clean.

---

## Execution order (we proceed step by step — pause for review between steps)

**Step 0 — persist the plan into the repo (DONE as part of this step):**
- This file (`workspace/plan/plan_v5_warm_session.md`) is the repo source of truth.
- `workspace/status/build_tracker.md` gains **Phase W** with W.0/W.1/W.2 (Active step → W.0).
- `workspace/current_state.md` points Active step → W.0.

**Step 1 — W.0** (prove the persistent loop, CPU echo): schema (`image_sessions` + `image_jobs`) +
`session_poc` notebook + minimal `image_session.py` (`start_session`/`submit_session_job`/`get_job`)
+ session routes + a minimal Lab control. Verify the warm-loop + Supabase rendezvous. Then pause.

**Step 2 — W.1** (real FLUX + unified job tracking): the FLUX persistent notebook, full session
manager, cold-job background worker + de-dup, `GET /generate/job` + `/generate/jobs`, the changed
`POST /generate` contract, `supabase_jwt_secret`, and both test files. Then pause.

**Step 3 — W.2** (Image Lab UI): job-driven `ImageGenerator`, `GenerationsPanel`, session bar +
countdown/extend/stop, server-derived button state, `client.ts` helpers, `npm run build`. Then pause.

After each step: run the relevant tests/build, then update `build_tracker.md` (mark the step `[x]`)
and `current_state.md` per the project's working agreement before starting the next.

---

## Risks / open items
- ⚠️ **Load-bearing assumption** — a batch-pushed Kaggle kernel running a long internet loop for tens of minutes. **W.0 exists specifically to prove this first.** If Kaggle kills long batch loops, fall back to the v4 "Architecture 2" tunnel variant (more TOS-sharp) or accept batch + pre-baked deps only.
- **No hard-kill** — Stop is cooperative (status flag + the kernel's internal timer as hard backstop). Kaggle exposes no clean batch-cancel.
- **GPU quota** — a warm session burns wall-clock against the ~30 h/week quota; the timer + cap are the user's quota control. Surface quota failures as a typed error, not a 500.
- **Security / RLS** — scoped session JWT + RLS is the recommended path; exact policy wiring is the W.1 schema spike. Service key is never injected.
- **Image size / volume** — base64-in-row (≤ ~5 MB PNG); fine for a personal trial, and `list_jobs` is capped + selects metadata (not `image_b64`) so the panel stays light, fetching bytes only on View. If rows get heavy, move image bytes to a Supabase Storage bucket — interface-compatible follow-up.
- **Liveness races** — a job stuck `running` because its owner died (a backend restart drops an in-flight cold task; a warm kernel dies mid-generate). `reap_stale_jobs` marks these `error` (cold: past a max wall-clock; warm: session heartbeat stale) so the panel never hangs; the UI offers retry.
- **Backend-restart durability** — job *rows* survive a backend restart (Supabase), but an in-flight **cold** task does not resume; it's reaped to `error` and the user re-generates. (Warm jobs are owned by the kernel, unaffected by a PAWN restart.)
- **Cleanup** — delete a `(user, model)`'s prior session when a new one starts; optional periodic sweep of `ended`/expired sessions and old `done`/`error` jobs to bound row growth.
