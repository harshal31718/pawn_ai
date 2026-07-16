# Chat — Open & Parked Items

**Status:** PLANNED / DONE. **Branch:** `dev`. **Folder:** `workspace/plan/chat/`
**Date:** 2026-07-15

This file tracks the remaining feature additions that are either completed, optional, or parked.

---

## F-3 — Drive-mandatory Wording Reconciliation — DONE (2026-07-15)

- Clarified wording in the docs to define Drive as the durable source of truth (chats, `rag_chunks.jsonl`, upload manifest) and Postgres as the derived rebuildable index.
- Applied to [project_overview.md](file:///c:/Users/harsh/Desktop/PAWN/workspace/decisions/project_overview.md) and [phase_10_drive_mandatory.md](file:///c:/Users/harsh/Desktop/PAWN/workspace/implemented_phases/phase_10_drive_mandatory.md).

---

## F-4 — Private + Public Repo Mirror — OPTIONAL (Ops Runbook)

- Useful when PAWN goes public.
- Runbook:
  - `git remote rename origin private`
  - `git remote add public <url>`
  - Publish to public: `git push public main` only.
- Safety: `scripts/promote-to-main.sh` already strips workspace docs from `main`.

---

## F-5 — Kaggle-hosted LLM API — PARKED

- Run LLMs on Kaggle kernels as a free provider for PAWN chat.
- Assessed as low value today because PAWN's BYOK provider layer already gives fast, free-tier LLMs with failover (Groq, Cerebras, Gemini) at much lower latency than a Kaggle round-trip.
- Revisit only if free API tiers collapse or a Kaggle-exclusive model is needed.
