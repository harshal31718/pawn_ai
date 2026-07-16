"""Image-generation preset registry (Q3.3) — data, not code.

Two orthogonal, combinable axes:
- **Style** (visual treatment: photorealistic, cinematic, anime, ...) — Q3.3a's
  original 5 presets, replacing the old hardcoded `STYLE_SUFFIXES` dict in
  `routes/generate.py`.
- **Subject type** (portrait, nature, product, architecture) — new in Q3.3b,
  composes with any style preset. A "multi-person/group" entry was deliberately
  NOT added here: SDXL's cross-attention doesn't segment per-subject, so
  results reliably degrade (blended faces/limbs) regardless of prompt
  phrasing — not worth shipping a preset for a case the model handles poorly
  (per the user's explicit call, 2026-07-16). Revisit if/when a model with
  real multi-subject support (regional conditioning, ControlNet pose, etc.)
  is added.

Both axes carry per-model suffix variants (`sdxl_suffix` keyword-scaffold vs
`flux_suffix` natural-language, per Q3.1's research) instead of one suffix
shared across models. Loaded once at import time -- this file is bind-mounted
(`backend/data` in docker-compose.yml), so editing the JSON takes effect on
the next backend restart, no rebuild needed.
"""

import json

from app.constants import IMAGE_PRESETS_FILE


def _load_registry() -> tuple[dict[str, dict], dict[str, dict]]:
    raw = json.loads(IMAGE_PRESETS_FILE.read_text(encoding="utf-8"))
    styles = {entry["id"]: entry for entry in raw["styles"]}
    subject_types = {entry["id"]: entry for entry in raw["subject_types"]}
    return styles, subject_types


IMAGE_STYLES: dict[str, dict] = {}
IMAGE_SUBJECT_TYPES: dict[str, dict] = {}
IMAGE_STYLES, IMAGE_SUBJECT_TYPES = _load_registry()

# Back-compat alias: Q3.3a's original name, still used by a couple of test
# files/comments that predate the subject-type split.
IMAGE_PRESETS = IMAGE_STYLES


def _suffix_for(entry: dict | None, model_id: str) -> str:
    if entry is None:
        return ""
    return entry.get(f"{model_id}_suffix") or entry.get("sdxl_suffix", "")


def get_preset_suffix(preset_id: str | None, model_id: str = "sdxl") -> str:
    """Look up a style preset's prompt suffix by id, for the given model.
    Unknown/None id (a legacy cached frontend sending a since-removed key, or
    no preset selected) falls back to an empty string -- never raises,
    generation must never block on an unrecognized preset."""
    if not preset_id:
        return ""
    return _suffix_for(IMAGE_STYLES.get(preset_id), model_id)


def get_subject_type_suffix(subject_type_id: str | None, model_id: str = "sdxl") -> str:
    """Same contract as get_preset_suffix, for the subject-type axis. None/
    unknown/the default "portrait" id all resolve to an empty suffix (portrait
    is the existing default assumption -- no vocabulary injected)."""
    if not subject_type_id:
        return ""
    return _suffix_for(IMAGE_SUBJECT_TYPES.get(subject_type_id), model_id)
