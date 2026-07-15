# Plan: Feature Additions (from user findings triage, 2026-07-15)

*Source: the five raw items in `plan_findings.md`, each verified against the current dev
tree before planning (chat has NO image tool in `agent/tools/`; `ModelSwitcher` renders only
when `MessageInput` gets model props — the search tab doesn't pass them; the cold-generate
guard only blocks when a warm session IS live, by design). Findings notepad reset; this file
is the structured outcome.*

**Ground rules: dev is working — every item is ADDITIVE (new tool, new prop, new doc, new
script). No refactors of working paths, no new lettered phases; each item is a standalone
mini-plan sized for one or two build-step runs.**

---

## F-1 — Image generation from chat (finding #1) — RECOMMENDED, medium

**Decision embedded in this plan (was the open question):** keep the Image Lab as the home
for sessions/browsing, and ADD a chat-side `generate_image` agent tool — this is imageLab's
long-deferred "Milestone B (chat composer integration)", now cheap because the agent tool
layer (A.2) and the job layer both exist.

Steps:
1. New `backend/app/agent/tools/generate_image.py` — ToolSpec `generate_image(prompt,
   model='sdxl')`: routes EXACTLY like the Lab (warm session first via
   `submit_session_job`, else cold via `create_cold_job` — reuse, zero new job logic),
   returns `job_id` + a one-line "generation started" observation immediately (never blocks
   the tool loop on a multi-minute render). Gated in `registry.py` on saved Kaggle creds
   (same pattern as `web_search`'s key gating).
2. Frontend: chat messages learn one new trace/citation-style element — an image-job chip
   that polls `GET /generate/job/{id}` (reuse client helpers) and swells into the image
   inline when done. No composer button needed v1 — the agent decides when the user asked
   for an image (cheaper UX than a mode toggle, and matches PAWN's agentic direction).
3. Tests: tool spec/gating/dispatch (mocked job layer); one route-level integration test.
   `npm run build` clean. security-auditor not required (no new secret surface).

Also closes finding #1's first half: cold "generate once" STAYS (it's the no-session path
the tool itself uses). The reported "cold not working without session" could not be
reproduced in code review — if it recurs, capture the error box text and treat as a bug
report against `create_cold_job`, not a design question.

## F-2 — Model switcher missing in search tab (finding #3) — RECOMMENDED, small

`MessageInput` hides `ModelSwitcher` when `models`/`selectedProvider`/`onChangeProvider`
props are absent — the search-tab usage doesn't pass them (verified). Fix: pass the same
three props from the search-tab render site (find via `grep -rn "<MessageInput"`); if the
search tab intentionally locks the model, render the switcher disabled with a tooltip
instead of hiding it (honest UI beats vanishing controls). One file + `npm run build`;
confirm with the user which behavior was intended before choosing lock-vs-switch.

## F-3 — "Drive-mandatory" wording reconciliation (finding #5) — RECOMMENDED, docs-only

Reality (verified in code): Drive is the durable source of truth (chats, `rag_chunks.jsonl`,
uploads manifest) and the rebuild source; pgvector/Postgres is a rebuildable derived index —
`rebuild_index` re-derives it from Drive. The stale claim is docs saying "Drive is the only
backend" as if no Postgres index existed. Fix: one clarifying paragraph ("Drive = durability,
Postgres = derived search index, rebuildable from Drive") applied to `project_overview.md`'s
pitch + `phase_10_drive_mandatory.md` header + anywhere
`grep -ril "drive.mandatory" workspace/` still overstates it. No code.

## F-4 — Private+public repo mirror (finding #4) — OPTIONAL ops runbook, no code

Useful only when PAWN goes public. Distilled runbook (replaces the pasted chat log):
`git remote rename origin private` → `git remote add public <url>` → work/push to
`private` as today → publish = `git push public main` only. Rules: never `git push --all`;
identical `.gitignore` both sides; squash-merge to keep private notes out of public history.
PAWN-specific note: `scripts/promote-to-main.sh` already strips workspace docs from `main` —
the public remote should track `main` ONLY, making the existing script the safety layer.
Action when activated: add `scripts/publish-public.sh` (thin wrapper: verify branch==main,
verify no `secrets/`/`workspace/` paths in tree, push public). Until then: no action.

## F-5 — Kaggle-hosted models via notebook-as-API (finding #2) — BACKLOG, assessed

The idea (run LLMs on Kaggle kernels, or proxy Kaggle-provided model APIs through a
notebook, as a free provider for PAWN chat) is technically proven by imageLab's warm
serve-loop — a `textlab` session would be the same rendezvous with tokens instead of PNGs.
Honest assessment: low value today — PAWN's BYOK provider layer already gives free-tier
LLMs (Groq/Cerebras/Gemini-class) with failover, at far lower latency than a Kaggle kernel
round-trip, without burning the 30 GPU-hrs/week that imageLab/videoLab need. Revisit ONLY
if: free API tiers collapse, or a Kaggle-exclusive open model matters. If activated, it's
"videoLab plan §V2 with a text serve-loop" — no new research needed. Parked.

---

## Suggested order

F-2 (smallest, user-visible) → F-3 (docs) → F-1 (the real feature) → F-4/F-5 stay parked.
Register only the picked items in `build_tracker.md`; update `current_state.md`/`dev_log.md`
per step as usual.
