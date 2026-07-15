# Phase V3 — Video Lab UI (imageLab architecture, Higgsfield-inspired presentation, mobile-first)

**Goal:** the user-facing Video Lab page. Architecturally a mirror of imageLab (always-mounted
per-model panels, SessionBar, GenerationsPanel, shared credentials block) — but presented like
a modern video-gen product (Higgsfield-style): **gallery-first**, a prominent prompt composer,
preset chips instead of raw parameter walls, and fully **mobile responsive**.

**Read first:** `frontend/src/components/{ImageLabPage,SessionBar,GenerationsPanel,
ImageGenerator,AdvancedParams,KaggleCredentials}.tsx`, `frontend/src/api/client.ts`,
`workspace/implemented_phases/phase_06_ui.md` and `phase_07_mobile_readiness.md`,
`.claude/rules/frontend.md` (~150-line component rule, client.ts-only API calls, types in
`types.ts`, Tailwind v4, no new UI libraries).

**Branch:** `dev`. Steps V3.1–V3.5 in `build_tracker.md`.

---

## Design Direction (locked)

**From imageLab (architecture — keep):**
- One page, `VideoLabPage.tsx`, route + sidebar entry next to Image Lab.
- Shared `KaggleCredentials` block at top (same component, same stored creds — reuse, don't fork).
- Per-model panels **always mounted** (imageLab W.5 lesson: unmounting kills poll timers and
  countdowns). Each panel owns its jobs polling, SessionBar, composer, and gallery.
- SessionBar: Start (30 min) / countdown ⏳ / Extend / Stop, warmup-phase messages
  ("Waiting for Kaggle GPU…" → "Installing dependencies…" → "Loading model (~4 min)…"),
  `Warming · loading_model · 1m 21s` elapsed substatus (round-7 parity), confirm-before-restart.
- GenerationsPanel mechanics: 3–5 s job polling, `N running · M queued` split counts, live
  `⏱ Xm Ys` elapsed ticker per running job, copy-prompt button, error rows with real messages.

**From Higgsfield (presentation — new):**
- **Gallery-first**: finished clips render as a responsive grid of video cards (not a list of
  rows). Card = looping muted autoplay preview on hover/tap (poster = first frame), duration
  badge, model chip, prompt on hover overlay / tap-to-expand on mobile. Click → lightbox with
  native `<video controls>`, prompt, params, Download, "Reuse prompt", and (V4) "Animate
  again" / "Use as start frame".
- **Prominent prompt composer** per model panel: large textarea, aspect chips
  (9:16 default · 1:1 · 16:9), duration chips (3 s / 5 s — mapped to 8n+1 frame counts),
  a single Generate button that routes warm-session-first (falls back to cold with a
  "cold start ≈ 15–25 min" hint when no session is live — copy calibrated from V2.4 timings).
- **Preset chips over parameter walls**: a horizontal scrollable row of motion/style presets
  ("Slow orbit", "Static shot", "Dolly in", "Handheld", "Cinematic", "Product spin") — each is
  just a prompt suffix (backend `STYLE_SUFFIXES` pattern from imageLab's style presets, new
  `MOTION_SUFFIXES` dict in `routes/video.py`). Advanced params stay in a collapsed
  `AdvancedParams`-style panel (steps, guidance, seed, negative prompt, explicit WxH).
- Dark, media-forward look consistent with PAWN's existing theme system (respect the user's
  theme accent; no hardcoded colors outside Tailwind theme tokens).

**Mobile responsiveness (hard requirement, not a polish pass):**
- Gallery: `grid-cols-2` on mobile → 3–4 cols ≥`md`; cards keep 9:16 aspect via `aspect-[9/16]`.
- Composer sticky at bottom of the active panel on mobile; chips horizontally scrollable
  (`overflow-x-auto`, no wrap); touch targets ≥44 px.
- SessionBar collapses to a single status pill + kebab (Extend/Stop inside) under `sm`.
- Model panels: vertical stack everywhere; on mobile add a sticky top model-switcher chip row
  that scroll-jumps between panels (panels stay mounted — anchor scroll, not tabs).
- Lightbox is full-screen on mobile; `playsinline muted` attributes so iOS autoplays previews.
- Verify with the checks from `phase_07_mobile_readiness.md` (viewport, safe-area, no
  horizontal overflow) at 360 px, 390 px, 768 px, 1280 px widths.

---

