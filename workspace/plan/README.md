# workspace/plan — Start Here (written 2026-07-15, re-ordered 2026-07-16)

Entry point for any agent picking up planned work. Every plan folder is self-contained
(read its `00_overview*.md` first); this file only adds the cross-plan ordering and the
human-dependency list that lives nowhere else.

> **Top recommendation: start with `chat/`.** Cross-plan order is now: **chat → imageLab**.
> **videoLab is deferred — no plans to implement it for now; it will only be picked up
> at the very end**, once `chat/` and `imageLab/` are both done. Its plan files stay put
> in `videoLab/` untouched; nothing else in this workspace should reference it in the
> meantime.

## Recommended cross-plan order

1. **chat/ F-9** (sidebar scroll bug) — **fixes already applied in code 2026-07-15**,
   only needs live re-verification. **F-1 / F-2 / F-6 / F-7 / F-8 / F-10** — remaining
   filler/feature items in `chat/`, see its own `00_overview.md` for order.
2. **imageLab Q1** (`imageLab/phase_Q1_generation_fixes.md`) — smallest diffs, biggest
   user-visible win (fixes half-generated/black/soft images).
3. **imageLab I-1** (`imageLab/open_items.md`) — FLUX OOM: rebase `worktree-flux-oom-fix`,
   live-verify, merge. Quick, already written.
4. **imageLab Q2 → Q3 → Q4** — realism checkpoints, prompting, polish. Q3.1's enhancer
   mechanics are superseded by `plan_vision_prompt_enhancement.md` (below) — build the
   shared vision plumbing there first if Q3 is picked up after it lands.
5. **Vision-grounded prompt enhancement** (`plan_vision_prompt_enhancement.md`) — imageLab
   plumbing (image+prompt → vision-model refine → generation model, Groq→Gemini→raw
   chain); build before/alongside imageLab Q3 once its 3 open questions are answered.
   (The plan file's own text also scopes a videoLab reuse of this plumbing — out of
   scope until videoLab is picked back up; treat those sections as parked, not active.)

**videoLab — deferred to the very end, not currently planned for implementation.** Its
plan folder (`videoLab/`, phases V1–V6, and `videoLab/v2/`, phases P1–P7) stays exactly
where it is with no code-side dependency on it; once `chat/` and `imageLab/` are fully
done, revisit `videoLab/00_overview.md` to resume. At that point the user intends to
move the `videoLab/` folder out of this application entirely, so treat anything inside
it as self-contained and not to be cross-referenced from other plan files.

## Rules that apply to ALL of it

- Branch `dev`, additive only — the working tree is deployed; never refactor live paths.
- Use the `build-step` skill per numbered step; register steps in
  `workspace/status/build_tracker.md` before starting (plans are registered there already).
- Research files (`01_research_*.md`) carry prices/model availability as of 2026-07-15 —
  re-verify with a web search at the start of each phase.
- Quality claims need the fixed-seed benchmark A/B (imageLab Q1.5 defines it).

## Needs the USER, not an agent (blockers to surface early)

- Kaggle creds + a restarted cloudflared tunnel for ALL live verifications
  (imageLab I-2/I-4, Q-phase A/Bs).
- Publishing Kaggle weight datasets (one-time per model: Juggernaut, RealVis…).
- F-2 decision: search-tab model switcher — re-verify it still reproduces before
  deciding lock-with-tooltip vs switchable (didn't reproduce against current code as
  of 2026-07-15).
- Vision prompt enhancement: confirm the currently-live free-tier Groq vision model id,
  whether enhancement is default-on for every generation or image-only, and where
  Groq-specific provider-pinning logic should live (`plan_vision_prompt_enhancement.md` §5).
- Manual Drive cleanup: merge duplicate "PAWN" root folders; delete orphaned
  `pawn-image-flux-1-schnell` kernel.
- Prod deploys (imageLab I-3) only in an explicit deployment session — standing instruction.

## Folder map

- `chat/` — feature additions + bug fixes F-1/F-2/F-6..F-10 + open items
- `imageLab/` — quality program Q1–Q4 + open items (I-1..I-5)
- `plan_vision_prompt_enhancement.md` — imageLab vision-grounded prompt-enhancement
  plumbing (supersedes imageLab Q3.1 mechanics)
- `plan_findings.md` — user's notepad, don't process without being asked
- History of completed plans → `workspace/implemented_phases/`
