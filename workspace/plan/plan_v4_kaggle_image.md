<!-- LAST STABLE COMMIT: 306e41f9c47415800bd7dbfaa2eade37789ad2c7 (306e41f "Stable: concurrent multi-chat + key-aware models with cross-provider failover") -->
<!-- Everything below this marker is being re-worked. If this rework breaks the codebase, reset to the commit above. -->

# Plan v4 — Kaggle-backed Image Generation (modality-ready)

**Status:** Draft — reconciled with Architecture 1 (batch Kaggle Kernels API + auto-push). See the feasibility section below.
**Scope today:** text-to-image, fully automated — PAWN auto-deploys & runs a fixed template kernel in the user's own Kaggle account (user supplies only their Kaggle username + API token).
**Scope tomorrow:** add text-to-video by adding a second modality, with **no** re-plumbing of routing / storage / auth.

---

## Context — Why this is being built

PAWN's chat today only generates text. Users have asked to generate images from inside the chat (typing a prompt, getting an image back). Requirements:

- The "attach file" button is being replaced with a `+` button that offers two actions: **Attach file** (existing behaviour, untouched) and **Create image** (new).
- When the user has toggled **Create image** for a message, the next prompt generates an image; the image appears inline in the assistant bubble with **View (large)** + **Delete** + **Download** controls. Images live in the frontend only for now — closing the session deletes them. (Persisting to Drive is a future option.)
- The user supplies only their **Kaggle username + API token** in **Settings → API Keys**, the same place BYOK LLM keys live. PAWN deploys and runs a fixed template kernel in the user's own account — the user never writes or pastes a notebook. No shared credentials, no leaks. (Requires a phone-verified Kaggle account for free GPU + internet.)
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
path can never break existing chat. Three milestones, each provable before the next:

**Milestone A.0 — prove the Kaggle round-trip with `findCube(int)` (NO image, NO GPU).**
Before touching image models, prove the *pipe* with the cheapest possible payload. This removes
every hard variable at once — no GPU, no model download, no multi-minute latency, no internet —
so any failure is unambiguously in the plumbing, not the model.
- **Template kernel** = a CPU notebook that defines `def findCube(n): return n ** 3`, reads an
  injected integer, and writes `/kaggle/working/out.json` = `{"input": n, "result": n**3}`.
  `kernel-metadata.json`: `enable_gpu: false`, `enable_internet: false`, `is_private: true` —
  the fastest, quota-free configuration.
- **Backend** exercises the *entire* chain on a trivial function: `deploy_kernel` (push the cube
  template once) → inject `n` → `push` a run → poll `status` → pull `output` → parse the JSON.
  This is the generic primitive `kaggle.run_kernel(payload, creds, slug) -> Artifact`; image gen
  later is just `run_kernel` with the image template + an int swapped for a prompt.
- **Lab UI** = an integer input + "Run" button that shows the returned number (e.g. `5 → 125`)
  and round-trip time, plus any error verbatim.
- **Done = type `5` in the Lab, get `125` back from a real Kaggle run.** Once green, the only
  remaining unknown for images is the model itself — the transport is proven.

**Milestone A — swap the cube for the image model (throwaway Lab, isolated).**
Reuse everything from A.0; change only the template kernel (cube → image model, GPU + internet on)
and the Lab control (int input → prompt textbox, number → rendered image).
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

> **The sections below are RECONCILED with Architecture 1 (batch Kaggle Kernels API + auto-push).**
> Locked decisions: auto-run via the user's Kaggle creds; PAWN auto-pushes a fixed template kernel
> into the user's account; a **phone-verified Kaggle account** is a prerequisite (required for GPU +
> internet inside kernels); **no shared-secret token in Arch 1** — the Kaggle API itself is the auth
> (the shared secret returns only in the Arch 2 tunnel upgrade).

---

## Architecture at a glance

Today: one BYOK key per provider (Groq, Cerebras, …). Kaggle joins as a parallel provider family
with **modalities** underneath — but unlike the LLM providers, PAWN **manages the compute**: it
pushes and runs a kernel in the *user's own* Kaggle account on their behalf.

