# workspace/plan — Start Here (written 2026-07-15, re-ordered 2026-07-16)

Entry point for any agent picking up planned work. Every plan folder is self-contained
(read its `00_overview*.md` first); this file only adds the cross-plan ordering and the
human-dependency list that lives nowhere else.

> **`chat/` is done — cross-plan order is now: imageLab next.** All of chat/'s
> 2026-07-15/16 batch (F-1/F-2/F-3/F-6/F-7/F-8/F-9/F-10) plus F-11 (image attach +
> forced-SDXL session) shipped; see `workspace/implemented_phases/phase_13_chat_feature_fixes.md`
> and `workspace/implemented_phases/phase_F11_chat_io_formats.md` for the closed-out
> records. `chat/` stays as a folder for whatever gets planned there next.
> **videoLab is deferred — no plans to implement it for now; it will only be picked up
> at the very end**, once `imageLab/` is also done. Its plan files stay put
> in `videoLab/` untouched; nothing else in this workspace should reference it in the
> meantime.

## Recommended cross-plan order

**imageLab Q1, G1, and the vision-grounded prompt enhancement plan are all DONE** — see
`workspace/implemented_phases/phase_Q1_generation_fixes.md`,
`workspace/implemented_phases/phase_G1_generations_management.md`, and
`workspace/implemented_phases/plan_vision_prompt_enhancement.md` (its design was fully
implemented under imageLab Q3.1). What's left, in order:

1. **imageLab Q2** (`imageLab/phase_Q2_realism_models.md`) — realism checkpoints
   (Juggernaut/RealVis), deliberately deferred by the user until Q3's prompting work
   landed (it has — Q3.1/Q3.2/Q3.3 all done, only the optional Q3.4 negative-embeddings
   spike remains open). Now the natural point to revisit.
2. **imageLab open items** (`imageLab/open_items.md`) — I-1 (FLUX OOM) is done; I-2/I-3/
   I-4/I-5 remain, mostly gated on the user + a real Kaggle session or a deployment
   session.

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
- Vision prompt enhancement: confirm the currently-live free-tier Groq vision model id,
  whether enhancement is default-on for every generation or image-only, and where
  Groq-specific provider-pinning logic should live (`plan_vision_prompt_enhancement.md` §5).
- Manual Drive cleanup: merge duplicate "PAWN" root folders; delete orphaned
  `pawn-image-flux-1-schnell` kernel.
- Prod deploys (imageLab I-3) only in an explicit deployment session — standing instruction.

## Folder map

- `chat/` — no active plans (last batch shipped 2026-07-16, see
  `implemented_phases/phase_13_chat_feature_fixes.md` and
  `implemented_phases/phase_F11_chat_io_formats.md`); kept for future plans
- `imageLab/` — quality program: Q1 done (archived), Q2 open (deferred until now),
  Q3 mostly done (Q3.4 spike still open), G1 done (archived); Q4 dropped 2026-07-17.
  Open items I-1..I-5 in `open_items.md` (I-1 done).
- `plan_findings.md` — user's notepad, don't process without being asked
- History of completed plans → `workspace/implemented_phases/` (includes
  `phase_Q1_generation_fixes.md`, `phase_G1_generations_management.md`,
  `plan_vision_prompt_enhancement.md`, `phase_F11_chat_io_formats.md`,
  `plan_deployment_dev_to_main_promotion.md`)
