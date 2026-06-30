# Plan 1.0 — Generations Panel UI Fixes

**Branch:** `imageLab`
**Scope:** Four targeted fixes to the Generations panel header and job rows. No backend schema changes — all data is already present in the list response or in the existing `params` JSONB column.

---

## Fix 1 — Active count label

### Problem

The header shows `30 · 6 active` when there are 1 running + 5 queued. Calling queued jobs "active" is wrong — they haven't started yet.

### Fix

Replace the single `N active` badge with a split display:

```
Generations  30 · 1 running · 5 queued
```

Rules:
- **running** count: jobs where `status === 'running'`
- **queued** count: jobs where `status === 'queued'`
- If running = 0 and queued = 0: show nothing (just the total, e.g. `Generations  30`)
- If only one of them is non-zero, show just that segment:
  - `30 · 1 running`
  - `30 · 3 queued`
- Colour: running segment uses the amber/orange pulse colour (same as the existing running chip); queued segment uses muted text

---

## Fix 2 — Generation time in job rows

### Problem

Each row shows `7m ago` (time since the job was created / prompt was submitted). That is useful for context but says nothing about how long the actual GPU run took.

### What to add

Show generation time in the **rightmost corner** of each row, alongside the existing `created_at` timestamp. The two timestamps serve different purposes and should both be visible:

```
┌──────────────────────────────────────────────────────────┐
│  FLUX   A Japanese sports car drifting…                  │
│  queued   7m ago                                         │  ← no gen time (not started)
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│  FLUX   A Japanese sports car drifting…                  │
│  running  7m ago                        ⏱ 0m 42s        │  ← live elapsed timer
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│  SDXL   A Japanese sports car drifting…    View Download │
│  done   10m ago                            ⏱ 2m 18s     │  ← fixed gen time
└──────────────────────────────────────────────────────────┘
```

### Data source

`started_at` is already in `_JOB_LIST_COLUMNS` and returned by `list_jobs`, but it is not yet in `JobResult` in `client.ts` or mapped by `list_jobs` in `image_session.py`. That needs a one-line fix in both places.

| Status | Gen time shown | Source |
|---|---|---|
| `queued` | nothing | — |
| `running` | live elapsed since `started_at`, updates every second | `now() - started_at` |
| `done` / `error` | fixed duration | `done_at - started_at` |

### Format

