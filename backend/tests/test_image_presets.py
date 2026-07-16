"""Tests for Q3.3a — image_presets.json registry (replaces the old hardcoded
STYLE_SUFFIXES dict in routes/generate.py). Behavior-preserving: same 5
presets, same suffix strings, same fallback-to-empty-string-on-unknown-key
semantics as the dict it replaces.
"""

from app.core.image_presets import IMAGE_PRESETS, get_preset_suffix


def test_registry_loads_five_presets():
    assert set(IMAGE_PRESETS) == {
        "photorealistic", "cinematic", "anime", "oil_painting", "sketch",
    }


def test_every_preset_has_a_label_and_a_suffix():
    for preset in IMAGE_PRESETS.values():
        assert preset["label"]
        assert preset["suffix"]


def test_get_preset_suffix_matches_legacy_strings():
    """Exact strings from the old hardcoded STYLE_SUFFIXES dict, preserved."""
    assert get_preset_suffix("photorealistic") == ", RAW photo, 8K, ultra detailed, photorealistic, DSLR"
    assert get_preset_suffix("cinematic") == ", cinematic shot, anamorphic lens, dramatic lighting, film grain"
    assert get_preset_suffix("anime") == ", anime style, studio ghibli, detailed illustration, vibrant colors"
    assert get_preset_suffix("oil_painting") == ", oil painting, impressionist, thick brushstrokes, canvas texture"
    assert get_preset_suffix("sketch") == ", pencil sketch, charcoal drawing, black and white, cross-hatching"


def test_get_preset_suffix_unknown_key_returns_empty_string():
    """Matches the old dict's `.get(key, "")` fallback -- a since-removed key
    from an old cached frontend must never raise or block generation."""
    assert get_preset_suffix("no-such-preset") == ""


def test_get_preset_suffix_none_returns_empty_string():
    assert get_preset_suffix(None) == ""


def test_get_preset_suffix_empty_string_returns_empty_string():
    assert get_preset_suffix("") == ""
