<!-- LAST STABLE COMMIT: 306e41f9c47415800bd7dbfaa2eade37789ad2c7 (306e41f "Stable: concurrent multi-chat + key-aware models with cross-provider failover") -->
<!-- Everything below this marker is being re-worked. If this rework breaks the codebase, reset to the commit above. -->

# Plan v4 — Kaggle-backed Image Generation (modality-ready)

**Status:** Draft — awaiting approval.
**Scope today:** text-to-image via a user-supplied Kaggle notebook URL.
**Scope tomorrow:** add text-to-video by adding a second modality, with **no** re-plumbing of routing / storage / auth.

---

## Context — Why this is being built

PAWN's chat today only generates text. Users have asked to generate images from inside the chat (typing a prompt, getting an image back). Requirements:

- The "attach file" button is being replaced with a `+` button that offers two actions: **Attach file** (existing behaviour, untouched) and **Create image** (new).
- When the user has toggled **Create image** for a message, the next prompt generates an image; the image appears inline in the assistant bubble with **View (large)** + **Delete** + **Download** controls. Images live in the frontend only for now — closing the session deletes them. (Persisting to Drive is a future option.)
- The user supplies the Kaggle notebook URL (and any required Kaggle creds) in **Settings → API Keys**, the same place BYOK LLM keys live. No shared credentials, no leaks.
- The architecture must extend cleanly to **video** (and any other Kaggle-backed generation) later — no second re-plan.

---

## ⚠️ Feasibility research (v4 rework — read this before the architecture below)

The original plan (everything from "Architecture at a glance" down) silently assumes a
Kaggle notebook can act as a **live HTTP endpoint** that accepts `{"prompt": "..."}` and
returns image bytes. Web research shows that assumption is the load-bearing risk, and the
plan is internally inconsistent about it. There is **no native way** for a Kaggle notebook
to be a web server. There are exactly two real execution models, and they are very different:

### Model A — Kaggle Kernels API (official, batch)

The Kaggle public API (`kaggle kernels push` / `status` / `output`) is the *only* official,
TOS-clean way to trigger a notebook from outside. Flow:

1. Backend injects the prompt into the kernel source (rewrite `kernel-metadata.json` + a param
   cell / attached dataset), then `push` to run it.
2. Kaggle **queues** the run, cold-starts a container, loads the model, generates, writes output.
3. Backend **polls** `status` until complete, then `output` to pull the image file.

- ✅ Official, headless, no manual session start, no account-flagging risk.
- ❌ **Latency is minutes, not seconds** — queue wait + cold start + model load + generation.
  Reports describe "a few minutes" just to start. This is *not* an interactive chat experience.
- ❌ Essentially serial per kernel; GPU quota ~30 hrs/week; no concurrency story.
- ❌ The "prompt" must be baked into source each call — no clean request/response.
- ❌ A `kaggle.com/.../x.ipynb` **URL is not callable**; you address a kernel by *slug*, and it
  can't take an HTTP prompt at all. So the plan's "paste your notebook URL" UX doesn't map here.

### Model B — Live tunnel (Flask/FastAPI + ngrok/cloudflared inside the notebook)

The user manually starts their Kaggle notebook, which launches a small web server and opens a
public tunnel (ngrok / cloudflared). The tunnel gives a public URL; the user pastes **that URL**
into PAWN. Backend POSTs `{prompt}` to it and gets bytes back. **This is the only model that
delivers the UX the plan describes** (type prompt → image back in seconds).

- ✅ Low latency once warm (seconds); true request/response; matches the plan's UI as drawn.
- ❌ User must **manually start the notebook every session** (max 12h, idle-killed earlier).
- ❌ The public URL **changes on every restart** unless the user pays for a reserved ngrok
   domain / named cloudflare tunnel → otherwise they must re-paste the URL each session.
- ❌ Using Kaggle notebooks as a server / tunneling is **against the spirit of Kaggle's TOS**
   and can get accounts flagged. (Widely done for SD/LLM demos, but it is a gray area.)
- ❌ The URL the user pastes is the **tunnel URL, not a kaggle.com URL**. And Kaggle
   username/api_token are **not used by PAWN at all** in this model — PAWN just calls the tunnel.
   Auth between PAWN and the tunnel would be a shared secret the user sets in both places.

### What this means for the original plan

