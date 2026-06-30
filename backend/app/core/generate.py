"""Modality dispatch for Kaggle-backed generation.

One entry point per modality. Each loads the user's Kaggle creds, builds the
kernel source from a bundled template (payload base64-injected), runs it via the
generic `kaggle.run_kernel`, and parses the output. Blocking — callers invoke
these via run_in_threadpool.
"""

import json
import base64
from app.constants import (
    KAGGLE_CUBE_SLUG,
    KAGGLE_CUBE_TEMPLATE,
)
from app.core import kaggle, key_store
from app.core.image_models import DEFAULT_IMAGE_MODEL, ImageModel, get_image_model
from app.exceptions import KaggleError, NotConfiguredError


def _load_creds(user_id: str) -> dict:
    cfg = key_store.get_kaggle(user_id)
    if not cfg or not cfg.get("username") or not cfg.get("api_token"):
        raise NotConfiguredError(
            "Add your Kaggle username + API token in the Kaggle Lab to enable generation."
        )
    return cfg


def _kernel_title(spec: ImageModel) -> str:
    """Kaggle derives a notebook's slug from its title, so the title MUST slugify
    back to `spec.slug` — otherwise the push 409s ("title already in use") and the
    run never starts at our slug. Derive the title from the slug so the two can never
    drift: e.g. label "FLUX.1-schnell" would slugify to "...-1-schnell" and never
    match slug "pawn-image-flux", but slug → "Pawn Image Flux" → "pawn-image-flux"."""
    return spec.slug.replace("-", " ").title()


def connect_kaggle(user_id: str, model: str = DEFAULT_IMAGE_MODEL) -> None:
    """First-time setup for a model: push its notebook to the user's account to
    verify the connection and prime the slug.

    The warmup is deliberately **dataset-free** — the notebook's `prompt == "warmup"`
    branch writes a placeholder without touching the weights, so deploy stays fast
    even for a model whose dataset is tens of GB.
    """
    spec = get_image_model(model)  # validate model id before anything else (→ 400)
    cfg = _load_creds(user_id)
    source = kaggle.inject_payload(
        spec.template.read_text(encoding="utf-8"),
        {"prompt": "warmup"},
    )
    kaggle.deploy_kernel(
        username=cfg["username"],
        api_token=cfg["api_token"],
        kernel_name=spec.slug,
        title=_kernel_title(spec),
        source=source,
        enable_gpu=False,
        enable_internet=True,  # install cell still runs on warmup
        dataset_sources=[],
        accelerator=None,
    )


def generate_image(user_id: str, prompt: str, model: str = DEFAULT_IMAGE_MODEL) -> dict:
    """Run image generation for `model` on the user's Kaggle account.

    Model-agnostic: every detail (slug, notebook, dataset, accelerator, timeout)
    comes from the image-model registry, so SDXL and FLUX share this one path.
    """
    spec = get_image_model(model)  # validate model id before anything else (→ 400)
    cfg = _load_creds(user_id)
    source = kaggle.inject_payload(
        spec.template.read_text(encoding="utf-8"),
        {"prompt": prompt},
    )
    raw = kaggle.run_kernel(
        username=cfg["username"],
        api_token=cfg["api_token"],
        kernel_name=spec.slug,
        title=_kernel_title(spec),
        source=source,
        output_filename=spec.output_filename,
        enable_gpu=True,
        enable_internet=True,
        dataset_sources=[spec.dataset],
        accelerator=spec.accelerator,
        timeout=spec.run_timeout,
    )
    encoded = base64.b64encode(raw).decode("utf-8")
    return {
        "image": encoded,
        "mime": spec.mime,
        "model": spec.id,
        "via": f"kaggle:{cfg['username']}/{spec.slug}",
    }


def generate_cube(user_id: str, n: int) -> dict:
    """Proof-of-transport: run findCube(n) on the user's Kaggle account."""
    cfg = _load_creds(user_id)
    source = kaggle.inject_payload(
        KAGGLE_CUBE_TEMPLATE.read_text(encoding="utf-8"),
        {"input": n},
    )
    raw = kaggle.run_kernel(
        username=cfg["username"],
        api_token=cfg["api_token"],
        kernel_name=KAGGLE_CUBE_SLUG,
        title="PAWN Cube POC",
        source=source,
        output_filename="out.json",
        enable_gpu=False,
        enable_internet=False,
    )
    try:
        result = json.loads(raw.decode())
    except (ValueError, UnicodeDecodeError) as e:
        raise KaggleError("Kaggle returned an unreadable result.") from e
    return {
        "input": result.get("input", n),
        "result": result["result"],
        "via": f"kaggle:{cfg['username']}/{KAGGLE_CUBE_SLUG}",
    }
