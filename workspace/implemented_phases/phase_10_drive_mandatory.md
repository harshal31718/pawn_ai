# Plan: Drive-Mandatory Storage (Remove Local-Storage Fallback)

## Context

Triggered by investigating a passphrase-gate 500 error: the user's Google
login didn't grant Drive (`drive.file`) scope, so `GET /crypto/salt` threw an
unhandled 403 from the Drive API, which the frontend showed as a generic
"could not reach the server." Rather than just patching that one route, the
user decided the local-filesystem fallback pattern itself should be removed
everywhere — Google Drive becomes the only storage backend for user data, no
exceptions.

**Reference commit:** `dev` @ `9350664e4e9f421e8d6388f7faa4f336fe49c439`
("feat: D.3+D.4 - migrate Supabase to self-hosted Postgres+pgvector+PostgREST")
is marked as the last-stable point in `workspace/stable_commits.md`. This plan
starts from there and is sequenced **before** the remaining deployment steps
(D.5–D.8 in `workspace/plan/plan_deployment.md`).

**Scope discovered while investigating:** the local-storage fallback isn't
dead code — it's what makes today's test suite pass without a real Drive
account. In every test, `get_drive_for_user()` naturally returns `None`
(no real Postgres/Drive connection in the test environment → caught
exception → `None`), which silently routes `test_chat.py`, `test_agent.py`,
`test_conversations.py`, `test_upload.py`, `test_summarize.py`, `test_rag.py`,
and `test_crypto.py` through local storage today, without any of them ever
mocking Drive. Removing the fallback without also fixing these tests would
break most of the suite.

Production files with the `if drive: ... else: local_storage...` branch:
`backend/app/routes/crypto.py`, `backend/app/routes/conversations.py`,
`backend/app/routes/upload.py`, `backend/app/routes/chat.py`,
`backend/app/memory/summarize.py`. Backing local-storage modules that become
dead code once these are rewritten: `backend/app/storage/conversations.py`,
`backend/app/storage/documents.py`.

## Decisions locked in (do not re-litigate)

1. Google Drive becomes mandatory for all user data — conversations, uploads,
   memory-summary indexing, and the encryption salt. No local-filesystem
   fallback anywhere in production code.
2. When Drive is unavailable for a request (not linked, insufficient OAuth
   scope, token decrypt failure, Drive API error), the request fails with a
   **clear per-request error** — reusing the existing `NotConfiguredError`
   pattern (`app/exceptions.py`, HTTP 412, `{"detail": ..., "code":
   "not_configured"}`) already used for "user must configure X" cases (e.g.
   missing Kaggle creds). No new exception class needed; `frontend/src/api/
   client.ts` already surfaces any `detail` field generically.
3. No app-wide "Connect Drive" gate screen — per-request errors only (smaller
   surface, matches the user's explicit choice over blocking the whole app
   upfront).
4. Tests must explicitly mock Drive as available (a fake/mocked
   `DriveStorage` + mocked `conversations_drive`/`documents_drive` module
   calls) rather than relying on the accidental "no real DB → None → local
   fallback" behavior every test currently depends on. This closes a real gap
   in the existing test design, not something newly broken by this change.
5. This work is sequenced before D.5–D.8 of the deployment plan. Where
   reasonable, deployment steps that don't depend on it (D.5, D.6) are folded
   in below so this doesn't block overall progress toward deploy.

## Phases