The plan mixes the two models: it stores Kaggle **username + api_token + a kaggle.com notebook
URL** (Model A vocabulary) but describes **live POST `{prompt}` → bytes in seconds** (Model B
behaviour). Those cannot both be true. Before any implementation we must pick **A or B** (or a
documented hybrid), because it changes: the Settings fields, what `kaggle.py` actually does,
the auth model, the latency/UX promise, and the test surface.

### Reconciling with the product decisions (auto-run requirement)

Decisions taken: (1) **fully automated** — the user must NOT manually start the notebook; PAWN
triggers it. (2) PAWN ships **fixed notebooks** and deploys them to the user's Kaggle/Drive via
API. (3) Auth via **shared secret token**. Open to **Colab** if it auto-runs better.

Research findings against those decisions:

- **Colab does not help.** There is no headless, server-to-Colab way to start/run a notebook.
  The only 2026 automation is the **Colab MCP Server**, which still drives a *browser-opened*
  notebook via a local agent — it cannot be triggered from PAWN's backend. So Colab is **worse**
  than Kaggle for auto-run. → Stay on Kaggle.
- **Auto-run on Kaggle is real** via `kaggle kernels push` with the user's username + API token.
  This means PAWN **must** store the user's Kaggle username + token (the original plan was right
  to collect them — they are required for Model A / for auto-starting any kernel). The user's
  Kaggle account must be **phone-verified** to get GPU + internet inside kernels.
- **You cannot read logs/output of a *running* kernel** — Kaggle only exposes output *after* the
  run finishes (confirmed open feature request). This **breaks** the obvious "self-tunnel + poll
  the kernel log for its URL" idea: a server notebook never "finishes," so PAWN can never pull
  the tunnel URL from Kaggle. A live model therefore needs an **out-of-band rendezvous**.

### Two architectures that satisfy "auto-run" (pick one)

**Architecture 1 — Pure batch (Kernels API only).** PAWN injects the prompt into the fixed
notebook, `push`es it to the user's account, polls `status`, pulls the image from `output`.
- ✅ Simplest; TOS-clean; no tunnel; shared-secret not even needed (Kaggle API is the auth).
- ❌ **Minutes of latency per image** (queue + cold start + model load). Chat shows a long
  "generating…" state. Acceptable only if the user tolerates slow, non-interactive generation.

**Architecture 2 — Auto-started self-tunnel + Supabase rendezvous (live).** PAWN `push`es a
fixed notebook that: boots, loads the model on GPU, opens a tunnel, and **writes its tunnel URL
into a Supabase row keyed by `user_id`** (PAWN already uses Supabase — this is the rendezvous
that sidesteps the running-kernel-log limitation), then serves `POST {prompt}` guarded by the
**shared secret**. PAWN polls Supabase for the URL, then talks to the tunnel directly; the first
image waits for boot, later images are fast. Lifecycle: detect dead tunnel → re-push to restart.
- ✅ Interactive after warm-up; matches the in-chat UX; uses the shared secret meaningfully;
  fits PAWN's existing Supabase stack.
- ❌ Most complex; tunneling is a **Kaggle TOS gray area** (account-flagging risk); must manage
  session death / cold re-start; needs the notebook to hold the user's Supabase write creds
  (or PAWN exposes a tiny authenticated "register-my-url" callback endpoint instead).

**Recommendation:** Build **Architecture 1 first** (correct, simple, ships the feature and proves
the modality plumbing) and treat **Architecture 2** as a fast-path upgrade behind the same
`generate.generate_image` interface — so the route/UI/storage never change between them. This
keeps the original plan's "modality-ready, no re-plumbing" promise intact.

### Branch strategy

All v4 work happens on a dedicated feature branch **`imageLab`**, branched off `dev` at the
stable commit `306e41f` (so the branch point == the stable marker at the top of this file).
`dev`/`main` stay untouched; if the experiment breaks things, delete the branch and nothing of
value is lost. Merge back to `dev` only once Milestone A (and later B) are green.

### Rollout strategy — demo-first (de-risk before touching chat)

The Kaggle round-trip is the risky, unproven part. The chat composer is working, polished code.
We will **not** wire the two together until the round-trip is proven, so a failure in the new
path can never break existing chat. Two independent milestones:

