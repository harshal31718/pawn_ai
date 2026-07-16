"""Image-generation style preset registry (Q3.3a) — data, not code.

Replaces the old hardcoded `STYLE_SUFFIXES` dict in `routes/generate.py` with a
JSON-backed registry, following the same data/registry/*.json convention the
chat model registry (`models.json`/`endpoints.json`) already uses. Loaded once
at import time — this file is bind-mounted (`backend/data` in docker-compose.yml),
so editing the JSON takes effect on the next backend restart, no rebuild needed.

Q3.3a is deliberately behavior-preserving: same 5 presets, same suffix strings,
same single-suffix-per-preset shape (no per-model SDXL/FLUX variants yet). The
per-model variants and the new subject-type axis (portrait/multi-person/nature/
product/architecture) are Q3.3b, once this registry-load foundation is proven.
"""

import json

from app.constants import IMAGE_PRESETS_FILE


def _load_presets() -> dict[str, dict[str, str]]:
    raw = json.loads(IMAGE_PRESETS_FILE.read_text(encoding="utf-8"))
    presets: dict[str, dict[str, str]] = {}
    for entry in raw:
        presets[entry["id"]] = {"label": entry["label"], "suffix": entry["suffix"]}
    return presets


IMAGE_PRESETS: dict[str, dict[str, str]] = _load_presets()


def get_preset_suffix(preset_id: str | None) -> str:
    """Look up a style preset's prompt suffix by id. Unknown/None id (a legacy
    cached frontend sending a since-removed key, or no preset selected) falls
    back to an empty string, matching the old dict's `.get(key, "")` behavior
    -- never raises, generation must never block on an unrecognized preset."""
    if not preset_id:
        return ""
    preset = IMAGE_PRESETS.get(preset_id)
    return preset["suffix"] if preset else ""
