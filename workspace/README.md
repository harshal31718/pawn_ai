# workspace/ — Docs Index

Everything here lives on `dev` only (`scripts/promote-to-main.sh` strips `workspace/` from `main`).
Two audiences. Keep them separate.

## For the human owner (current picture only, no history)

| File | Content |
|---|---|
| `OVERVIEW.md` | What PAWN is, where it runs, how to release, risks, chores |
| `../README.md` | Project description / tech overview |
| `../deployment.md` | GCP runbook: VM, Nginx, secrets, Postgres, backups, rollback |

When something changes, rewrite the stale lines in these files. Do not append history.

## For AI agents (Claude, Gemini, others)

Read in this order before working: `current_state.md` -> `status/build_tracker.md` (top block) -> the relevant plan -> `../.claude/rules/*`.

| File | Content | Update rule |
|---|---|---|
| `current_state.md` | Short snapshot: prod, branches, features, open issues | Replace stale lines after every step |
| `CODEBASE_MAP.md` | Module map, data flow, API reference (sec. 6), storage, config, sharp edges | Update when code structure/API changes |
| `decisions/change_log_2026.md` | Decision -> action -> why log | Add an entry when a decision or infra change needs its reasoning kept |
| `decisions/*.md` (others) | Original design records (some marked superseded); `sse_protocol.md`, `provider_layer.md` still broadly valid | Do not rewrite; add a banner if superseded |
| `schemas/` | Provider/model schema design (model schema not implemented) | |
| `status/build_tracker.md` | Step ledger. Read the CURRENT STATUS block at the top; the rest is chronological and has stale statements | Add rows per step |
| `status/dev_log.md` | Dated history (mostly newest-first; the 2026-10-30 entry was appended at the bottom of the file) | Add a dated entry per step |
| `stable_commits.md` | Last known-good commit per branch | Only when the user says so |
| `plan/` | Active plans (README has the order) | |
| `implemented_phases/` | Closed-out plans and retrospectives (history) | Read-only history |
| `archive/` | Superseded long-form docs (old `current_state.md`) | Read-only |
| `plan/plan_findings.md` | The owner's private notepad | Do not process unless asked |
| `learn/` | Owner's learning material, gitignored | Ignore |

Agent config lives outside this folder: `../CLAUDE.md`, `../AGENTS.md` (root pointers), `../.claude/` (CLAUDE.md, AGENTS.md, rules, agents, skills, settings), `../.gemini/GEMINI.md` (pointer).