**Milestone A — "Image Lab" demo surface (throwaway, isolated).**
- **UI placement = mirror the Settings view-swap (confirmed against the code).** Today
  `App.tsx` keeps an `isSettingsOpen` boolean and renders `{isSettingsOpen ? <SettingsPage/> :
  <chat area>}`; `Sidebar.tsx` exposes `onOpenSettings` / `onCreate` and renders the "New Chat"
  button. Image Lab is a 1:1 mirror:
  - add `isImageLabOpen` state in `App.tsx` and a third arm to the ternary → `<ImageLabPage/>`
    renders **in place of the chat section**, exactly like Settings;
  - add an `onOpenImageLab` prop to `Sidebar` and a **"Image Lab" button directly below
    "New Chat"**;
  - new component `frontend/src/components/ImageLabPage.tsx` (throwaway): one prompt textbox +
    "Generate" button + an area that renders the returned image and any error verbatim.
- It calls the same backend `POST /generate` we will keep, so all backend work (Settings →
  Kaggle creds, `key_store`, `kaggle.py`, `generate.py`, the route, auto-`push`/poll/output) is
  built and validated here, with **zero** changes to `MessageInput`, `Message`, the conversation
  store, or the existing chat-area branch of `App.tsx`.
- Done = type a prompt in the Lab, get an image back end-to-end, and a missing-config error
  renders cleanly. **Deletion = remove one state var, one prop, one sidebar button, and
  `ImageLabPage.tsx`** — the chat path is never touched.

**Milestone B — integrate into chat (only after A is green).**
- Now do the composer work from the original draft (`+` button, image-mode chip, `ImageCard`,
  `streamGenerate`, store mutators). Backend is already proven, so this is pure frontend wiring.
- The Lab button can stay (handy for debugging) or be removed.

This keeps the backend and the chat-UI changes as **two separately revertable steps**, and means
the scary external dependency is fully characterised before it touches anything users rely on.

> **The sections below are the ORIGINAL draft and are NOT yet reconciled with the above.**
> They will be rewritten to match the chosen architecture once the final questions are answered.

---

## Architecture at a glance

Today: one BYOK key per provider (Groq, Cerebras, …). Adding Kaggle as a parallel provider family with **modalities** underneath gives:

```
Settings → API Keys
  ├── groq          (text/chat)
  ├── cerebras      (text/chat)
  ├── google        (text/embed)
  └── kaggle        ← NEW
        ├── credentials (username, api_token) — once per user
        └── notebooks
              ├── image: https://www.kaggle.com/.../text-to-image.ipynb
              ├── video: https://www.kaggle.com/.../text-to-video.ipynb   (future)
              └── ...
```

**Dispatch flow (text/chat, today):** `App.tsx` → `POST /chat` → `normalize.chat_stream(model_id, user_id)` → `resolver.pick(model_id, user_id)` → endpoint.

**Dispatch flow (image, new):** `App.tsx` (toggled "create image") → `POST /generate` → `generate.generate_image(prompt, user_id)` → `kaggle.run_notebook(notebook_url, prompt, creds)` → bytes → SSE `image` event → assistant bubble.

`generate` is a **new module** with one entry point per modality (`generate_image`, `generate_video`, …). `kaggle` is a **new thin client** that takes a notebook URL + prompt + creds and returns the generated artifact. The two stay separate so video tomorrow is `generate.generate_video` calling the same `kaggle` client with a different notebook URL.

No changes to `resolver.py` / `normalize.py` / `graph.py` — they're LLM-shaped and shouldn't have to know about images.

---

## User-facing behaviour

### 1. Composer

- The paperclip icon in `MessageInput` is replaced with a `+` icon.
- Click `+` → small popover with two rows:
  - **Attach file** (existing `onAttach` flow — unchanged).
  - **Create image** (new — sets `imageMode = true` on the composer state).
- When `imageMode` is on, a chip **"Generating image"** appears to the left of the `ModelSwitcher`, mirroring its pill style. Clicking the chip turns image mode off.
- When `imageMode` is on, the **send button** icon becomes an image/sparkle icon; pressing Send sends to `/generate` instead of `/chat`.

### 2. Assistant response (image mode)

- The assistant bubble is replaced with a **generated image card**:
  - Thumbnail of the image, full chat-bubble width.
  - Below: **View** (opens in-app modal at natural size, dark backdrop, Esc to close), **Download** (`<a download>` from a blob URL), **Delete** (removes the card and the blob URL — session-only).
