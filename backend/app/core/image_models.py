"""Image-generation model registry — the single source of truth for the
model-switch pipeline.

Each entry fully describes how to deploy and run one model on Kaggle: which
bundled notebook template to push, which slug it lives under in the user's
account, which dataset to mount, which accelerator to request, and how the
output is shaped. `core/generate.py` is model-agnostic — it just looks an entry
up here and feeds it into the generic `kaggle.run_kernel` / `kaggle.deploy_kernel`.

To add a model: drop a notebook under `kaggle_templates/image_<id>/notebook.ipynb`
(keeping the `__PAWN_PAYLOAD_B64__` placeholder + the `prompt == "warmup"`
short-circuit) and add one row below. No other backend code changes.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.constants import (
    KAGGLE_RUN_TIMEOUT_SECONDS,
    KAGGLE_TEMPLATES_DIR,
)
from app.exceptions import UnknownModelError


# SDXL is trained on ~1024²-area buckets; off-bucket sizes (e.g. the old
# SD1.5-era 576×1024) are the classic cause of half-generated/deformed bodies.
# All six values are already multiples of 16, so the same table also satisfies
# FLUX's "round to /16" requirement — no separate FLUX table needed.
_SDXL_NATIVE_BUCKETS: dict[str, tuple[int, int]] = {
    "1:1": (1024, 1024),
    "3:4": (896, 1152),
    "4:5": (832, 1216),
    "4:3": (1152, 896),
    "16:9": (1344, 768),
    "9:16": (768, 1344),
}


@dataclass(frozen=True)
class ImageModel:
    id: str                 # stable key used by the frontend + API ("sdxl", "flux")
    label: str              # human label (logs / titles)
    slug: str               # kernel slug suffix: full slug is "<username>/<slug>"
    template: Path          # bundled .ipynb pushed to the user's account
    dataset: str            # Kaggle dataset mounted for the weights
    accelerator: str        # machineShape value (NvidiaTeslaT4 → 2× T4 box)
    output_filename: str = "out.png"
    mime: str = "image/png"
    run_timeout: int = KAGGLE_RUN_TIMEOUT_SECONDS
    # --- Warm/persistent session (Phase W) ---
    # The notebook + slug pushed for a warm session (loads once, then serves a
    # Supabase work-loop). None → warm sessions aren't available for this model.
    session_template: Optional[Path] = None
    session_slug: Optional[str] = None
    session_gpu: bool = False  # FLUX needs the GPU + dataset; the CPU echo doesn't
    # Model-native resolution buckets, keyed by aspect-ratio label (Q1.1).
    # Server-side param snapping picks the nearest one by aspect-ratio distance.
    resolution_buckets: Optional[dict[str, tuple[int, int]]] = None
    # Which sampler the model's notebook templates configure (Q1.3) — informational
    # only today, since templates are static .ipynb files, not generated from this
    # registry at deploy time. Documents the choice as data so a future model can
    # declare its own without anyone having to go spelunking in notebook JSON.
    scheduler: str = "default"
    # Research-backed default negative prompt (Q3.2), merged with any user-supplied
    # negative prompt server-side. None for models that don't accept negatives at
    # all (FLUX is guidance-free — Q1.4 already hides the UI field for it).
    default_negative: Optional[str] = None


IMAGE_MODELS: dict[str, ImageModel] = {
    "sdxl": ImageModel(
        id="sdxl",
        label="SDXL",
        slug="pawn-image-sdxl",
        template=KAGGLE_TEMPLATES_DIR / "image_sdxl" / "notebook.ipynb",
        dataset="steubk/stable-diffusion-xl-base-1-0",
        accelerator="NvidiaTeslaT4",
        run_timeout=600,
        # Warm session: load SDXL once (~1–2 min on a single T4), then serve images
        # in seconds from the Supabase work-loop.
        session_template=KAGGLE_TEMPLATES_DIR / "image_sdxl_session" / "notebook.ipynb",
        session_slug="pawn-sdxl-session",
        session_gpu=True,
        resolution_buckets=_SDXL_NATIVE_BUCKETS,
        scheduler="dpmpp_2m_sde_karras",
        default_negative=(
            "cartoon, illustration, anime, painting, CGI, 3d render, "
            "unrealistic proportions, extra fingers, low quality, deformed, "
            "extra limbs, bad anatomy, blurry, watermark, text"
        ),
    ),
    "flux": ImageModel(
        id="flux",
        label="FLUX.1-schnell",
        slug="pawn-image-flux",
        template=KAGGLE_TEMPLATES_DIR / "image_flux" / "notebook.ipynb",
        dataset="guillaumegaillard/flux1-schnell-diffusers",
        accelerator="NvidiaTeslaT4",
        # FLUX mounts ~34 GB + loads a 12B model on first run — needs more headroom.
        run_timeout=900,
        # The real warm path: load FLUX once, then serve many prompts in seconds.
        session_template=KAGGLE_TEMPLATES_DIR / "image_flux_session" / "notebook.ipynb",
        session_slug="pawn-flux-session",
        session_gpu=True,
        resolution_buckets=_SDXL_NATIVE_BUCKETS,
    ),
}

DEFAULT_IMAGE_MODEL = "sdxl"


def get_image_model(model_id: str) -> ImageModel:
    """Look up a model by id, raising a typed error (→ HTTP 400) if unknown."""
    spec = IMAGE_MODELS.get(model_id)
    if spec is None:
        known = ", ".join(IMAGE_MODELS)
        raise UnknownModelError(f"Unknown image model '{model_id}'. Available: {known}.")
    return spec


def snap_resolution(
    model_id: str, width: Optional[int], height: Optional[int]
) -> tuple[Optional[int], Optional[int]]:
    """Snap an incoming (width, height) to the model's nearest native bucket by
    aspect-ratio distance. Protects API callers and old cached frontends that
    still send pre-Q1.1 (SD1.5-era) sizes. Passes `(None, None)` through
    unchanged so callers that never set a resolution keep the model's own
    pipeline default."""
    if width is None or height is None:
        return width, height
    buckets = get_image_model(model_id).resolution_buckets
    if not buckets or width <= 0 or height <= 0:
        return width, height
    target_ratio = width / height
    best_w, best_h = min(
        buckets.values(), key=lambda wh: abs((wh[0] / wh[1]) - target_ratio)
    )
    return best_w, best_h


# Style presets whose whole point is to move AWAY from photorealism (Q3.3's
# `STYLE_SUFFIXES` in routes/generate.py). The SDXL default negative below
# specifically bans "cartoon, illustration, anime, painting" -- applying it
# under one of these presets would have the prompt fight itself (e.g. "anime
# style, ... detailed illustration" as a positive suffix while the negative
# prompt simultaneously bans "illustration"/"anime"). Kept here, not in
# routes/generate.py, so this stays a single data-driven rule next to the
# default_negative value itself rather than logic duplicated at each call site.
NON_PHOTOREAL_STYLE_PRESETS = frozenset({"anime", "oil_painting", "sketch"})


def merge_negative_prompt(
    model_id: str, user_negative: Optional[str], style_preset: Optional[str] = None
) -> Optional[str]:
    """Prepend the model's research-backed default negative prompt (Q3.2) ahead
    of whatever the user supplied, comma-joined. A model with no default (FLUX)
    passes the user's value through unchanged. Empty/whitespace-only user input
    is treated the same as None, so an accidentally-enabled-but-blank negative-
    prompt field doesn't produce a trailing comma. Skipped entirely when a
    non-photoreal style preset is active (see NON_PHOTOREAL_STYLE_PRESETS) --
    the default is a photoreal-specific negative list and would otherwise
    contradict presets like "anime" or "oil_painting"."""
    default = get_image_model(model_id).default_negative
    user_negative = (user_negative or "").strip() or None
    if style_preset in NON_PHOTOREAL_STYLE_PRESETS:
        return user_negative
    if not default:
        return user_negative
    if not user_negative:
        return default
    return f"{default}, {user_negative}"
