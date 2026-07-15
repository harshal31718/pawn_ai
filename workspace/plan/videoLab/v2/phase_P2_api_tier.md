# Phase P2 — API Tier: Hosted SOTA Models (the Higgsfield Jugad)

**Goal:** the biggest quality jump per line of code in the whole plan — route generation to
hosted SOTA models (Seedance, Kling, Wan 2.5/2.6, Veo, Hailuo) through fal.ai/Replicate on
the user's keys. After this phase, videoLab output quality equals Higgsfield's model lineup,
because it IS Higgsfield's model lineup.

**Read first:** `01_research_stack.md` §2, `core/llm_core.py` (the failover-chain pattern
being mirrored), `core/video_exec/base.py` (P1), fal + Replicate API docs at build time
(queue/webhook semantics change; re-verify).

**Branch:** `dev`. Steps P2.1–P2.4.

---

## P2.1 — `api_exec` executor + provider clients

**Files:** new `core/video_exec/api_exec.py`, new `core/video_providers/{fal,replicate}.py`,
`exceptions.py` (typed `VideoProviderError`), tests.

- Provider clients: thin async httpx wrappers — submit (fal queue API / Replicate
  predictions), poll status, fetch result bytes. Webhooks deliberately NOT used v1 (PAWN dev
  runs behind tunnels; polling is proven in this codebase). Poll interval per provider,
  exponential backoff, request ids into `provider_meta`.
- `api_exec.dispatch()`: estimate → budget check (P1 hook) → submit → background poll loop →
  download MP4 → Drive artifact (P1.2) → poster extraction (ffmpeg thumbnail server-side or
  provider-returned) → job done + `record(actual_cost)` (fal returns billed amounts; else
  compute from registry price × duration).
- **Failover chain per model row** (`providers: ["fal", "replicate"]` ordered list in the
  registry): provider down/queue-full/4xx-model-missing → next provider, mirroring
  `chat_stream`'s endpoint failover semantics and logging.

**Tests:** mocked-provider matrix (success, failover, both-fail, cost recording, budget
stop). Security-auditor (keys in headers, never logged/echoed in provider_meta).

## P2.2 — SOTA model registry rows

**Files:** `core/video_models.py` (rows gain `backends`, `providers`, `price_per_sec`,
`max_duration_s`, `native_audio`, `supports_reference_image`, provider-side model ids per
provider), possibly split registry into `data/registry/video_models.json` (data-not-code
rule — recommended now that rows are many; migrate the Kaggle rows into it too).

Initial lineup (verify exact provider slugs at build time):

| id | Model | Tier feel | Price ~ | Why |
|---|---|---|---|---|
| `seedance-fast` | Seedance Fast | Draft | $0.03/s | cheapest good draft; best-of-N fodder |
| `seedance-pro` | Seedance Pro | Pro | $0.05/s | price/quality king |
| `kling` | Kling 2.x/3.0 | Pro | $0.07/s | motion + camera params |
| `wan-api` | Wan 2.5/2.6 hosted | Pro | $0.05/s | open-family continuity with free tier |
| `hailuo` | MiniMax Hailuo 02 | Pro | mid | human motion |
| `veo` | Veo 3.1 (+Lite) | Max | $0.05 (Lite 720p)–$0.40/s | native audio, top realism |

I2V (start image) supported on all rows that offer it — params flow from the existing V4
plumbing (`init_image_b64` already in job params).

**Tests:** registry loads, per-row provider ids resolve, price fields drive estimates.

## P2.3 — UI: quality selector + model cards

**Files:** `frontend/src/components/videolab/*`.

- Composer gains the **Quality selector** (Draft/Pro/Max chips) mapping to default model
  rows; an "advanced" model picker lists every row with price badge + one-line blurb
  (registry `blurb`). Estimate line `≈ $0.35 · ~60 s` live-updates with duration/model.
- Panels-per-model layout (basic videoLab) evolves: 2.0 models DON'T get one panel each —
  they share ONE "Studio" panel with the model picker (panel-per-model stays only for
  Kaggle warm-session models, which have session state to show). This is the V3→2.0 UI
  pivot; keep it as one panel component swap, mobile rules intact.
- Jobs from all backends interleave in the same gallery with backend/model badges.

**Gate:** build clean; mocked E2E; mobile widths re-verified.

## P2.4 — Live verification

- User adds fal key (few dollars of credit) → Draft (Seedance) clip <60 s end-to-end →
  Pro (Kling) → one Veo Lite with audio. Ledger matches provider dashboard within cents.
  Failover tested by forcing a bad fal key with Replicate configured.
- Record real latencies + costs in dev_log; update `01_research_stack.md` prices if drifted.

---

## Risks

| Risk | Mitigation |
|---|---|
| Provider API shape drift | thin clients, re-verify docs at build time, provider_meta for debug |
| Content moderation rejections (hosted models) | surface provider rejection reason verbatim on job error; document per-model quirks in registry blurbs |
| Cost surprises (per-video vs per-second billing) | estimates conservative (round up), $1 confirm threshold, hard budget |
| Veo/Sora access gating | rows ship disabled-if-no-provider-slug; enable as access confirms |