- Card carries the original prompt as alt text and a small footer ("Generated via your Kaggle notebook").

### 3. Settings → API Keys

- New section **Kaggle** above (or alongside) the existing provider sections.
- Fields:
  - **Username** (text)
  - **API token** (password — value never returned in GET)
  - **Image notebook URL** (text — optional, per-modality)
  - **Video notebook URL** (text — future, optional)
- "Save" persists via `PUT /keys/kaggle`; "Remove" via `DELETE /keys/kaggle`.
- If the user tries to send an image-mode message with no image notebook configured, the composer shows an inline warning and the send is blocked; the message is *not* sent (this matches the BYOK-only LLM behaviour from BK-4).

### 4. Graceful "not configured"

- `/generate` returns a typed `NotConfiguredError` ("Add your Kaggle image notebook URL in Settings → API Keys to enable image generation.").
- Frontend renders the error as a chat notice bubble (same shape as today's `provider_switch` notices), with a button **Open Settings** that jumps to the API Keys section.

---

## Backend changes

### New modules

| Path | Purpose |
|---|---|
| `backend/app/core/kaggle.py` | Thin async client. `run_notebook(notebook_url, payload, creds) -> Artifact` (bytes + mime). Single function per artifact type; no modality-aware branching inside. |
| `backend/app/core/generate.py` | Modality dispatch. `generate_image(prompt, user_id)` looks up the user's kaggle creds + image notebook URL, calls `kaggle.run_notebook`, returns the artifact. `generate_video` (stub for now) will live next to it. |
| `backend/app/routes/generate.py` | `POST /generate` — body `{prompt: str, modality: Literal["image","video"] = "image"}`. Returns SSE stream. |

### `core/key_store.py` changes

- Add `"kaggle"` to `VALID_PROVIDERS`.
- Extend the storage row to support **multiple secrets per provider**: the existing single-string value stays for LLM providers; `kaggle` stores a JSON-encoded blob:
  ```json
  {
    "username": "...",
    "api_token": "...",
    "notebooks": { "image": "https://...", "video": "https://..." }
  }
  ```
- `get_key("kaggle")` returns the parsed dict (decrypted). LLM providers still get a `str` — additive change, no caller breakage.
- `set_key("kaggle", {...})` accepts the dict; `delete_key("kaggle")` unchanged.

### `routes/keys.py` changes

- `GET /keys` already returns `{"providers": [...]}`. Add `GET /keys/kaggle` (separate route) that returns the **shape only** (no secrets): `{has_creds: bool, notebooks: {image: bool, video: bool}}`. Keeps the same "values never returned" rule.
- `PUT /keys/kaggle` accepts the dict above; `DELETE /keys/kaggle` unchanged.

### `routes/generate.py` shape (the interesting part)

- Validates auth (middleware already provides `user_id`).
- Loads `key_store.get_key("kaggle")` for `user_id`.
  - Missing → `NotConfiguredError("Add your Kaggle image notebook URL in Settings → API Keys ...")` (HTTP 412, mapped to a typed SSE `error` event with `code: "not_configured"`).
- Calls `generate.generate_image(prompt, user_id)` in a `run_in_threadpool` (per PERF-1 — never block the event loop on third-party HTTP).
- Streams a single `image` SSE event with the bytes base64-encoded, then a `done` event. (Base64 keeps the SSE channel uniform with the rest of the app; the frontend `decode`s.)
- Image MIME type is captured from the Kaggle response and round-tripped on the event so the frontend can pick `image/png` vs `image/jpeg`.

### Concurrency / threading

- All Kaggle calls run in `run_in_threadpool` (matches PERF-1 pattern).
- The `kaggle` client uses `httpx` with a 60-second timeout (image gen is slow on Kaggle; configurable via constant).
- No caching of generated images — each prompt is fresh.

### Tests

- `tests/test_generate.py`
  - `POST /generate` happy path with mocked `kaggle.run_notebook` returning a tiny PNG → SSE contains the `image` event + `done`.
  - User with no kaggle key → `error` event with `code: "not_configured"`; HTTP 412.
  - Prompt sanitised (no shell-style injection — `kaggle` client uses parameterized payload, never string interpolation into URLs).
  - `run_in_threadpool` confirmed (monkeypatched to assert the call was off-loop).
- `tests/test_keys_kaggle.py`
  - `set_key("kaggle", {...})` + `get_key` round-trips.
  - `GET /keys/kaggle` returns `has_creds` + `notebooks`, never the token.
  - `delete_key("kaggle")` removes the entry.
- Mocks: `kaggle.run_notebook` (no real Kaggle calls in tests — the testing rule says never hit real providers).

### `exceptions.py`

- New `NotConfiguredError(ProviderError)` — same HTTP mapping as `ProviderError` but with a stable `code: "not_configured"` so the frontend can distinguish from generic provider failures.

---

## Frontend changes

### Composer

- `frontend/src/components/MessageInput.tsx`
  - Paperclip → `+` icon.
  - New `useState<"none" | "attach" | "image">("none")` for the popover.
  - Popover is a small floating card above the composer, two rows.
  - When `imageMode`, render an **"Image"** chip to the left of `ModelSwitcher`; clicking it clears the mode.

### Send / receive

- `frontend/src/api/client.ts`
  - New `streamGenerate(prompt, callbacks, modality="image")` — same shape as `streamChat` but hits `/generate`. Reuses the existing `StreamChatCallbacks` object but only wires `onImage` + `onDone` + `onError`.
  - `onImage` receives `{ mime: string, bytesBase64: string }`; converts to a `Blob` + object URL.
- `frontend/src/types.ts`
  - `GeneratedImage { id, blobUrl, mime, prompt }` — transient; not persisted.
  - `Message.content` gains a new union arm: `{ kind: "image"; images: GeneratedImage[] }`. Existing text content keeps working.
- `frontend/src/store/useConversationStore.ts`
  - `appendImage(convId, image)` + `deleteImage(convId, imageId)` mutators. Images are stored **per-conversation** alongside messages but excluded from the localStorage cache (they'd bloat the 4 MB cap and won't survive reload by design).
  - Persist effect already strips non-text content for the same reason — extend it.
- `frontend/src/App.tsx`
  - `handleSend` branches on `imageMode` → calls `streamGenerate` instead of `streamChat`.
  - Per-conv streaming plumbing from PERF-2 already covers this — `streamingConvIds` works unchanged.
  - New `<ImageCard>` component rendered in `Message.tsx` when `content.kind === "image"`.

### Image card UI

- `frontend/src/components/ImageCard.tsx` (~80 lines, single-purpose).
  - Thumbnail (`<img>` from blob URL, `alt={prompt}`).
  - **View** → `<ImageLightbox>` (new, ~50 lines): full-screen modal, dark backdrop, Esc + backdrop-click to close, no chrome. Lives in the same file.
  - **Download** → `<a href={blobUrl} download={filename}>`.
  - **Delete** → `deleteImage(convId, imageId)`; cleans up the blob URL with `URL.revokeObjectURL`.

### Settings

- `frontend/src/components/ApiKeysSection.tsx`
  - New section above existing providers: **Kaggle**.
  - Three inputs (username, API token, image notebook URL) + Save / Remove.
  - On mount, fetch `GET /keys/kaggle` to know whether to show "Configured" badge.
  - Reuses `getKey`/`setKey`/`deleteKey` from `client.ts` — extended there with `getKaggleConfig()`, `setKaggleConfig()`, `deleteKaggleConfig()`.
- "Add your Kaggle image notebook URL…" warning chip in the composer when `imageMode` is on but `has_creds` is false.

### Failure UI

- SSE `error` event with `code: "not_configured"` → notice bubble with **Open Settings** button that scrolls/highlights the Kaggle section and (optionally) switches to it.

---

## Multi-user isolation (the explicit checklist)

- [x] **Per-user credentials** — `kaggle` row in `key_store` is keyed by `user_id`. No shared secrets anywhere.
- [x] **Per-user notebook URL** — the notebook itself is owned by the user; PAWN never supplies a default. Two users on the same PAWN instance use two different notebooks.
- [x] **No cross-user leakage** — `/generate` resolves creds via `request.state.user_id`. A forged request can't run against another user's notebook.
- [x] **Encrypted at rest** — same AES-GCM path as BYOK LLM keys (BK-1).
- [x] **Tokens never returned** — `GET /keys/kaggle` returns `has_creds`/`notebooks` shape only; `api_token` value is write-only.
- [x] **Settings revoke = immediate** — `key_store.set_key`/`delete_key` evict the in-memory cache (PERF-1), so the next `/generate` sees the new state without restart.
- [x] **No data persistence** — image bytes live in the blob URL until the tab closes; not written to Drive, not written to Supabase, not in the conversation cache.

---

## Future: adding text-to-video

Because the routing is modality-shaped, video is a small additive change:

1. Add `notebook_url_video` field to the kaggle key payload.
2. `generate.generate_video(prompt, user_id)` in `core/generate.py`.
3. `POST /generate` already accepts `modality`; the frontend just adds a third row to the `+` popover.
4. `Message.content` union grows a `{ kind: "video"; ... }` arm.
5. No changes to `key_store`, `resolver`, `normalize`, `graph`, auth, or storage.

---

## Files to be created / modified

**New**
- `backend/app/core/kaggle.py`
- `backend/app/core/generate.py`
- `backend/app/routes/generate.py`
- `backend/app/exceptions.py` — add `NotConfiguredError`
- `frontend/src/components/ImageCard.tsx` (includes `ImageLightbox`)
- `backend/tests/test_generate.py`
- `backend/tests/test_keys_kaggle.py`

**Modified**
- `backend/app/core/key_store.py` — add `kaggle` to `VALID_PROVIDERS`; support dict-shaped payloads
- `backend/app/routes/keys.py` — `GET /keys/kaggle`
- `backend/app/main.py` — register `routes.generate`
- `frontend/src/components/MessageInput.tsx` — paperclip → `+`; popover; image-mode chip
- `frontend/src/components/Message.tsx` — render `ImageCard` when `content.kind === "image"`
- `frontend/src/api/client.ts` — `streamGenerate`, kaggle key helpers
- `frontend/src/types.ts` — `GeneratedImage`, `Message.content` union arm
- `frontend/src/store/useConversationStore.ts` — `appendImage`, `deleteImage`, exclude from cache
- `frontend/src/App.tsx` — `handleSend` branches on `imageMode`
- `frontend/src/components/ApiKeysSection.tsx` — Kaggle section

---

## Verification

End-to-end manual:

1. `docker compose up -d --build`
2. Sign in with Google; open **Settings → API Keys**.
3. Paste Kaggle username + API token + image notebook URL; Save; verify **Configured** badge appears.
4. New Chat → click `+` → **Create image**; confirm chip appears next to ModelSwitcher.
5. Type `a red apple on a wooden table`; send.
6. Expect: assistant bubble replaced with an image card; **View** opens a large modal; **Download** saves a PNG; **Delete** removes the card.
7. Refresh the page — image gone (session-only by design).
8. Remove the kaggle key in Settings; toggle image mode again; send → notice bubble "Add your Kaggle image notebook URL in Settings…" with **Open Settings** button.
9. Sign in with a second Google account → confirm no Kaggle config leaks across users (separate encrypted row).
10. `docker compose exec backend pytest` — all backend tests green including the new `test_generate.py` + `test_keys_kaggle.py`.
11. `cd frontend && npm run build` — clean.

Automated:

- Backend: `pytest backend/tests/test_generate.py backend/tests/test_keys_kaggle.py -v`
- Frontend: `npm run build` (tsc + vite).

---

## Out of scope (deliberately)

- Persisting generated images to Drive (future option noted in user-facing copy).
- Video generation (routing is ready; only the generator + UI are deferred).
- Generating from uploaded reference images (img2img).
- Style presets, negative prompts, seed control, multi-image grids.
- Public/shared gallery of generations.

---

## Open questions to confirm before implementation

1. **Notebook contract** — the plan assumes the user's notebook exposes a single HTTP endpoint that accepts `{"prompt": "..."}` and returns image bytes (or a JSON `{image_base64, mime}`). If the Kaggle notebook wrapper exposes a different shape (e.g. webhook + dataset commit, or a long-poll), we need to adjust `kaggle.run_notebook` early.
2. **Kaggle creds vs notebook URL** — are username + API token mandatory (Kaggle-authenticated notebook), or is the notebook URL enough (public notebook)? The plan stores both but only requires notebook URL to be configured.
3. **Image size / format** — assume the notebook returns PNG, ≤ ~5 MB. Larger → we'd need chunked streaming; deferred.
4. **Generation timeout** — 60 s assumed; configurable via `constants.KAGGLE_TIMEOUT_SECONDS`. Confirm or override.
