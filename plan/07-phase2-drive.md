# Phase 2 — Google Drive
## Conversation Logs, Memory File, Uploaded Docs on Drive

---

## Prerequisite

Phase 1.6 merged to main and verified before Phase 2 starts.

---

## Goal

Replace local `data/` storage with the user's own Google Drive. The platform stores
nothing permanently. All personal data — conversations, memory, uploaded documents,
API key configs — lives on Drive under a dedicated `PAWN/` folder.

The user owns their data completely. They can open, read, and delete it in Google Drive
directly. PAWN is purely an interface.

---

## Why Drive, Not a Database

- Zero server storage cost
- User retains ownership and control
- No vendor lock-in — data is readable without PAWN
- Aligns with the BYOK principle: user's API keys, user's compute, user's storage
- Encryption (Phase 3) can be applied to Drive files without changing the storage layer

---

## Drive Folder Structure

```
PAWN/                              ← created on first run if absent
  conversations/
    <uuid>/
      meta.json
      messages.jsonl
      summary.md
  memory/
    index.json
  registry/
    models.json                    ← user can edit to add custom models
    endpoints.json                 ← user can edit to add custom endpoints
  uploads/
    <doc_id>.txt                   ← plain text extracted from uploads
```

---

## Auth

Phase 2 uses a **personal Google token**, not Google OAuth2 multi-user flow.
This is the single-user phase. The user:
1. Creates a Google Cloud project, enables Drive API
2. Downloads OAuth2 credentials (`credentials.json`)
3. Runs a one-time auth flow locally → `token.json` saved to `secrets/`
4. PAWN mounts `token.json` as a Docker secret and uses it for all Drive calls

Multi-user OAuth2 comes in Phase 4. Phase 2 is single-user, personal token only.

---

## Step P2-1 — Wire Google Drive API + Conversation Logs

**Goal:** conversations read/written to Drive instead of local `data/conversations/`.
Local `data/` is still kept as a cache (write-through). On startup, sync from Drive.
**Demo:** stop and restart the container. Conversations still there. Open Drive → see the files.

Add to requirements.txt: `google-api-python-client`, `google-auth-httplib2`, `google-auth-oauthlib`

`backend/app/storage/drive.py`:
```python
class DriveStorage:
    def __init__(self, token_path: str):
        creds = Credentials.from_authorized_user_file(token_path)
        self._service = build("drive", "v3", credentials=creds)
        self._pawn_folder_id = self._ensure_folder("PAWN")

    def write_file(self, path: str, content: str) -> None:
        # path is relative to PAWN/ (e.g. "conversations/uuid/meta.json")
        # creates intermediate folders as needed
        ...

    def read_file(self, path: str) -> str | None: ...
    def list_folder(self, path: str) -> list[str]: ...
    def delete_file(self, path: str) -> None: ...
```

`app/storage/conversations.py` updated:
- Writes to both local `data/` and Drive
- On startup (`initialize_managers`): sync conversations from Drive to local if local is empty

New secret: `secrets/drive_token.json` (the personal OAuth2 token file).

Tests: drive writes are called on conversation create/append/delete (Drive client mocked).

Commit: `feat: Google Drive storage — conversations written to Drive`

---

## Step P2-2 — Memory File on Drive

**Goal:** user memory file (`PAWN/memory/user_memory.md`) lives on Drive. Contains user
preferences, ongoing projects, and key facts that the AI should always know.
**Demo:** add a preference in the memory file directly in Drive. Open a new chat — AI
references it without being asked.

`PAWN/memory/user_memory.md` (plain Markdown, user-editable):
```markdown
# My Preferences
- Prefer concise, bullet-point answers
- Working on a FastAPI + React project called PAWN

# Ongoing Projects
- PAWN: personal AI workspace with multi-provider failover

# Key Facts
- Name: Priya
- Timezone: IST (UTC+5:30)
```

Backend:
- `app/memory/user_memory.py` — `load_user_memory() -> str`; reads from Drive, cached in memory
- Injected as a system message before every request (prepended to context)
- Refreshed from Drive every N minutes (configurable, default 5)

No UI for editing yet — user edits the file directly in Google Drive.

Tests: memory file load, injection into context, cache refresh.

Commit: `feat: user memory file on Drive — auto-injected as context`

---

## Step P2-3 — Uploaded Docs on Drive

**Goal:** uploaded documents stored on Drive instead of in-memory dict.
**Demo:** upload a PDF, restart the container. Ask about it — AI still has it.

Current state: `app/storage/documents.py` is an in-memory dict. Lost on restart.

Updated flow:
1. `POST /upload` → extract text (pypdf for PDF, raw for txt)
2. Write text to `PAWN/uploads/<doc_id>.txt` on Drive
3. Return `doc_id`
4. On `/chat` with `doc_id`: read from Drive (or local cache if recently uploaded)

`app/storage/documents.py` updated:
- `store_doc(doc_id: str, text: str)` → write to Drive + local cache
- `load_doc(doc_id: str) -> str` → check local cache first, then Drive

Tests: upload roundtrip to Drive (mocked), load from cache, load from Drive on cache miss.

Commit: `feat: uploaded docs persisted to Drive`

---

## Phase 2 Completion Checklist

- [ ] Conversations persist across container restarts (stored on Drive)
- [ ] `PAWN/` folder created in user's Google Drive on first run
- [ ] Uploaded documents survive container restarts
- [ ] User memory file auto-loaded and injected into context
- [ ] Memory file changes on Drive reflected within N minutes
- [ ] No data stored on the server beyond an in-session cache
- [ ] `secrets/drive_token.json` mounted correctly (not committed)
- [ ] All backend tests pass