`Xm Ys` — e.g. `2m 18s`, `0m 42s`, `14m 06s`. No milliseconds. If `started_at` is null for a running/done job (shouldn't happen, but defensive), show nothing.

### Live timer

For `running` jobs the elapsed time ticks up once per second. Use a `useEffect` with `setInterval(1000)` scoped to the row component. This interval is already acceptable since the parent `GenerationsPanel` polls the job list every 3 s anyway; the 1 s tick is only for the display digit, not a network call.

---

## Fix 3 — Style preset tag on the job row

### Problem

When a job was submitted with a style preset (e.g. Cinematic, Anime), there is no way to see that from the Generations panel. The stored prompt already has the suffix baked in, but the preset label is not shown.

### Fix

Read `style_preset` from the job's `params` JSONB field (already returned in the list response as part of the row, but not currently surfaced in the UI). Show it as a small pill tag in the **top-right corner of the first line** — beside the truncated prompt:

```
┌──────────────────────────────────────────────────────────┐
│  FLUX   Cristiano Ronaldo mid-jump…      [Cinematic]     │
│  queued   2m ago                                         │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│  SDXL   A Japanese sports car…           (no tag)        │
│  done   10m ago                          ⏱ 2m 18s       │
└──────────────────────────────────────────────────────────┘
```

- Only shown when `job.params?.style_preset` is non-empty
- Display name is the human-readable label (invert the `STYLE_PRESET_KEYS` map from `ImageLabPage.tsx`), e.g. `oil_painting` → `Oil Painting`
- Tag style: small pill, subtle background (e.g. `bg-theme-brand/10 text-theme-brand border border-theme-brand/20`), `text-[10px]`
- No click behaviour — display only

### Data source

`params` is already in `_JOB_LIST_COLUMNS` (`"id, session_id, model, prompt, status, mime, via, error, created_at, started_at, done_at"` — actually `params` is NOT currently in this column list). Two-line change needed:

1. Add `params` to `_JOB_LIST_COLUMNS` in `image_session.py`
2. Add `params?: Record<string, unknown> | null` to `JobResult` in `client.ts`

---

## Fix 4 — Copy prompt button

### Problem

Once a job is in the Generations panel, there is no way to reuse its prompt. The user has to type it again.

### Fix

Add a **copy icon button** to each job row. On click, copy `job.prompt` to the clipboard. Show a brief `✓ Copied` tooltip or swap the icon to a checkmark for 1.5 s, then reset.

```
┌──────────────────────────────────────────────────────────┐
│  FLUX   Cristiano Ronaldo mid-jump…  [Cinematic]  [⎘]   │  ← copy button
│  queued   2m ago                                         │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│  SDXL   A Japanese sports car…                    [⎘]   │
│  done   10m ago           View  Download   ⏱ 2m 18s     │
└──────────────────────────────────────────────────────────┘
```

- Use `navigator.clipboard.writeText(job.prompt ?? '')`
- Button: small icon-only button (`w-6 h-6`), clipboard SVG icon, muted colour, hover brightens
- Confirmed state: swap to a checkmark icon for 1.5 s via local `useState<boolean>`
- Truncated prompt in the row is NOT affected — it still truncates for display; what is copied is the full `job.prompt` string

---

---

## Fix 5 — Mark running/queued jobs as error when their session dies

### Problem

If a Kaggle notebook is stopped manually (or crashes), the warm-session health checker correctly marks the session as `stopped`. However, any generation jobs that were `running` or `queued` against that session remain stuck in `running`/`queued` forever — the Generations panel shows a spinning indicator with no error, and the user has no feedback that the job will never complete.

### Root cause

The session-death path updates `image_sessions.status` but does not touch `image_jobs`. The two tables are only loosely coupled: `image_jobs.session_id` links them, but nothing reads that link to propagate the session failure.

### Fix

When the health-check loop (or any code path) transitions an image session to a terminal state (`stopped`, `dead`, `error`), immediately fail all non-terminal jobs for that session:

```sql
UPDATE image_jobs
SET status = 'error',
    error  = 'Session terminated unexpectedly',
    done_at = now()
WHERE session_id = <session_id>
  AND status IN ('running', 'queued');
```

This update should happen **in the same transaction** (or immediately after) the session status change, so there is no window where the session is dead but jobs appear still running.

### Where the change goes

The health check loop that detects session death lives in `backend/app/core/image_session.py` (likely the `_reap_dead_sessions` or equivalent heartbeat handler). That function already has a DB connection and already writes to `image_sessions` — add the job-update query right after.

No new columns, no schema migrations, no frontend changes needed: `status = 'error'` and `error` are already present in `image_jobs` and already surfaced by `list_jobs`.

### Frontend behaviour (no code change needed)

Once the backend marks the jobs as `error`, the existing 3 s poll in `GenerationsPanel` picks them up automatically. The row will flip from the amber running indicator to the red error state on the next poll cycle (≤ 3 s after the session is reaped).

---

## Files to change

| File | Change |
|---|---|
| `backend/app/core/image_session.py` | Add `started_at` and `params` to `_JOB_LIST_COLUMNS`; fail running/queued jobs when their session goes terminal |
| `frontend/src/api/client.ts` | Add `started_at?: string \| null` and `params?: Record<string, unknown> \| null` to `JobResult` |
| `frontend/src/components/GenerationsPanel.tsx` | All four fixes: active count, gen-time ticker, style preset tag, copy button |

No route changes, no schema changes, no test changes (the list_jobs test only checks `has_image` — adding extra fields is additive).

---

## Completion Checklist

- [ ] `list_jobs` response includes `started_at` and `params`
- [ ] `JobResult.started_at` and `JobResult.params` typed in `client.ts`
- [ ] Header shows `N running · M queued` (or just one if the other is 0, or nothing if both 0)
- [ ] `queued` rows: no gen-time shown
- [ ] `running` rows: live `Xm Ys` elapsed since `started_at`, ticking every second
- [ ] `done`/`error` rows: fixed `Xm Ys` from `started_at` to `done_at`
- [ ] Gen time hidden if `started_at` is null
- [ ] Style preset tag shown in top-right of first line when `params.style_preset` is set
- [ ] Style preset key inverted to human-readable label (e.g. `oil_painting` → `Oil Painting`)
- [ ] Copy button on every row; copies full `job.prompt` to clipboard
- [ ] Copy button shows checkmark for 1.5 s then resets
- [ ] When a session goes terminal (`stopped`/`dead`/`error`), all its `running`/`queued` jobs are immediately set to `error` with message "Session terminated unexpectedly"
- [ ] Jobs marked error via session death show `done_at` so gen-time can display the partial elapsed time
- [ ] `npm run build` clean
