# Plan v4 — Kaggle-backed Image Generation (imageLab)

**Branch:** `imageLab` → merges into `dev`  
**Last stable commit:** `306e41f` ("Stable: concurrent multi-chat + key-aware models with cross-provider failover")

---

## What's Done

| Milestone | What it covered | Status |
|---|---|---|
| A.0 | Batch Kaggle round-trip proof (cube POC, CPU, no model) | ✅ Live |
| A.1 | SDXL + FLUX.1-schnell cold generation, model-switch UI | ✅ Live |
| W.0 | Warm session persistent-loop proof (CPU echo + Supabase rendezvous) | ✅ Live |
| W.1 | FLUX warm serve-loop + unified durable job layer (lost-result bug fix) | ✅ Live |
| W.2 | Image Lab UI — job-driven generator, GenerationsPanel, SessionBar | ✅ Live |
| W.3 | Real SDXL warm serve-loop (load once → generate many) | ✅ Live |

Current backend test count: **134 green**. `npm run build` clean.

---

## Architecture Summary (what's built)

**Cold path (no session):** `POST /generate` → `create_cold_job` (de-duped per `(user, model)`) → fire-and-forget background worker → `generate.generate_image` blocking Kaggle round-trip → writes result to `image_jobs` row → frontend polls `GET /generate/job/{id}`.

**Warm path (session live):** `POST /generate/session/job` → inserts `queued` row → live Kaggle kernel picks it up via Supabase REST → generates (model already warm) → patches row `done` + `image_b64` → frontend polls same `GET /generate/job/{id}`.

Both paths produce an identical `image_jobs` row; one polling API and one `GenerationsPanel` covers everything.

**Key files:**
- `backend/app/core/image_session.py` — session lifecycle + unified job layer
- `backend/app/core/image_models.py` — model registry (SDXL / FLUX)
- `backend/app/core/kaggle.py` — Kaggle Kernels REST client
- `backend/app/core/generate.py` — cold one-shot dispatch
- `backend/app/routes/generate.py` — all `/generate/*` routes
- `backend/app/kaggle_templates/image_flux_session/notebook.ipynb` — FLUX warm serve-loop
- `backend/app/kaggle_templates/image_sdxl_session/notebook.ipynb` — SDXL warm serve-loop
- `frontend/src/components/ImageLabPage.tsx` — Image Lab page
- `frontend/src/components/SessionBar.tsx` — warm session controls
- `frontend/src/components/GenerationsPanel.tsx` — job monitor
- `frontend/src/api/client.ts` — all session/job helpers

**Hard rules:**
- `NvidiaTeslaT4` always provisions a 2× T4 (2×16 GB) box. FLUX (~24 GB bf16) shards across both via `device_map="balanced"`. Both cards are assumed present.
- The Supabase `service_key` is never injected into any notebook. Only the public `anon_key` + URL are injected.
- All Supabase + Kaggle calls run via `run_in_threadpool` (never block the async event loop).

---

## Known Issues (from live verification)

These were observed during W.1–W.3 live runs and are the direct motivation for W.4–W.6:

1. **"session ended before this job ran" error in GenerationsPanel (confirmed live)** — Root cause is a cascade triggered by `IMAGE_SESSION_HEARTBEAT_STALE_SECONDS = 30`:
   - `list_jobs` calls `reap_stale_jobs` on every frontend poll (~3 s).
   - `reap_stale_jobs` calls `_is_alive` on all sessions for the user.
   - `_is_alive` checks `heartbeat_at` age against 30 s. The kernel pauses heartbeats during FLUX inference (~30–90 s per image), so the session is declared dead mid-generation.
   - `reap_stale_jobs` then marks all `queued` jobs for that session as `error: "session ended before this job ran"`.
   - The job is killed before the kernel can pick it up — even though the kernel is alive and will generate the image successfully if left alone.
   - Fix: raise `IMAGE_SESSION_HEARTBEAT_STALE_SECONDS` to 90 s (W.6 Fix A).

2. **GPU slot exhaustion cascade** — false "ended" → user falls back to cold Generate → warm FLUX + cold FLUX = 2 GPU slots = Kaggle limit → SDXL cold job fails with "Maximum batch GPU session count of 2 reached". Fix: block cold jobs while a warm session is live (W.6 Fix B).

3. **No startup phase visibility** — FLUX startup is ~20 min. The UI shows `status='starting'` the entire time with no breakdown between "queuing on Kaggle", "pip installing", and "loading the 12B model". Fix: W.4.

4. **Tab switcher loses session state** — switching model tabs unmounts `SessionBar` + `ImageGenerator`, resetting poll timers and the live countdown. Fix: W.5.

---

## What Remains (W.4 – W.6)

