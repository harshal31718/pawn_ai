# Phase 4 — Multi-User / Auth
## Google OAuth2, Multi-User Sessions, Subagent Routing

---

## Prerequisite

Phase 3 merged and verified. The single-user encrypted Drive version is stable before
introducing multi-user concerns.

---

## Goal

Make PAWN usable by multiple users independently. Each user:
- Authenticates via Google OAuth2
- Has their own Drive folder (`PAWN/` in their personal Drive)
- Has their own API keys (still BYOK)
- Has completely isolated data from other users

The server still stores nothing. Each user's data is in their own Google Drive.

---

## What Changes from Phase 1–3

| Concern | Phase 1–3 (single-user) | Phase 4 (multi-user) |
|---|---|---|
| Auth | None | Google OAuth2 session cookies |
| Drive token | Personal `token.json` in secrets | Per-user OAuth2 token from login flow |
| API keys | Shared Docker secrets | Per-user, stored encrypted on their Drive |
| Data isolation | N/A (one user) | Per-user Drive folder; server never cross-reads |
| Rate limits | Shared in-memory counters | Per-user in-memory counters (keyed by user_id + endpoint_id) |

---

## Step P4-1 — Google OAuth2 + Multi-User Sessions

**Goal:** users log in via Google; each gets their own isolated Drive-backed workspace.
**Demo:** open two different browser profiles as different Google accounts.
Each sees only their own conversations.

### Auth Flow

1. User clicks "Sign in with Google"
2. Backend redirects to Google OAuth2 consent screen
3. User grants Drive access
4. Google redirects back with an auth code
5. Backend exchanges code for access + refresh tokens
6. Tokens stored in a server-side session (encrypted, keyed by session cookie)
7. All subsequent Drive calls use the user's own OAuth2 tokens

This is the first time sessions exist in PAWN. A simple signed cookie (not a DB-backed
session table). Session data is ephemeral — on logout or expiry, the user signs in again.

**Required scopes:**
- `https://www.googleapis.com/auth/drive.file` — access only files PAWN created
- `openid email profile` — identify the user

### API Key Migration

In Phase 1–3, API keys are Docker secrets (shared). In Phase 4:
- Users enter their own API keys via a Settings panel in the UI
- Keys are encrypted with their passphrase and stored in `PAWN/config/keys.enc` on their Drive
- Backend reads them per-request from the user's Drive (cached in session, refreshed on key change)

Docker secrets remain as fallback / development mode only.

### Per-User Rate Limit State

`EndpointRateLimiter` changes from a flat `endpoint_id` key to a composite
`(user_id, endpoint_id)` key. Users on the same provider have independent quota tracking —
their API keys are different, so their quotas are different.

### Session Management

```python
# app/core/session_manager.py

class UserSession:
    user_id: str
    email: str
    oauth_tokens: dict   # access + refresh token
    api_keys: dict       # decrypted per-provider keys (in-memory cache)
    drive: DriveStorage  # Drive client for this user's tokens

class SessionManager:
    def get_session(self, session_cookie: str) -> UserSession | None: ...
    def create_session(self, oauth_tokens: dict, user_info: dict) -> str: ...  # returns cookie
    def invalidate_session(self, session_cookie: str) -> None: ...
```

### Routes

- `GET  /auth/login`    → redirect to Google OAuth2 consent screen
- `GET  /auth/callback` → exchange code → create session → redirect to app
- `POST /auth/logout`   → invalidate session → redirect to login
- `GET  /auth/me`       → current user info (`{email, name, picture}`)

Tests: auth callback (mocked Google response), session creation, session expiry.

Commit: `feat: Google OAuth2 — multi-user sessions with per-user Drive isolation`

---

## Step P4-2 — Subagent Routing + Settings Panel

**Goal:** the agent routes sub-tasks to specialised "agents" by capability level and tag.
The user can configure their own agents with custom system prompts.
**Demo:** set up a "Coding Agent" with a coding-focused system prompt.
Ask a coding question → trace panel shows coding agent handling the sub-task.

### Settings Panel

`src/components/Settings.tsx`:
- API Keys tab: one field per provider; masked; validated on save; encrypted before writing to Drive
- Agents tab: list of custom agent configurations
- Each agent: name, system prompt, capability level, capability tags
- Default agents pre-configured: General, Coding, Research, Writing

### Custom Agent Schema

```json
{
  "id": "agent-coding-01",
  "name": "Coding Agent",
  "system_prompt": "You are an expert software engineer. Always include working code examples.",
  "capability_level": "balanced",
  "preferred_tags": ["coding"],
  "active": true
}
```

Stored at `PAWN/config/agents.json` on Drive (encrypted).

### Capability + Tag Routing

The resolver gains tag-aware routing:

```python
def pick_by_capability_and_tags(
    self,
    level: str,
    preferred_tags: list[str],
    user_id: str,
) -> list[tuple]:
    # Find models matching the level AND having overlap with preferred_tags
    # Fall back to level-only match if no tag match
    ...
```

Agent node selects the appropriate agent configuration based on the current sub-task purpose,
then calls `resolver.pick_by_capability_and_tags` with that agent's `preferred_tags`.

Commit: `feat: subagent routing + settings panel — per-user agent configuration`

---

## Phase 4 Completion Checklist

- [ ] Google OAuth2 login/logout flow works
- [ ] Each user sees only their own conversations
- [ ] Each user's API keys stored encrypted on their own Drive
- [ ] Rate limit counters are per-user (different users don't share quota)
- [ ] Settings panel: API key entry, masked, save/update works
- [ ] Custom agent configurations saved to Drive
- [ ] Agent routes sub-tasks by capability level + tags
- [ ] Two users in different browser profiles see fully isolated workspaces
- [ ] Session expiry and refresh token flow works
- [ ] All backend tests pass
