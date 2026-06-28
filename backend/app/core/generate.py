"""Modality dispatch for Kaggle-backed generation.

One entry point per modality. Each loads the user's Kaggle creds, builds the
kernel source from a bundled template (payload base64-injected), runs it via the
generic `kaggle.run_kernel`, and parses the output. Blocking — callers invoke
these via run_in_threadpool.

Today: `generate_cube` (Milestone A.0 — proves the transport). `generate_image`
will live next to it and call the same `kaggle.run_kernel` with the image
template + GPU/internet enabled.
"""

import json

from app.constants import KAGGLE_CUBE_SLUG, KAGGLE_CUBE_TEMPLATE
from app.core import kaggle, key_store
from app.exceptions import KaggleError, NotConfiguredError


def _load_creds(user_id: str) -> dict:
    cfg = key_store.get_kaggle(user_id)
    if not cfg or not cfg.get("username") or not cfg.get("api_token"):
        raise NotConfiguredError(
            "Add your Kaggle username + API token in the Kaggle Lab to enable generation."
        )
    return cfg


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