```
Settings → API Keys
  ├── groq          (text/chat)
  ├── cerebras      (text/chat)
  ├── google        (text/embed)
  └── kaggle        ← NEW
        ├── credentials (username, api_token) — entered once per user
        └── kernels (PAWN-managed — the user never writes or pastes a notebook)
              ├── image: <username>/pawn-image-gen   ← auto-pushed by PAWN on setup
              └── video: <username>/pawn-video-gen   ← future, auto-pushed
```

**Dispatch flow (text/chat, today):** `App.tsx` → `POST /chat` → `normalize.chat_stream(...)` → `resolver.pick(...)` → endpoint. *(unchanged)*

**Dispatch flow (image, Arch 1 — batch):** `ImageLabPage` (Milestone A) / `App.tsx` (Milestone B) → `POST /generate` → `generate.generate_image(prompt, user_id)` → `kaggle.run_image(prompt, creds, slug)`: **inject prompt → `push` kernel version → poll `status` → pull `output` image** → bytes. The route streams `status` events while it runs (queued/running), then one `image` event + `done`.

`generate` is a **new module** with one entry point per modality. `kaggle` is a **new client** wrapping the **Kaggle Kernels REST API** (`push` / `status` / `output`) plus a one-time `deploy_kernel(creds, slug)`. The split means the future Arch 2 (live tunnel) replaces only the *inside* of `kaggle.run_image` — `generate`, the route, and the UI never change.

No changes to `resolver.py` / `normalize.py` / `graph.py` — they're LLM-shaped and don't know about images.

---

## User-facing behaviour

### 1. Composer (Milestone B — after the Lab is proven)

- The paperclip icon in `MessageInput` is replaced with a `+` icon.
- Click `+` → small popover with two rows:
  - **Attach file** (existing `onAttach` flow — unchanged).
  - **Create image** (new — sets `imageMode = true` on the composer state).
- When `imageMode` is on, a chip **"Generating image"** appears to the left of the `ModelSwitcher`, mirroring its pill style. Clicking the chip turns image mode off.
- When `imageMode` is on, the **send button** icon becomes an image/sparkle icon; pressing Send sends to `/generate` instead of `/chat`.

### 2. Assistant response (image mode)

- **Arch 1 is slow (minutes).** The assistant bubble first shows a **progress state** — "Generating image… (queued / running on Kaggle)" — driven by SSE `status` events.
- On completion the bubble becomes a **generated image card**:
  - Thumbnail of the image, full chat-bubble width.
  - Below: **View** (opens in-app modal at natural size, dark backdrop, Esc to close), **Download** (`<a download>` from a blob URL), **Delete** (removes the card and the blob URL — session-only).
- Card carries the original prompt as alt text and a small footer ("Generated on your Kaggle GPU").

### 3. Settings → API Keys

- New section **Kaggle** above (or alongside) the existing provider sections.
- Fields (**no notebook URL** — PAWN manages the kernel):
  - **Username** (text)
  - **API token** (password — value never returned in GET)
- A short note states the prerequisite: *"Requires a phone-verified Kaggle account (needed for free GPU + internet inside notebooks)."*
- **Save** persists via `PUT /keys/kaggle`; on success PAWN **auto-deploys** the image template kernel to the user's account (`deploy_kernel`) and records the slug. **Remove** via `DELETE /keys/kaggle`.
- Status badges: **Configured** (creds saved) and **Kernel ready** (template deployed).
- If the user tries to send an image-mode message with no Kaggle creds, the composer shows an inline warning and the send is blocked; the message is *not* sent (matches the BYOK-only LLM behaviour from BK-4).

### 4. Graceful "not configured"