Implementation order: **W.6 → W.4 → W.5**

W.6 first (heartbeat fix makes W.4 phase transitions safe to observe). W.4 before W.5 (SessionBar changes easier to validate on single-tab layout before W.5 restructures it).

---

### W.6 — Session Liveness + Cold-vs-Warm Routing Fixes

**Files:** `constants.py`, `core/image_session.py`, `core/kaggle.py`, `components/SessionBar.tsx`

**Fix A — Heartbeat stale threshold (`constants.py`)**

```python
IMAGE_SESSION_HEARTBEAT_STALE_SECONDS = 90   # was 30; 3× typical FLUX inference time
```

**Fix B — Block cold job if warm session is live (`core/image_session.py`)**

In `create_cold_job`, before the INSERT:

```python
latest = _latest_session(db, user_id, model)
if latest is not None and _is_alive(latest):
    raise RuntimeError(
        f"A warm session is already running for '{model}'. "
        "Submit via the session — use Generate on the warm session bar."
    )
```

Route catches `RuntimeError` → HTTP 400; frontend surfaces in the existing error box.

**Fix C — Kaggle GPU limit: human-readable error (`core/kaggle.py`)**

In `deploy_kernel` / `run_kernel`, after reading the error body:

```python
if "Maximum batch GPU session count" in error_body:
    raise KaggleError(
        "Kaggle GPU limit reached (max 2 concurrent GPU sessions). "
        "Stop an active warm session or wait for a running job to finish, then retry."
    )
```

**Fix D — Confirm before re-Start if session exists (`components/SessionBar.tsx`)**

```tsx
async function handleStart() {
  if (session && !window.confirm(
    'A session already exists for this model. Starting a new one will stop it on Kaggle. Continue?'
  )) return
  // ... existing start logic
}
```

**Tests:** Add one test — `create_cold_job` raises when a live session exists for that model.

**Demo:** Warm FLUX session stays "Warm ●" throughout inference. Cold Generate while session is live → error box. GPU limit → actionable message. Re-Start with active session → confirm dialog.

---

### W.4 — Session Startup Observability

**Files:** both session notebooks, `core/image_session.py`, `components/SessionBar.tsx`, `api/client.ts`

#### Prerequisite bug fixes (must land before the phase patches)

**Bug 1 — `_LIVE_STATUSES` missing new statuses (`core/image_session.py` line 44)**

Current: `_LIVE_STATUSES = ("starting", "ready")`

A kernel that patches itself to `installing` is immediately treated as dead by `_is_alive()` and `reap_stale_jobs`. Fix:

```python
_LIVE_STATUSES = frozenset({"starting", "installing", "loading_model", "ready"})
```

No logic change to `_is_alive()` — the heartbeat check is already skipped for non-`ready` statuses. Just set membership.

**Bug 2 — Frontend `starting` variable too narrow (`SessionBar.tsx` line 78)**

Current: `const starting = session?.status === 'starting'`

After the notebook patches `installing` or `loading_model`, `starting` is false, so `const ended = !!session && !live && !starting` becomes true and the bar shows "Session ended — start a new one" while the kernel is mid-install. Fix is in Fix 3 below.

#### Fix 1 — Notebook phase patches (both models, identical placement)

**`kaggle_templates/image_flux_session/notebook.ipynb`**  
**`kaggle_templates/image_sdxl_session/notebook.ipynb`**

| Cell | Where exactly | Call |
|---|---|---|
| Cell 1 | Top, before `subprocess.check_call` | `patch_session({"status": "installing"})` |
| Cell 2 | Top, before `from_pretrained` | `patch_session({"status": "loading_model"})` |
| Cell 2 | After successful load (existing line) | `patch_session({"status": "ready", "heartbeat_at": now_iso()})` — no change |

The `installing` patch fires within seconds of the container starting, distinguishing "notebook is running" from "still in Kaggle's GPU queue."

#### Fix 2 — Backend `_LIVE_STATUSES` (`core/image_session.py`)

```python
_LIVE_STATUSES = frozenset({"starting", "installing", "loading_model", "ready"})
```

No schema change — `status` is a free-text column.

#### Fix 3 — Frontend phase messages (`components/SessionBar.tsx`)

```tsx
const WARMUP_STATUSES = new Set(['starting', 'installing', 'loading_model'])

const STARTUP_MESSAGES: Record<string, string> = {
  starting: 'Waiting for Kaggle GPU…',
  installing: 'Installing dependencies (1–2 min)…',
  loading_model: 'Loading model onto GPU (FLUX: ~7 min · SDXL: ~2 min)…',
}

const warmingUp = !!session && WARMUP_STATUSES.has(session.status)
const ended = !!session && !live && !warmingUp
```

