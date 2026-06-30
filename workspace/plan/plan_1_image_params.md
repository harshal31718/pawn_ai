# Plan 1 — Image Generation Parameter Controls

**Branch:** `imageLab`
**Scope:** Expose generation parameters in the UI with opt-in checkboxes. Unchecked = model default. Checked = user value is sent.
**Effort:** Medium. UI is the bulk; backend is a thin pass-through; notebooks need 1-cell update each.

---

## UI Design

Each model panel's `ImageGenerator` gets a collapsible **Advanced** section below the prompt:

```
┌─ Prompt ─────────────────────────────────────────────┐
│ [a cinematic shot of a mountain at sunset...        ] │
└───────────────────────────────────────────────────────┘

▼ Advanced

 ☐  Aspect Ratio      [1:1 ▾]
                        1:1  → 512 × 512
                        16:9 → 1024 × 576
                        9:16 → 576 × 1024
                        4:3  → 768 × 576

 ☐  Inference Steps   ──●──────────  20        (4 – 50)

 ☐  Guidance Scale    ──────●──────  7.5       (1.0 – 20.0)
                       (FLUX: leave at 0 — model is guidance-free)

 ☐  Negative Prompt   [avoid: blurry, cartoon, text...   ]

 ☐  Style Preset      [None ▾]
                        None
                        Photorealistic
                        Cinematic
                        Anime
                        Oil Painting
                        Sketch

[Generate]
```

**Checkbox behaviour:** unchecked → control is greyed out, default value shown as hint, nothing sent to backend. Checked → control is active, value is sent. State persists per model within the session (not across reloads).

---

## Style Preset → Prompt Suffix Map

| Preset | Appended to prompt |
|---|---|
| Photorealistic | `, RAW photo, 8K, ultra detailed, photorealistic, DSLR` |
| Cinematic | `, cinematic shot, anamorphic lens, dramatic lighting, film grain` |
| Anime | `, anime style, studio ghibli, detailed illustration, vibrant colors` |
| Oil Painting | `, oil painting, impressionist, thick brushstrokes, canvas texture` |
| Sketch | `, pencil sketch, charcoal drawing, black and white, cross-hatching` |

Suffix is appended on the **backend** before the prompt reaches the notebook — keeps the frontend clean.

---

## Architecture

```
Frontend (ImageGenerator)
  └─ AdvancedParams panel
       └─ enabled params → GenerateRequest.params{}

Backend (routes/generate.py)
  └─ GenerateRequest.params → apply style suffix → ImageJobParams
  └─ create_cold_job / submit_session_job carry params as JSONB

Supabase (image_jobs table)
  └─ params JSONB column  ← schema migration required

Notebooks (FLUX + SDXL serve-loops)
  └─ read params from job row, apply to pipeline call
```

---

## Steps

### IP-1 — Schema migration

Add `params JSONB DEFAULT '{}'` to `image_jobs` in Supabase:

```sql
ALTER TABLE image_jobs ADD COLUMN IF NOT EXISTS params JSONB DEFAULT '{}';
```

Run in the Supabase SQL editor. No backend model change needed — existing rows get `{}`.

**Done when:** `image_jobs` table has `params` column; existing jobs unaffected.

---

### IP-2 — Backend: params pass-through

**`backend/app/core/image_session.py`**

Add `ImageJobParams` dataclass (or Pydantic model):

```python
class ImageJobParams(BaseModel):
    width: int | None = None
    height: int | None = None
    num_inference_steps: int | None = None
    guidance_scale: float | None = None
    negative_prompt: str | None = None
    style_preset: str | None = None  # applied as suffix before storing
```

`submit_session_job(user_id, model, prompt, params)` — inserts `params.model_dump(exclude_none=True)` into the `params` JSONB column.

`create_cold_job(user_id, model, prompt, params)` — same.

**`backend/app/routes/generate.py`**

```python
class GenerateRequest(BaseModel):
    prompt: str
    model: str = "sdxl"
    params: ImageJobParams = ImageJobParams()
```

Apply style suffix here (before storing):