- `/generate` returns a typed `NotConfiguredError` ("Add your Kaggle username + API token in Settings → API Keys to enable image generation.").
- Frontend renders the error as a chat notice bubble (same shape as today's `provider_switch` notices), with a button **Open Settings** that jumps to the Kaggle section.

---

## Backend changes

### New modules

| Path | Purpose |
|---|---|
| `backend/app/core/kaggle.py` | Client over the **Kaggle Kernels REST API** (HTTP Basic = `username:token`). Generic primitive `run_kernel(payload, creds, slug) -> Artifact`: inject payload → `push` run → poll `status` → pull `output`. `deploy_kernel(creds, template, slug)` pushes a bundled template once. `run_image(...)` is a thin wrapper over `run_kernel` with the image template; the A.0 cube POC calls `run_kernel` with the cube template. Reports coarse status so the route can stream progress. No modality branching inside. |
| `backend/app/core/generate.py` | Modality dispatch. `generate_image(prompt, user_id)` loads the user's kaggle creds, ensures the kernel is deployed, calls `kaggle.run_image`, returns the artifact. `generate_video` (stub) lives next to it. |
| `backend/app/routes/generate.py` | `POST /generate` — body `{prompt: str, modality: Literal["image","video"] = "image"}`. SSE: `status` events while running, then `image` + `done`. |
| `backend/app/kaggle_templates/image_gen/` | The **fixed template kernel** PAWN deploys: the notebook (`.ipynb`) + `kernel-metadata.json` (`enable_gpu: true`, `enable_internet: true`, `is_private: true`). The notebook decodes the injected prompt, generates, and writes the image to `/kaggle/working/out.png`. |

### Prompt injection (safe by construction)

- The prompt is **never string-interpolated into notebook source.** PAWN base64-encodes the prompt into a single dedicated param the template decodes at runtime (`prompt = base64.b64decode(PROMPT_B64).decode()`). This neutralises quote / `"""` / code-injection via the prompt text.

### `core/key_store.py` changes

- Add `"kaggle"` to `VALID_PROVIDERS`.
- Extend the row to support a **dict payload** for kaggle (LLM providers keep their plain string); kaggle stores a JSON-encoded blob:
  ```json
  {
    "username": "...",
    "api_token": "...",
    "kernels": { "image": "<username>/pawn-image-gen", "video": null }
  }
  ```
- Stored encrypted as a JSON string via the same AES-GCM path. `get_key("kaggle")` returns the parsed dict (decrypted); LLM providers still get a `str` — additive change, no caller breakage.
- `set_key("kaggle", {...})` accepts the dict; `delete_key("kaggle")` unchanged.

### `routes/keys.py` changes

- `GET /keys` already returns `{"providers": [...]}`. Add `GET /keys/kaggle` returning the **shape only** (no secrets): `{has_creds: bool, kernels: {image: bool, video: bool}}`.
- `PUT /keys/kaggle` accepts `{username, api_token}`; on success it triggers `deploy_kernel` (off-loop) and stores the resulting slug. `DELETE /keys/kaggle` unchanged.

### `routes/generate.py` shape (the interesting part)

- Validates auth (middleware already provides `user_id`).
- Loads `key_store.get_key(user_id, "kaggle")`.
  - Missing creds → `NotConfiguredError("Add your Kaggle username + API token in Settings → API Keys ...")` (HTTP 412, mapped to a typed SSE `error` event with `code: "not_configured"`).
- Calls `generate.generate_image(prompt, user_id)` in `run_in_threadpool` (per PERF-1 — never block the event loop on third-party HTTP; here the call lasts **minutes**).
- Streams `status` events (`queued` / `running`) during polling so the UI shows progress, then a single `image` event with the bytes base64-encoded (frontend `decode`s) and the captured MIME, then `done`.

### Concurrency / threading / limits

- All Kaggle calls run in `run_in_threadpool` (matches PERF-1 pattern).
- `httpx` client with short per-HTTP-call timeouts, wrapped in a **poll loop** up to `constants.KAGGLE_RUN_TIMEOUT_SECONDS` (default 600 s) at `KAGGLE_POLL_INTERVAL_SECONDS` (default 8 s).
- **Per-user serialization**: a kernel slug is single-writer — two concurrent image requests for the same user would clobber the same kernel version. A per-`user_id` lock makes a user's image requests serial (different users still run in parallel).
- Respect Kaggle's **GPU quota (~30 h/week/user)** and push rate limits — surface quota/limit failures as a typed error event, not a generic 500.
- No caching of generated images — each prompt is fresh.

### Tests

- `tests/test_generate.py`
  - `POST /generate` happy path with mocked `kaggle.run_image` returning a tiny PNG → SSE contains `status` → `image` → `done`.
  - User with no kaggle creds → `error` event with `code: "not_configured"`; HTTP 412.
  - Prompt-injection neutralised — assert the prompt is passed base64 / parameterized, never interpolated into kernel source.
  - `run_in_threadpool` confirmed (monkeypatched to assert the call was off-loop).
- `tests/test_keys_kaggle.py`
  - `set_key("kaggle", {...})` + `get_key` round-trips the dict.
  - `PUT /keys/kaggle` triggers `deploy_kernel` (mocked) and stores the slug.
  - `GET /keys/kaggle` returns `has_creds` + `kernels`, never the token.
  - `delete_key("kaggle")` removes the entry.
- Mocks: the entire `kaggle` client / Kaggle REST API — **no real Kaggle calls in tests** (testing rule says never hit real providers).

### `exceptions.py`

- New `NotConfiguredError(ProviderError)` — same HTTP mapping as `ProviderError` but with a stable `code: "not_configured"` so the frontend can distinguish from generic provider failures. (Optionally a `KaggleQuotaError` later for quota/limit surfacing.)

---

## Frontend changes

### Milestone A — Image Lab (throwaway)

- `frontend/src/components/ImageLabPage.tsx` — prompt textbox + **Generate** button; renders SSE `status` text, then the returned image; shows any error verbatim. Calls `streamGenerate` (below).
- `frontend/src/App.tsx` — `isImageLabOpen` state + ternary arm rendering `<ImageLabPage/>` in place of the chat area.
- `frontend/src/components/Sidebar.tsx` — `onOpenImageLab` prop + **"Image Lab"** button under "New Chat".

### Milestone B — chat composer (only after A is green)

- `frontend/src/components/MessageInput.tsx` — paperclip → `+`; `useState<"none"|"attach"|"image">("none")` popover (small floating card, two rows); image-mode chip left of `ModelSwitcher` (click clears the mode).
- `frontend/src/components/Message.tsx` — render `<ImageCard>` when `content.kind === "image"`; render the progress state while streaming `status`.
- `frontend/src/App.tsx` — `handleSend` branches on `imageMode` → `streamGenerate` instead of `streamChat`. Per-conv streaming plumbing from PERF-2 covers this — `streamingConvIds` unchanged.

### Shared (built in Milestone A, reused in B)

- `frontend/src/api/client.ts`
  - New `streamGenerate(prompt, callbacks, modality="image")` — same shape as `streamChat` but hits `/generate`; wires `onStatus` + `onImage` + `onDone` + `onError`.
  - `onImage` receives `{ mime: string, bytesBase64: string }`; converts to a `Blob` + object URL.
  - Kaggle key helpers `getKaggleConfig()`, `setKaggleConfig()`, `deleteKaggleConfig()`.
- `frontend/src/types.ts`
  - `GeneratedImage { id, blobUrl, mime, prompt }` — transient; not persisted.
  - `Message.content` gains a new union arm: `{ kind: "image"; images: GeneratedImage[] }`. Existing text content keeps working.
- `frontend/src/store/useConversationStore.ts`
  - `appendImage(convId, image)` + `deleteImage(convId, imageId)` mutators. Images stored **per-conversation** alongside messages but excluded from the localStorage cache (they'd bloat the 4 MB cap and won't survive reload by design — extend the existing strip effect).

### Image card UI (Milestone B)

- `frontend/src/components/ImageCard.tsx` (~80 lines, single-purpose).
  - Thumbnail (`<img>` from blob URL, `alt={prompt}`).
  - **View** → `<ImageLightbox>` (new, ~50 lines): full-screen modal, dark backdrop, Esc + backdrop-click to close, no chrome. Lives in the same file.
  - **Download** → `<a href={blobUrl} download={filename}>`.
  - **Delete** → `deleteImage(convId, imageId)`; cleans up the blob URL with `URL.revokeObjectURL`.

### Settings

- `frontend/src/components/ApiKeysSection.tsx`
  - New section above existing providers: **Kaggle**.
  - Two inputs (username, API token) + Save / Remove + the phone-verified-account note.
  - On mount, fetch `GET /keys/kaggle` to show **Configured** / **Kernel ready** badges.
  - Uses the `client.ts` kaggle helpers above.
- Warning chip in the composer when `imageMode` is on but `has_creds` is false.

### Failure UI

- SSE `error` event with `code: "not_configured"` → notice bubble with **Open Settings** button that scrolls/highlights the Kaggle section and (optionally) switches to it.

---

## Multi-user isolation (the explicit checklist)

- [x] **Per-user credentials** — `kaggle` row in `key_store` is keyed by `user_id`. No shared secrets anywhere.
- [x] **Per-user kernel** — PAWN deploys the template into *each user's own* Kaggle account; runs execute on that user's GPU quota under their token. No shared compute, no default account.
- [x] **No cross-user leakage** — `/generate` resolves creds via `request.state.user_id`. A forged request can't run against another user's account.
- [x] **Encrypted at rest** — same AES-GCM path as BYOK LLM keys (BK-1); the `api_token` is inside the encrypted JSON blob.
- [x] **Tokens never returned** — `GET /keys/kaggle` returns `has_creds`/`kernels` shape only; `api_token` value is write-only.
- [x] **Settings revoke = immediate** — `key_store.set_key`/`delete_key` evict the in-memory cache (PERF-1), so the next `/generate` sees the new state without restart.
- [x] **No data persistence** — image bytes live in the blob URL until the tab closes; not written to Drive, not written to Supabase, not in the conversation cache.

---

## Future: text-to-video (and the Arch 2 live-tunnel upgrade)

Video — a small additive change because routing is modality-shaped:

1. Add a `video` template under `kaggle_templates/`; deploy as `<username>/pawn-video-gen`.
2. `generate.generate_video(prompt, user_id)` in `core/generate.py`.
3. `POST /generate` already accepts `modality`; the frontend adds a third row to the `+` popover.
4. `Message.content` union grows a `{ kind: "video"; ... }` arm.
5. No changes to `key_store`, `resolver`, `normalize`, `graph`, auth, or storage.

Arch 2 (live tunnel, fast) — swaps only the *inside* of `kaggle.run_image`: deploy a server+tunnel template, add the **shared-secret token** field, add a **Supabase URL rendezvous** row, and a session-liveness check. `generate`, the route, and all UI stay identical.

---

## Files to be created / modified

**New (Milestone A.0 — prove the round-trip)**
- `backend/app/core/kaggle.py` — generic `run_kernel` + `deploy_kernel` (cube template first)
- `backend/app/routes/generate.py` — start as a generic `POST /generate` (cube), specialize later
- `backend/app/kaggle_templates/cube_poc/` — `findCube` notebook + `kernel-metadata.json` (CPU, no internet)
- `frontend/src/components/ImageLabPage.tsx` — start as a "Kaggle Lab": int input → returned number

**New (Milestone A — swap in the image model)**
- `backend/app/core/generate.py` — `generate_image` wrapping `run_kernel`
- `backend/app/kaggle_templates/image_gen/` — image template notebook + `kernel-metadata.json` (GPU + internet)
- `backend/app/exceptions.py` — add `NotConfiguredError`
- `backend/tests/test_generate.py`
- `backend/tests/test_keys_kaggle.py`
- `frontend/src/components/ImageLabPage.tsx` (throwaway)

**New (Milestone B — chat UI)**
- `frontend/src/components/ImageCard.tsx` (includes `ImageLightbox`)

**Modified (Milestone A)**
- `backend/app/core/key_store.py` — add `kaggle` to `VALID_PROVIDERS`; support dict-shaped payloads
- `backend/app/routes/keys.py` — `GET/PUT/DELETE /keys/kaggle` + auto-deploy on PUT
- `backend/app/main.py` — register `routes.generate`
- `backend/app/constants.py` — `KAGGLE_RUN_TIMEOUT_SECONDS`, `KAGGLE_POLL_INTERVAL_SECONDS`, template path
- `frontend/src/api/client.ts` — `streamGenerate`, kaggle key helpers
- `frontend/src/App.tsx` — `isImageLabOpen` state + ternary arm
- `frontend/src/components/Sidebar.tsx` — `onOpenImageLab` + button under "New Chat"
- `frontend/src/components/ApiKeysSection.tsx` — Kaggle section

**Modified (Milestone B)**
- `frontend/src/components/MessageInput.tsx` — paperclip → `+`; popover; image-mode chip
- `frontend/src/components/Message.tsx` — render `ImageCard` + progress state
- `frontend/src/types.ts` — `GeneratedImage`, `Message.content` union arm
- `frontend/src/store/useConversationStore.ts` — `appendImage`, `deleteImage`, exclude from cache
- `frontend/src/App.tsx` — `handleSend` branches on `imageMode`

---

## Verification

**Milestone A.0 (prove the round-trip — cube):**

1. `docker compose up -d --build`
2. Sign in with Google; **Settings → API Keys → Kaggle**; enter username + API token; Save → cube template auto-pushed.
3. Sidebar → **Kaggle Lab**; enter `5`; Run.
4. Expect: "queued → running" then **`125`** returned from a real Kaggle run, with round-trip time shown.
5. Backend tests green for the round-trip (mocked Kaggle REST). → transport proven; proceed to images.

**Milestone A (backend + Image Lab):**

1. Swap the template to the image model; redeploy.
2. Sign in with Google; open **Settings → API Keys → Kaggle**; enter username + API token; Save.
3. Confirm **Configured** and **Kernel ready** badges (template auto-pushed to your Kaggle account).
4. Sidebar → **Image Lab**; type `a red apple on a wooden table`; Generate.
5. Expect: "queued → running" progress (minutes), then the image renders in the Lab.
6. Remove the Kaggle creds; Generate again → inline `not_configured` error with **Open Settings**.
7. Second Google account → no Kaggle config leaks (separate encrypted row); its own kernel.
8. `docker compose exec backend pytest` — green incl. `test_generate.py` + `test_keys_kaggle.py`.
9. `cd frontend && npm run build` — clean.

**Milestone B (chat integration):**

10. New Chat → `+` → **Create image**; confirm chip appears next to `ModelSwitcher`.
11. Send a prompt → progress in the bubble → image card; **View** opens a modal; **Download** saves the file; **Delete** removes the card.
12. Refresh the page — image gone (session-only by design).
13. `npm run build` clean; backend tests still green.

Automated:

- Backend: `pytest backend/tests/test_generate.py backend/tests/test_keys_kaggle.py -v`
- Frontend: `npm run build` (tsc + vite).

---

## Out of scope (deliberately)

- Persisting generated images to Drive (future option noted in user-facing copy).
- Video generation (routing is ready; only the generator + UI are deferred).
- Arch 2 live-tunnel fast path (interface is ready; deferred to a later phase).
- Generating from uploaded reference images (img2img).
- Style presets, negative prompts, seed control, multi-image grids.
- Public/shared gallery of generations.

---

## Open questions / risks to confirm before implementation

1. **Kaggle REST contract** — exact `push` / `status` / `output` endpoint paths + payloads must be
   verified against the `kaggle` API source before coding `kaggle.py` (the official package wraps
   `https://www.kaggle.com/api/v1/...` with HTTP Basic). Spike this first.
2. **Latency UX** — minutes per image is inherent to Arch 1. Confirm the `status`-event progress UI
   is acceptable for v1; if not, prioritise the Arch 2 tunnel upgrade sooner.
3. **GPU quota & rate limits** — per-user ~30 GPU-h/week and kernel-push rate limits. Decide how to
   surface "quota exhausted" vs generic failure (typed `KaggleQuotaError`?).
4. **Template kernel contents** — which image model (e.g. SD/SDXL via diffusers) and how it's loaded
   (HF download needs internet; or a Kaggle model-dataset). Defines the template notebook + its size.
5. **Image size / format** — assume PNG ≤ ~5 MB returned via base64. Larger → chunked streaming; deferred.
6. **Concurrency** — confirm the per-`user_id` serialization lock is acceptable (a user can't run two
   generations at once) for v1.