Replace the existing `{starting && ...}` block:

```tsx
{warmingUp && (
  <div className="flex items-center gap-2 text-[11px] text-amber-600 dark:text-amber-400">
    <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse shrink-0" />
    <span>{STARTUP_MESSAGES[session!.status] ?? 'Starting…'}</span>
  </div>
)}
```

#### Fix 4 — Type comment (`api/client.ts`)

```ts
status: string // none | starting | installing | loading_model | ready | stopping | ended | error
```

**Tests:** Assert `_LIVE_STATUSES` includes `installing` and `loading_model`. Assert `_is_alive` returns `True` for a session with `status='installing'` and a future `expires_at`.

**Demo:** Start warm FLUX session → "Waiting for Kaggle GPU…" → "Installing dependencies…" → "Loading model onto GPU…" → "🟢 Warm · ⏳ …"

---

### W.5 — Independent Per-Model Panels

**Files:** `frontend/src/components/ImageLabPage.tsx` only. No backend changes.

**Problem:** Tab switcher unmounts `SessionBar` + `ImageGenerator` on switch, resetting poll timers and the live countdown. Shared `GenerationsPanel` mixes all models' jobs.

Remove `activeModelId` state, the tab bar, and the single-model render. Replace with a `ModelPanel` component (defined inside `ImageLabPage.tsx`) that renders all models stacked vertically — always mounted, never unmounted.

Each `ModelPanel`:
- Owns its own `jobs` state polling `listJobs(model.id, 30)` independently
- Owns its own `SessionBar` + `ImageGenerator` — always mounted
- Owns its own `GenerationsPanel` receiving only its model's jobs
- Receives `hasCreds` as a prop from the shared `KaggleCredentials` block at the top

```
[Kaggle Credentials — saved]

┌── SDXL ──────────────────────────────────────────────┐
│ Connection & Notebook Deployment   [Deployed ✓]       │
│ Warm session  [Start 30 min]                          │
│ [Prompt textarea]  [Generate]                         │
│ Generations                                           │
│   ● running  a cinematic shot...  2m ago              │
└───────────────────────────────────────────────────────┘

┌── FLUX.1-schnell ────────────────────────────────────┐
│ Connection & Notebook Deployment   [Deployed ✓]       │
│ Warm session  [Start 30 min]                          │
│ [Prompt textarea]  [Generate]                         │
│ Generations                                           │
│   (empty — no FLUX jobs submitted)                    │
└───────────────────────────────────────────────────────┘
```

**Tests:** `npm run build` clean.

**Demo:** Submit SDXL → only SDXL Generations panel updates; FLUX panel untouched. Start both sessions simultaneously → both countdowns tick independently without either resetting.

---

## Deferred

| Item | Reason deferred |
|---|---|
| Scoped per-session JWT + RLS | Supabase `sb_publishable_*` platform deprecates legacy HS256 minting. Permissive-anon policy stays for single-user trial. Mandatory before multi-user. |
| Chat composer integration (Milestone B) | Isolated Image Lab is the current target. Routing + transport are already modality-shaped. |
| Text-to-video | Template + UI only; routing is ready. |
| SDXL quality tuning (steps/guidance/resolution) | Orthogonal; pre-existing deferred item. |
| `status_updated_at` column for startup crash detection | Would detect a kernel crash mid-install without waiting for `expires_at`. Requires schema migration. Low-risk for single-user trial. |
| SDXL CPU-offload fallback | SDXL fits a single T4 (~7 GB fp16). FLUX already has the crash-guard fallback. |

---

## Verification Checklist (W.6 → W.4 → W.5)

1. `docker compose exec backend pytest` — 134+ tests green
2. `npm run build` — clean, no type errors
3. **W.6:** Start warm FLUX session → generate → SessionBar stays "Warm ●" throughout (no false "Session ended")
4. **W.6:** With FLUX session live, click cold Generate → error shown in error box
5. **W.6:** Hit Kaggle GPU limit → "Kaggle GPU limit reached…" message, not raw traceback
6. **W.6:** Click Start with existing session → confirm dialog appears
7. **W.4:** Start warm FLUX → "Waiting for Kaggle GPU…" → "Installing dependencies…" → "Loading model onto GPU…" → "🟢 Warm · ⏳ …"
8. **W.4:** Same sequence for SDXL (faster: installing ~30 s, loading ~2 min)
9. **W.5:** Both SDXL and FLUX panels visible simultaneously
10. **W.5:** Submit SDXL job → only SDXL Generations updates; FLUX panel untouched
11. **W.5:** Start FLUX + SDXL sessions simultaneously → both countdown tickers independent
12. **W.5:** Navigate away from Image Lab and back → all panel state preserved (no remount reset)
