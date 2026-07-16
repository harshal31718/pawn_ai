"""Tests for Q3.3 — image_presets.json registry.

Q3.3a: replaced the old hardcoded STYLE_SUFFIXES dict with a JSON-backed
registry (5 style presets, one suffix each, no per-model variants).
Q3.3b: added per-model (SDXL/FLUX) suffix variants to every style preset, 4
new style presets (9 total), and a new orthogonal subject-type axis
(portrait/nature/product/architecture) with its own per-model suffixes. A
"multi-person/group" subject type was deliberately NOT added -- SDXL's
cross-attention doesn't segment per-subject, so results reliably degrade
regardless of prompt phrasing (per the user's explicit call, 2026-07-16).
"""

from app.core.image_presets import (
    IMAGE_STYLES,
    IMAGE_SUBJECT_TYPES,
    get_preset_suffix,
    get_subject_type_suffix,
)

_STYLE_IDS = {
    "photorealistic", "cinematic", "anime", "oil_painting", "sketch",
    "analog_film", "studio_product", "golden_hour", "editorial",
}
_SUBJECT_TYPE_IDS = {"portrait", "nature", "product", "architecture"}


# --- Registry shape -----------------------------------------------------------


def test_registry_loads_nine_style_presets():
    assert set(IMAGE_STYLES) == _STYLE_IDS


def test_registry_loads_four_subject_types():
    assert set(IMAGE_SUBJECT_TYPES) == _SUBJECT_TYPE_IDS


def test_every_style_has_a_label_and_both_model_suffixes():
    for style in IMAGE_STYLES.values():
        assert style["label"]
        assert style["sdxl_suffix"]
        assert style["flux_suffix"]


def test_every_subject_type_has_a_label_and_both_model_suffix_keys():
    for subject in IMAGE_SUBJECT_TYPES.values():
        assert subject["label"]
        assert "sdxl_suffix" in subject
        assert "flux_suffix" in subject


# --- Style suffix lookup (per-model) -------------------------------------------


def test_get_preset_suffix_sdxl_matches_legacy_strings():
    """Exact strings from Q3.3a / the original hardcoded STYLE_SUFFIXES dict,
    preserved for SDXL -- Q3.3b's per-model split must not change SDXL's
    existing behavior."""
    assert get_preset_suffix("photorealistic", "sdxl") == ", RAW photo, 8K, ultra detailed, photorealistic, DSLR"
    assert get_preset_suffix("cinematic", "sdxl") == ", cinematic shot, anamorphic lens, dramatic lighting, film grain"
    assert get_preset_suffix("anime", "sdxl") == ", anime style, studio ghibli, detailed illustration, vibrant colors"
    assert get_preset_suffix("oil_painting", "sdxl") == ", oil painting, impressionist, thick brushstrokes, canvas texture"
    assert get_preset_suffix("sketch", "sdxl") == ", pencil sketch, charcoal drawing, black and white, cross-hatching"


def test_get_preset_suffix_defaults_to_sdxl_when_model_omitted():
    """Backward compat for the Q3.3a call signature (no model_id arg)."""
    assert get_preset_suffix("cinematic") == get_preset_suffix("cinematic", "sdxl")


def test_get_preset_suffix_flux_variants_are_natural_language_not_keyword_soup():
    """FLUX prompting is different (Q3.1's research): natural-language
    sentences, not comma-separated keyword scaffolds. Spot-check a few --
    the FLUX variant should differ from the SDXL one and read as prose."""
    for style_id in ("photorealistic", "cinematic", "anime"):
        sdxl = get_preset_suffix(style_id, "sdxl")
        flux = get_preset_suffix(style_id, "flux")
        assert sdxl != flux
        assert flux.strip(", ")


def test_get_preset_suffix_unknown_key_returns_empty_string():
    """Matches the old dict's `.get(key, "")` fallback -- a since-removed key
    from an old cached frontend must never raise or block generation."""
    assert get_preset_suffix("no-such-preset") == ""


def test_get_preset_suffix_none_returns_empty_string():
    assert get_preset_suffix(None) == ""


def test_get_preset_suffix_empty_string_returns_empty_string():
    assert get_preset_suffix("") == ""


# --- Subject-type suffix lookup (per-model) ------------------------------------


def test_get_subject_type_suffix_portrait_is_empty_default_assumption():
    """Portrait is the existing default assumption -- no vocabulary
    injected, since single-person framing needs no extra hint."""
    assert get_subject_type_suffix("portrait", "sdxl") == ""
    assert get_subject_type_suffix("portrait", "flux") == ""


def test_get_subject_type_suffix_nature_differs_per_model():
    sdxl = get_subject_type_suffix("nature", "sdxl")
    flux = get_subject_type_suffix("nature", "flux")
    assert "landscape" in sdxl
    assert "landscape" in flux
    assert sdxl != flux


def test_get_subject_type_suffix_unknown_none_empty_all_fall_back():
    assert get_subject_type_suffix("no-such-subject") == ""
    assert get_subject_type_suffix(None) == ""
    assert get_subject_type_suffix("") == ""
