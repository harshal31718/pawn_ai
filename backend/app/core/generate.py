"""Modality dispatch for Kaggle-backed generation.

One entry point per modality. Each loads the user's Kaggle creds, builds the
kernel source from a bundled template (payload base64-injected), runs it via the
generic `kaggle.run_kernel`, and parses the output. Blocking — callers invoke
these via run_in_threadpool.
"""

import json
import httpx
import base64
from app.constants import (
    KAGGLE_CUBE_SLUG,
    KAGGLE_CUBE_TEMPLATE,
    KAGGLE_TEMPLATES_DIR,
    KAGGLE_API_BASE,
)
from app.core import kaggle, key_store
from app.exceptions import KaggleError, NotConfiguredError


def _load_creds(user_id: str) -> dict:
    cfg = key_store.get_kaggle(user_id)
    if not cfg or not cfg.get("username") or not cfg.get("api_token"):
        raise NotConfiguredError(
            "Add your Kaggle username + API token in the Kaggle Lab to enable generation."
        )
    return cfg


def connect_kaggle(user_id: str) -> None:
    """First-time setup: push the image notebook to the user's account to verify connection."""
    cfg = _load_creds(user_id)
    template_path = KAGGLE_TEMPLATES_DIR / "image_gen" / "notebook.ipynb"
    source = kaggle.inject_payload(
        template_path.read_text(encoding="utf-8"),
        {"prompt": "warmup"},
    )
    headers = {}
    auth = None
    if cfg["api_token"].startswith("KGAT_"):
        headers["Authorization"] = f"Bearer {cfg['api_token']}"
    else:
        auth = (cfg["username"], cfg["api_token"])

    with httpx.Client(
        base_url=KAGGLE_API_BASE, auth=auth, headers=headers, timeout=30
    ) as client:
        kaggle._push(
            client,
            cfg["username"],
            "pawn-image-poc",
            "PAWN Image POC",
            source,
            enable_gpu=False,
            enable_internet=True,
            dataset_sources=["steubk/stable-diffusion-xl-base-1-0"],
            accelerator=None,
        )


def generate_image(user_id: str, prompt: str) -> dict:
    """Run SDXL image generation on the user's Kaggle account."""
    cfg = _load_creds(user_id)
    template_path = KAGGLE_TEMPLATES_DIR / "image_gen" / "notebook.ipynb"
    source = kaggle.inject_payload(
        template_path.read_text(encoding="utf-8"),
        {"prompt": prompt},
    )
    raw = kaggle.run_kernel(
        username=cfg["username"],
        api_token=cfg["api_token"],
        kernel_name="pawn-image-poc",
        title="PAWN Image POC",
        source=source,
        output_filename="out.png",
        enable_gpu=True,
        enable_internet=True,
        dataset_sources=["steubk/stable-diffusion-xl-base-1-0"],
        accelerator="NvidiaTeslaT4",
    )
    encoded = base64.b64encode(raw).decode("utf-8")
    return {
        "image": encoded,
        "mime": "image/png",
        "via": f"kaggle:{cfg['username']}/pawn-image-poc",
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
