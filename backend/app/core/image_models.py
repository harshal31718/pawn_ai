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

from app.constants import (
    KAGGLE_RUN_TIMEOUT_SECONDS,
    KAGGLE_TEMPLATES_DIR,
)
from app.exceptions import UnknownModelError


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


IMAGE_MODELS: dict[str, ImageModel] = {
    "sdxl": ImageModel(
        id="sdxl",
        label="SDXL",
        slug="pawn-image-sdxl",
        template=KAGGLE_TEMPLATES_DIR / "image_sdxl" / "notebook.ipynb",
        dataset="steubk/stable-diffusion-xl-base-1-0",
        accelerator="NvidiaTeslaT4",
        run_timeout=600,
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
