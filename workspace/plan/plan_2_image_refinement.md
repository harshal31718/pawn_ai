# Plan 4 — Image Refinement (img2img + Iterative Improvement)

**Branch:** `imageLab`
**Prerequisite:** Plan 1 (image params) — adds the `params` column and pass-through that this plan extends.
**Scope:** Two entry points for img2img: (1) upload a source image alongside the prompt; (2) click Refine on a completed generation to iterate on it. Both flow through the same backend and notebook path.

---

## UI Design

### Entry Point A — Upload image with prompt

In `ImageGenerator`, the prompt row gets an image attachment slot:

```
┌─ Image Input (optional) ─────────────────────────────┐
│  [ + Add image ]                                      │
│    or drag & drop                                     │
└───────────────────────────────────────────────────────┘

┌─ Prompt ─────────────────────────────────────────────┐
│ [describe what you want to keep or change...        ] │
└───────────────────────────────────────────────────────┘

▼ Advanced
  ☐ Strength  ──●──────  0.6   (0.1 – 1.0)
                (lower = stay closer to source image)
  ... (other params from Plan 1)

[Generate]
```

Once an image is attached, a preview chip appears:

```
┌──────────────────────────────────────────────────────┐
│  🖼 source.png  ×                                    │
│  [──────────────────────────────]  320×240 preview   │
└──────────────────────────────────────────────────────┘
```

### Entry Point B — Refine from Generations panel

Each completed generation in `GenerationsPanel` shows a **Refine** button alongside View / Download:

```
┌─ Generations ────────────────────────────────────────┐
│  ● done   SDXL   a cinematic mountain...   5m ago    │
│  [thumbnail]  [Refine ↺]  [View]  [Download]         │
└───────────────────────────────────────────────────────┘
```

Clicking **Refine** on a generation:
1. Scrolls to / focuses that model's `ImageGenerator`
2. Pre-loads the generation's image as the init image (no upload needed — fetched via `getJob`)
3. Shows a chip: `🔄 Refining: [prompt truncated...] ×`
4. Clears the prompt box with hint text: _"Describe what to change…"_
5. Sets Strength to 0.6 by default (checkbox auto-enabled)

```
[ImageGenerator — SDXL]

 🔄  Refining: "a cinematic mountain at sunset..."  ×
 [┌────────────────────────────────────┐]
  │  [small thumbnail of source gen]   │
  └────────────────────────────────────┘

 Prompt: [make the sky more dramatic, add lightning]

 ▼ Advanced
   ✅ Strength   ──●──────  0.6

 [Generate]
```

---

## Architecture

```
Frontend
  └─ ImageGenerator
       ├─ initImage state: { src: blob | job_id | null, preview: dataURL }
       └─ GenerationsPanel → Refine button → sets initImage from job

Backend (routes/generate.py)
  └─ GenerateRequest
       ├─ init_image_b64: str | None   (base64 PNG/JPEG, sent for upload flow)
       └─ init_job_id: str | None      (job id, backend fetches b64 from Supabase)

  └─ image_session.submit_session_job / create_cold_job
       └─ params JSONB ← extends Plan 1 params with:
            strength: float | None
            init_image_b64: str | None   (stored temporarily for notebook pickup)

Supabase (image_jobs)
  └─ params JSONB (already added in Plan 1)
       └─ init_image_b64 stored here for warm-path pickup by notebook
          (cold path: passed directly to the generate worker)

Notebooks (SDXL + FLUX)
  └─ if init_image_b64 in params → img2img pipeline branch
  └─ else → text2img pipeline (existing behaviour)
```

---

## Steps

### IR-1 — Backend: init image routing

**`backend/app/routes/generate.py`**

Extend `GenerateRequest`:
```python
class GenerateRequest(BaseModel):
    prompt: str
    model: str = "sdxl"
    params: ImageJobParams = ImageJobParams()
    init_image_b64: str | None = None   # direct upload
    init_job_id: str | None = None      # refine from existing job
```

Resolution logic (in the route, before creating the job):
```python
async def _resolve_init_image(init_image_b64, init_job_id, user_id) -> str | None:
    if init_image_b64:
        return init_image_b64
    if init_job_id:
        job = await run_in_threadpool(get_job, init_job_id)
        if job and job.get("image_b64") and job.get("user_id") == user_id:
            return job["image_b64"]
    return None
```

The resolved `init_image_b64` is stored inside `params` JSONB alongside strength:
```python
params_dict = request.params.model_dump(exclude_none=True)
if init_b64:
    params_dict["init_image_b64"] = init_b64
    params_dict.setdefault("strength", 0.6)
```

**`backend/app/core/image_session.py`**

`ImageJobParams` gains:
```python
strength: float | None = None        # 0.1–1.0
init_image_b64: str | None = None    # stored transiently in JSONB
```

