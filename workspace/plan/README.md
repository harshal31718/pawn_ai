# workspace/plan — Start Here (written 2026-07-15)

Entry point for any agent picking up planned work. Every plan folder is self-contained
(read its `00_overview*.md` first); this file only adds the cross-plan ordering and the
human-dependency list that lives nowhere else.

> **Top recommendation: start with imageLab Q1** — it's the smallest diff with the biggest
> visible payoff (kills the half-generated/black/unreal image flaws), and its notebook
> recipes (resolution buckets, VAE fix, scheduler) feed straight into videoLab's templates.

## Recommended cross-plan order

1. **imageLab Q1** (`imageLab/phase_Q1_generation_fixes.md`) — smallest diffs, biggest
   user-visible win (fixes half-generated/black/soft images). Do before videoLab: the
   notebook recipes (buckets, VAE, scheduler) carry into videoLab templates, and videoLab's
   "Animate" feature consumes imageLab output.
2. **imageLab I-1** (`imageLab/open_items.md`) — FLUX OOM: rebase `worktree-flux-oom-fix`,
   live-verify, merge. Quick, already written.
3. **imageLab Q2 → Q3 → Q4** — realism checkpoints, prompting, polish.
4. **videoLab V1 → V4** (`videoLab/`) — skip V5 unless GPU budget is zero (see v2 §3.8).
5. **videoLab 2.0 P1 → P2 → P4 → P6-core → P3 → P5 → P7** (`videoLab/v2/`).
6. **F-1 / F-2** (`plan_feature_additions_2026-07-15.md`) — anytime as filler; F-2 needs a
   user decision first (below).

## Rules that apply to ALL of it

- Branch `dev`, additive only — the working tree is deployed; never refactor live paths.
- Use the `build-step` skill per numbered step; register steps in
  `workspace/status/build_tracker.md` before starting (plans are registered there already).
- Research files (`01_research_*.md`) carry prices/model availability as of 2026-07-15 —
  re-verify with a web search at the start of each phase.
- Quality claims need the fixed-seed benchmark A/B (imageLab Q1.5 defines it).

## Needs the USER, not an agent (blockers to surface early)

- Kaggle creds + a restarted cloudflared tunnel for ALL live verifications
  (imageLab I-2/I-4, Q-phase A/Bs, videoLab V1.5/V2.4).
- Publishing Kaggle weight datasets (one-time per model: Wan2.2-5B, Juggernaut, RealVis…).
- F-2 decision: search-tab model switcher — lock-with-tooltip vs switchable.
- videoLab 2.0: fal/Replicate/RunPod keys + a monthly budget number (P1 default $25).
- Manual Drive cleanup: merge duplicate "PAWN" root folders; delete orphaned
  `pawn-image-flux-1-schnell` kernel.
- Prod deploys (imageLab I-3) only in an explicit deployment session — standing instruction.

## Folder map

- `imageLab/` — quality program Q1–Q4 + open items (I-1..I-5)
- `videoLab/` — free-tier video gen V1–V6 (+ `v2/` premium tier P1–P7)
- `plan_feature_additions_2026-07-15.md` — F-1..F-5 (F-3 done; F-4/F-5 parked)
- `plan_findings.md` — user's notepad, don't process without being asked
- History of completed plans → `workspace/implemented_phases/`