```python
STYLE_SUFFIXES = {
    "photorealistic": ", RAW photo, 8K, ultra detailed, photorealistic, DSLR",
    "cinematic": ", cinematic shot, anamorphic lens, dramatic lighting, film grain",
    "anime": ", anime style, studio ghibli, detailed illustration, vibrant colors",
    "oil_painting": ", oil painting, impressionist, thick brushstrokes, canvas texture",
    "sketch": ", pencil sketch, charcoal drawing, black and white, cross-hatching",
}

if params.style_preset:
    prompt += STYLE_SUFFIXES.get(params.style_preset, "")
```

**Tests:** `test_generate.py` — assert params are stored on the job row; assert style suffix is applied before storing.

**Done when:** `POST /generate` with params → job row has `params` column populated.

---

### IP-3 — Notebook updates (FLUX + SDXL)

Both notebooks read `params` from the job row and pass values to the pipeline call.

**SDXL serve-loop cell 3 (inference):**
```python
p = job.get("params", {})
image = pipe(
    prompt=job["prompt"],
    negative_prompt=p.get("negative_prompt", ""),
    num_inference_steps=p.get("num_inference_steps", 20),
    guidance_scale=p.get("guidance_scale", 7.5),
    width=p.get("width", 512),
    height=p.get("height", 768),
).images[0]
```

**FLUX serve-loop cell 3 (inference):**
```python
p = job.get("params", {})
image = pipe(
    prompt=job["prompt"],
    num_inference_steps=p.get("num_inference_steps", 4),
    guidance_scale=0.0,           # FLUX is guidance-free — always 0
    width=p.get("width", 1024),
    height=p.get("height", 1024),
).images[0]
```

Note: `negative_prompt` is ignored for FLUX (guidance-free architecture). `guidance_scale` is hardcoded 0 regardless of user input — surface this as a tooltip in the UI.

**Done when:** a job with custom steps/size produces an image at the right resolution.

---

### IP-4 — Frontend: Advanced params panel

**`frontend/src/components/ImageGenerator.tsx`** (or `ImageLabPage.tsx`)

New `AdvancedParams` component (inline or split file, ~120 lines):

```tsx
interface ParamState {
  enabled: boolean
  value: T
}

interface AdvancedParamsValue {
  aspectRatio:      ParamState<string>   // "1:1" | "16:9" | "9:16" | "4:3"
  steps:            ParamState<number>   // 4–50
  guidanceScale:    ParamState<number>   // 1.0–20.0
  negativePrompt:   ParamState<string>
  stylePreset:      ParamState<string>
}
```

Aspect ratio maps to pixel dimensions client-side before building the request payload:
```ts
const RATIO_TO_SIZE: Record<string, {width: number, height: number}> = {
  "1:1":  { width: 512,  height: 512  },
  "16:9": { width: 1024, height: 576  },
  "9:16": { width: 576,  height: 1024 },
  "4:3":  { width: 768,  height: 576  },
}
```

Each param row: `<label><input type="checkbox" /> <span>{label}</span> {control}</label>`. Control greyed (`opacity-40 pointer-events-none`) when unchecked.

**`frontend/src/api/client.ts`** — `runGenerate` and `submitSessionJob` accept an optional `params` object.

**Done when:** Advanced panel renders, checkboxes gate controls, params appear in the `POST /generate` payload (verify in Network tab), generated image matches the requested resolution.

---

## Out of Scope

- Saving param presets (user-named configurations) — deferred
- Per-model param visibility rules in the registry — hardcoded for now
- Cold-path params (only warm session for first iteration) — actually both paths accept params via IP-2

---

## Completion Checklist

- [ ] `image_jobs.params` JSONB column in Supabase
- [ ] `GenerateRequest` and `submit_session_job` accept and store params
- [ ] Style suffix applied on backend before storing
- [ ] SDXL notebook uses params from job row
- [ ] FLUX notebook uses params (guidance hardcoded 0, note in UI)
- [ ] Advanced panel renders in `ImageGenerator` with checkbox-per-param
- [ ] Unchecked → control greyed, default used; checked → value sent
- [ ] Aspect ratio maps to correct pixel dimensions
- [ ] Backend tests: params stored, style suffix applied
- [ ] `npm run build` clean