- [x] **Phase 1 — Backend: remove local-storage fallback, Drive becomes mandatory**
  Add `require_drive_for_user(user_id) -> DriveStorage` to
  `backend/app/core/drive_factory.py` — calls `get_drive_for_user`, raises
  `NotConfiguredError("Connect your Google Drive in Settings to use PAWN.")`
  if `None`. Rewrite every `if drive: ... else: local_storage...` branch to
  call `require_drive_for_user()` once and the `*_drive` module
  unconditionally:
  - `routes/crypto.py` — drop `_local_get_or_create_salt`/`_LOCAL_SALT_DIR`.
  - `routes/conversations.py` — drop the `local_storage` import; simplify
    `_list`/`_create`/`_get`/`_delete`/`_update`.
  - `routes/upload.py` — drop the local `store_doc` import; simplify `_store`.
  - `routes/chat.py` — drop the `local_storage` import; simplify
    `_load_conversation_bundle`/`_persist_turn`/`_create_with_id`/
    `auto_title_background_task`.
  - `memory/summarize.py` — drop the `local_storage` import in
    `summarize_conversation_task`.
  Delete `backend/app/storage/conversations.py` and
  `backend/app/storage/documents.py` once confirmed unreferenced.
  security-auditor runs (touches Drive-token/auth-adjacent code).

- [x] **Phase 2 — Tests: mock Drive as available everywhere it's implicitly relied on**
  New `backend/tests/fake_drive.py` — an in-memory `FakeDriveStorage`
  implementing DriveStorage's low-level primitives (`get_or_create_root`,
  `get_or_create_folder`, `find_file`, `upload_text`, `download_text(_by_name)`,
  `list_subfolders`, `delete_file`), so tests run the REAL
  `conversations_drive.py`/`documents_drive.py` logic against a fake in-memory
  tree rather than mocking each high-level function. `test_conversations.py`,
  `test_upload.py`, `test_summarize.py`, `test_rag.py`, `test_crypto.py`
  rewritten to patch `app.core.drive_factory.get_drive_for_user` (patching it
  at its defining module is enough for every route, since
  `require_drive_for_user` resolves it by bare name at call time — no need to
  patch each route module separately). New tests assert the 412
  `not_configured` error fires when Drive is unavailable
  (`test_conversations_require_drive_when_unavailable`,
  `test_upload_requires_drive_when_unavailable`,
  `test_salt_requires_drive_when_unavailable`,
  `test_salt_fails_clearly_on_drive_api_error`,
  `test_summarize_conversation_task_skips_when_drive_unavailable`).
  `test_chat.py`/`test_agent.py` needed no changes — neither ever sets
  `conversation_id`/`doc_id` against the real `/chat` route in a way that
  requires Drive (chat.py only requires Drive when persistence or an
  uploaded doc is actually requested).
  **Verified manually against the live stack** (docker compose up --build,
  full backend+frontend+postgres+postgrest), not via the automated pytest
  suite — confirmed by the user: stateless chat unaffected, conversations/
  uploads/salt work when Drive is linked, and a request without Drive access
  returns the clear 412 instead of a 500. Automated `pytest` run was
  explicitly skipped this pass per user instruction; re-run it before the
  next step that depends on full suite coverage (D.6's pre-deploy test gate,
  Phase 3 below, already plans to run it).

  **Related fixes made alongside Phase 1/2 (not originally scoped, found
  during manual testing):**
  - Removed the Phase 3 encryption passphrase gate from `App.tsx`'s
    `AuthGate` entirely (deleted `frontend/src/pages/PassphraseGate.tsx`) —
    it unconditionally blocked the whole app after login, but the actual
    encrypt/decrypt-on-write wiring was deferred (see
    `implemented_phases/phase_8_encryption.md`), so it was pure friction for
    a feature that encrypted nothing. The crypto module and backend salt
    endpoint stay in the codebase, unused, for whenever encryption is
    properly wired up.
  - Renamed `supabase/` → `postgres/` (`schema.sql` + `init_pawn_anon.sh`) —
    the old name was actively misleading once Supabase was fully dropped in
    D.3/D.4. Updated `docker-compose.yml`'s two volume mounts and every
    docstring/doc reference to the old path. Verified live: a fresh Postgres
    volume still bootstraps correctly (pgcrypto, `pawn_anon` role with
    LOGIN, `image_jobs.params` column) from the renamed files.

