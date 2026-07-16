# Phase F-2 — Model Switcher Missing in Search Tab

**Status:** NEEDS RE-VERIFICATION (see §3) — not ready to build as originally written.
**Branch:** `dev`. **Folder:** `workspace/plan/chat/`
**Date:** 2026-07-15 (recovered from the deleted `plan_feature_additions_2026-07-15.md`
during the `chat/` folder reorg); **re-verified against current `dev` code 2026-07-15**
during this refinement pass.

## 1. Original finding

`MessageInput` hides `ModelSwitcher` when `models`/`selectedProvider`/`onChangeProvider`
props are absent. The original 2026-07-15 triage claimed "the search tab" render site
doesn't pass them, so the model switcher silently vanishes there.

## 2. Original proposed fix

Pass the same three props from the search-tab render site; if the search tab
intentionally locks the model, render the switcher disabled with a tooltip instead of
hiding it (honest UI beats vanishing controls). One file + `npm run build`; confirm with
the user which behavior was intended before choosing lock-vs-switch.

## 3. Re-verification result — the premise no longer matches the code

Grepped every `<MessageInput` render site in `frontend/src` (2026-07-15):

- `ChatPage.tsx:524` (draft/empty state) — passes `models`/`selectedProvider`/`onChangeProvider`.
- `ChatPage.tsx:555` (active chat) — passes all three.
- `ProjectPage.tsx:117` — passes all three.

There is no fourth render site and no dedicated "search tab"/"search page" component in
`frontend/src/pages/`. The sidebar's search box (`Sidebar.tsx`) only ever swaps in
`SearchResults` (a list of matched chats/projects to click into) — it never renders a
`MessageInput` itself. **Either this was already fixed by an earlier session (Phase A/M
frontend work touched `ChatPage.tsx` extensively), or the original finding described a
transient/reproduction-specific state (e.g. immediately after clicking a search result,
before `selectedProvider`/`availableModels` finish loading) rather than a structurally
missing prop.**

## 4. Before building anything

Do not implement the original fix blind — the file-level bug it describes isn't there
today. Ask the user to reproduce it live (which exact screen/flow, and does the switcher
reappear on reload) so the actual trigger (if any) can be pinned down, or drop this item
if it's stale. Given the small size, this is fine as a filler item once re-confirmed —
just not "recommended" at its original confidence level anymore.

## 5. Re-confirmed 2026-07-16 — not a bug, closed

User's concrete concern: with a Groq key configured, models like
`llama-3.1-8b-instant`/`gpt-oss-20b` seemed to be missing from the switcher. Traced live
via Chrome against the real stack:

- Settings showed Google/Groq/Kaggle/HuggingFace/GitHub Models/Tavily all configured,
  **OpenRouter not configured**.
- Opened the switcher: both named example models were actually present and correctly
  grouped (Fast tier). Counted the full dropdown (12 models) against the registry's 18
  active user-facing models — the 6 missing ones (`north-mini-code`, `hy3`, `laguna-xs`,
  `laguna-m`, `nemotron-3-ultra`, `nemotron-3-nano-omni-reasoning`) are exactly, and only,
  the models whose sole provider is OpenRouter.
- `AppContext.tsx`'s `availableModels = models.filter((m) => m.providers?.some((p) =>
  configuredProviders.includes(p)))` is working exactly as designed — a model with no
  configured provider can't actually be called, so hiding it from the picker is correct,
  not a bug.
- Confirmed the backend orchestrator is NOT more restrictive than this: `Resolver.
  pick_model_by_capability` (used by the orchestrator/execute-loop/final-synthesis/
  subagents, per F-6's investigation this same session) iterates the full
  `registry.user_models()` list independent of anything the frontend chose to display —
  it has the identical BYOK constraint (no key ⇒ genuinely can't call that provider), just
  applied per-model instead of the frontend's per-provider pre-filter. Adding an
  OpenRouter key would surface those 6 models in the picker AND make them available to
  the orchestrator simultaneously, no code change needed either way.

**Verdict: not a bug — closed.** No code changes made. If the user later wants unconfigured-
provider models shown-but-locked (a discovery aid) instead of hidden, that's a real, scoped
feature request for a future session, not a fix to this one.