**Tests:**
- `init_job_id` → `init_image_b64` resolved correctly from existing job
- User can't refine another user's job (user_id check)
- `init_image_b64` stored in `params` JSONB on the job row

**Done when:** `POST /generate` with `init_job_id` creates a job row with `params.init_image_b64` populated.

---

### IR-2 — Notebook updates (SDXL + FLUX)

Both notebooks add an img2img branch in the serve-loop inference cell.

**SDXL serve-loop (cell 3):**
```python
from diffusers import AutoPipelineForText2Image, AutoPipelineForImage2Image
from PIL import Image
import base64, io

p = job.get("params", {})
init_b64 = p.get("init_image_b64")

if init_b64:
    # img2img branch
    img_bytes = base64.b64decode(init_b64)
    init_image = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    img2img_pipe = AutoPipelineForImage2Image.from_pipe(pipe)
    image = img2img_pipe(
        prompt=job["prompt"],
        image=init_image,
        strength=p.get("strength", 0.6),
        negative_prompt=p.get("negative_prompt", ""),
        num_inference_steps=p.get("num_inference_steps", 20),
        guidance_scale=p.get("guidance_scale", 7.5),
    ).images[0]
else:
    # text2img branch (existing)
    image = pipe(prompt=job["prompt"], ...).images[0]
```

**FLUX serve-loop (cell 3):**
```python
from diffusers import FluxImg2ImgPipeline

if init_b64:
    init_image = Image.open(io.BytesIO(base64.b64decode(init_b64))).convert("RGB")
    # Reuse weights — no second load
    img2img_pipe = FluxImg2ImgPipeline(**pipe.components)
    image = img2img_pipe(
        prompt=job["prompt"],
        image=init_image,
        strength=p.get("strength", 0.6),
        num_inference_steps=p.get("num_inference_steps", 4),
        guidance_scale=0.0,
    ).images[0]
else:
    image = pipe(prompt=job["prompt"], ...).images[0]
```

Note: `AutoPipelineForImage2Image.from_pipe` reuses already-loaded weights — no extra model load time.

**Done when:** submitting a job with `params.init_image_b64` returns an image visibly influenced by the source image.

---

### IR-3 — Frontend: image attachment in ImageGenerator

**New state in `ImageGenerator`:**
```tsx
const [initImage, setInitImage] = useState<{
  src: string       // base64 dataURL for preview
  b64: string       // raw base64 to send (no data: prefix)
  label: string     // filename or "Refining: [prompt...]"
  isRefinement: boolean
} | null>(null)
```

**UI elements:**
- `+ Add image` button (hidden file input, accepts `image/*`)
- On file select: `FileReader.readAsDataURL` → set `initImage`
- Attachment chip with label + `×` to clear
- Strength row auto-appears (with checkbox pre-checked) when `initImage` is set
- On generate: include `init_image_b64: initImage.b64` in the request payload

**`GenerationsPanel.tsx`** — Refine button:
```tsx
<button onClick={() => onRefine(job)}>↺ Refine</button>
```

`onRefine` prop bubbles up to `ModelPanel` → `ImageGenerator`:
```tsx
function handleRefine(job: JobResult) {
  // fetch the full image if not in memory
  getJob(job.job_id).then(full => {
    setInitImage({
      src: `data:image/png;base64,${full.image_b64}`,
      b64: full.image_b64,
      label: `Refining: "${job.prompt.slice(0, 40)}…"`,
      isRefinement: true,
    })
    generatorRef.current?.scrollIntoView({ behavior: 'smooth' })
    generatorRef.current?.focusPrompt()
  })
}
```

**`frontend/src/api/client.ts`** — `runGenerate` and `submitSessionJob` accept `init_image_b64?: string`.

**Done when:**
- Drag/drop or file picker loads a source image into the generator chip
- Clicking Refine in GenerationsPanel pre-loads the generation + scrolls to generator
- Generated result is visibly influenced by the source image at strength 0.6

---

## Out of Scope

- Storing init images in Supabase Storage (using JSONB inline — fine at ~1 MB per image)
- Inpainting / masking (paint over part of an image) — separate feature
- Stylizing as a separate tab — covered by style presets in Plan 1
- Video refinement — deferred

---

## Completion Checklist

- [ ] Backend resolves `init_image_b64` from upload or existing job (with user_id guard)
- [ ] `params.init_image_b64` + `params.strength` stored in job row JSONB
- [ ] SDXL notebook: img2img branch using `from_pipe` (no extra load)
- [ ] FLUX notebook: img2img branch using shared components
- [ ] Frontend: `+ Add image` button + file reader → chip + preview
- [ ] Frontend: Strength param row auto-appears when image attached
- [ ] GenerationsPanel: Refine button populates generator with source image
- [ ] Refine scrolls to generator and focuses prompt
- [ ] `init_image_b64` sent in generate/session-job requests
- [ ] Backend tests: init_job_id resolution, user_id isolation
- [ ] `npm run build` clean