- [ ] **Phase 3 — Fold in D.5 + D.6 from the deployment plan**
  - **D.5** — Clean-`main` mechanism. Original `.gitattributes merge=ours`
    plan **tested and abandoned** (never consulted for the modify/delete case →
    conflicts on every `dev`→`main` merge that touched a doc). Replaced by a
    committed `scripts/promote-to-main.sh` (normal merge + unconditional strip
    of `.claude/`, `workspace/`, `CLAUDE.md`/`AGENTS.md`; keeps `README.md`),
    proven clean/repeatable against a real repo clone (39 doc paths → 0, 123
    code files preserved). Script **created**; the first real run against
    `main` is deferred to the staging-first deploy (D.8), not run standalone.
    `dev`→`main` must always go through this script. See `plan_deployment.md`
    D.5.
  - **D.6** — Pre-deploy test gate. **Automated portion done:** full `pytest`
    green (152 passed), `npm run build` clean, and the "412 `not_configured`
    when Drive unavailable" behavior is covered by the (now-run) suite. **Still
    outstanding (manual, needs a real linked Google account):** live
    Drive-mandatory flow end-to-end (salt fetch, conversation persistence,
    upload, BYOK key storage) plus confirming a Drive-less request returns the
    clear 412 instead of a raw 500 — to be run on the local stack (already up)
    or on staging.

- [ ] **Phase 4 — Review, docs, commit**
  code-reviewer + security-auditor + build-validator across the combined
  Phase 1–3 diff. Update `workspace/current_state.md`,
  `workspace/status/dev_log.md`, `workspace/status/build_tracker.md`; mark
  D.5/D.6 `[x]` in `plan_deployment.md`. Commit. This leaves D.7/D.8 (the
  actual live deploy) as the next step, still gated on
  `plan_deployment.md`'s working agreement to pause for confirmation there.

## Critical files

- `backend/app/core/drive_factory.py` (Phase 1 — new `require_drive_for_user`)
- `backend/app/routes/crypto.py`, `conversations.py`, `upload.py`, `chat.py`,
  `backend/app/memory/summarize.py` (Phase 1)
- `backend/app/storage/conversations.py`, `backend/app/storage/documents.py`
  → deleted (Phase 1)
- `backend/tests/test_chat.py`, `test_agent.py`, `test_conversations.py`,
  `test_upload.py`, `test_summarize.py`, `test_rag.py`, `test_crypto.py`
  (Phase 2)
- New `.gitattributes` (Phase 3 / D.5)
- `workspace/plan/plan_deployment.md`, `workspace/status/build_tracker.md`
  (Phase 3/4 — D.5/D.6 tracked there too)

## Working agreement

Implement phases sequentially; tests pass before moving to the next phase;
update `workspace/current_state.md` and `workspace/status/build_tracker.md`
after each phase. Pause for confirmation before D.7/D.8 (the live deploy), per
`plan_deployment.md`'s existing working agreement — unaffected by this plan.

## Open question raised outside this plan (resume-writing session, 2026-07-06)

"Decisions locked in" item 1 above lists **memory-summary indexing** as part of
what's Drive-mandatory. But per SM-1/D.3+D.4, the actual RAG-searchable
representation (embedded chunks inserted via `memory/index.py`'s `add_chunk`)
lives in the self-hosted Postgres/pgvector table, not Drive — Drive can't run
vector/FTS queries. So either (a) "memory-summary indexing" here only ever
meant the raw rolling-summary text file per conversation (Drive-stored), and
the pgvector chunk index is a separate, intentionally-additional system not
covered by this plan's "Drive is the only backend" claim — or (b) this plan's
scope statement is stale/imprecise now that the pgvector index exists.
`project_overview.md`'s pitch ("the platform stores nothing, all memory lives
on Drive") has the same gap. Worth reconciling the wording in both docs so the
Drive-mandatory claim's actual scope is unambiguous — not urgent, not
blocking, just flagging so it doesn't get treated as a settled non-issue.