## V3.1 — API client + types

**Files:** `frontend/src/api/client.ts`, `frontend/src/types.ts`.

Add `VideoJob`, `VideoSession`, `VideoModelInfo` types and client helpers mirroring the image
set: `videoGenerate`, `videoListJobs` (list responses exclude `video_b64`), `videoGetJob`,
`videoSessionStart/Status/Job/Stop/Extend`. Also `GET /video/models` (small V1 route addendum
if not present: id/label/defaults/supports_i2v per registry row) so the UI renders panels from
data, not hardcoded lists — this is what makes model switching data-driven (V5 adds rows, UI
updates itself). No fetch outside client.ts.

**Gate:** `tsc` + `npm run build` clean.

## V3.2 — Page skeleton + per-model panels

**Files:** new `frontend/src/components/videolab/VideoLabPage.tsx` +
`VideoModelPanel.tsx`, sidebar/router wiring file(s).

`VideoLabPage` = credentials block + `models.map(m => <VideoModelPanel …/>)` stacked, all
mounted. Panel owns: session state polling, jobs polling (`videoListJobs(model, 30)` every
5 s), and composes V3.3/V3.4 children. Mobile sticky model-chip scroll-jump row lives here.
Split any component crossing ~150 lines (frontend rule) — expect `videolab/` to end up with
5–8 small files.

**Gate:** build clean; both panels render with empty states.

## V3.3 — Composer + presets + SessionBar reuse

**Files:** `frontend/src/components/videolab/VideoComposer.tsx`,
`VideoAdvancedParams.tsx`; `SessionBar.tsx` — reuse if its props allow parametrizing the
API calls + copy, else create `videolab/VideoSessionBar.tsx` as a thin adaptation (do NOT
edit SessionBar behavior used by imageLab; props-only generalization is acceptable).

Composer: textarea, aspect chips, duration chips, preset chips row, Generate button with
warm-first routing + cold-fallback hint, disabled states matching imageLab rules (no creds,
cold blocked while warm session live — surface backend's message). Backend addendum:
`MOTION_SUFFIXES` applied server-side like `STYLE_SUFFIXES` (keeps prompts canonical in the
job row). Duration chips → frame count via `snap_frames_8n1` client-mirror (pure function in
`videolab/frames.ts` with a unit test if vitest is configured; else backend remains the
authority and UI sends seconds).

**Gate:** build clean; warm + cold submissions work against dev stack (mock or live).

## V3.4 — Gallery + lightbox

**Files:** `frontend/src/components/videolab/VideoGallery.tsx`, `VideoCard.tsx`,
`VideoLightbox.tsx`.

Card grid per the design direction: poster frame (first frame — `<video preload="metadata">`
gives it free), hover/tap loop preview (`muted playsinline loop`), duration + model badges,
running/queued cards show the live elapsed ticker + a shimmer placeholder, error cards show
the message + retry (re-submits same prompt/params). Lightbox: full `<video controls>`, prompt
(copy button), params list, Download (`data:` URL → blob download, mind CSP `media-src` —
check `SecurityHeadersMiddleware` allows `data:`/`blob:` for media and fix BOTH backend
middleware and prod Nginx header copies, the imageLab CSP `img-src` deploy bug generalized).
Fetch `video_b64` lazily per-card on first play (single-job GET), never in list polling; cache
in component state; cap concurrent loaded videos (~6, LRU-release object URLs) to bound memory.

**Gate:** build clean; a done job (seeded/mocked) plays inline and in lightbox; mobile widths
verified (360/390/768/1280), no horizontal overflow.

## V3.5 — Live E2E + polish pass

With user's creds: full flow on desktop + a real phone — start session, watch warmup phases,
generate 2 clips via presets, extend, download, stop. Fix paper cuts found live. Update
`build_tracker.md` / `current_state.md` / `dev_log.md`; screenshot(s) referenced in dev_log.

---

## Risks

| Risk | Mitigation |
|---|---|
| Many mounted `<video>` elements → memory | lazy b64 fetch on first play, LRU object-URL release, `preload="metadata"` |
| CSP blocks `data:`/`blob:` video | explicit `media-src` check in V3.4 (both header copies — known deploy gotcha) |
| SessionBar fork drift vs imageLab | prefer props-only reuse; if forked, note divergence in dev_log |
| Mobile autoplay quirks (iOS) | `muted playsinline` on all previews; tap-to-play fallback |
