"""Tests for Q1.1 — SDXL-native resolution buckets + server-side snapping.

Pure logic, no external calls — `image_models.py` is a static registry.
"""

import pytest

from app.core.image_models import IMAGE_MODELS, merge_negative_prompt, snap_resolution
from app.exceptions import UnknownModelError


def test_sdxl_and_flux_have_six_native_buckets():
    for model_id in ("sdxl", "flux"):
        buckets = IMAGE_MODELS[model_id].resolution_buckets
        assert set(buckets) == {"1:1", "3:4", "4:5", "4:3", "16:9", "9:16"}


def test_all_bucket_dimensions_are_multiples_of_16():
    for model in IMAGE_MODELS.values():
        for w, h in model.resolution_buckets.values():
            assert w % 16 == 0
            assert h % 16 == 0


def test_snap_resolution_none_passthrough():
    assert snap_resolution("sdxl", None, None) == (None, None)
    assert snap_resolution("sdxl", 512, None) == (512, None)


def test_snap_resolution_old_sd15_portrait_snaps_to_9_16_bucket():
    """The exact regression this step exists to fix: the old SD1.5-era default
    (576x1024, ~9:16) must snap onto the new SDXL-native 9:16 bucket."""
    assert snap_resolution("sdxl", 576, 1024) == (768, 1344)


def test_snap_resolution_old_sd15_square_snaps_to_1_1_bucket():
    assert snap_resolution("sdxl", 512, 512) == (1024, 1024)


def test_snap_resolution_old_sd15_landscape_snaps_to_16_9_bucket():
    assert snap_resolution("sdxl", 1024, 576) == (1344, 768)


def test_snap_resolution_exact_bucket_is_a_noop():
    assert snap_resolution("sdxl", 896, 1152) == (896, 1152)


def test_snap_resolution_flux_uses_same_bucket_table():
    assert snap_resolution("flux", 576, 1024) == (768, 1344)


def test_snap_resolution_unknown_model_raises():
    with pytest.raises(UnknownModelError):
        snap_resolution("nope", 512, 512)


def test_snap_resolution_zero_or_negative_dimension_passes_through():
    """A malicious/malformed caller sending height=0 must not 500 the request
    with a ZeroDivisionError -- pass the (invalid) value through unchanged and
    let it fail downstream validation instead."""
    assert snap_resolution("sdxl", 512, 0) == (512, 0)
    assert snap_resolution("sdxl", 0, 512) == (0, 512)
    assert snap_resolution("sdxl", -100, 512) == (-100, 512)


# --- Q3.2: default negative prompt merge ------------------------------------


def test_sdxl_has_a_default_negative_flux_does_not():
    assert IMAGE_MODELS["sdxl"].default_negative
    assert "blurry" in IMAGE_MODELS["sdxl"].default_negative
    assert IMAGE_MODELS["flux"].default_negative is None


def test_merge_negative_prompt_default_only():
    """No user negative supplied -> the SDXL default alone."""
    merged = merge_negative_prompt("sdxl", None)
    assert merged == IMAGE_MODELS["sdxl"].default_negative


def test_merge_negative_prompt_user_only_on_flux():
    """FLUX has no default -> the user's value passes through unchanged."""
    assert merge_negative_prompt("flux", "extra shadows") == "extra shadows"


def test_merge_negative_prompt_both_default_and_user():
    merged = merge_negative_prompt("sdxl", "extra shadows")
    assert merged == f"{IMAGE_MODELS['sdxl'].default_negative}, extra shadows"


def test_merge_negative_prompt_blank_user_input_treated_as_none():
    """An enabled-but-empty negative-prompt field must not produce a
    trailing comma or a lone whitespace string."""
    assert merge_negative_prompt("sdxl", "") == IMAGE_MODELS["sdxl"].default_negative
    assert merge_negative_prompt("sdxl", "   ") == IMAGE_MODELS["sdxl"].default_negative
    assert merge_negative_prompt("flux", "") is None
    assert merge_negative_prompt("flux", None) is None


def test_merge_negative_prompt_unknown_model_raises():
    with pytest.raises(UnknownModelError):
        merge_negative_prompt("nope", "blurry")


def test_merge_negative_prompt_skipped_under_non_photoreal_style_presets():
    """The photoreal default negative bans 'cartoon, illustration, anime,
    painting' -- directly contradicting the anime/oil_painting/sketch style
    presets, which ADD those exact words as positive prompt suffixes
    (routes/generate.py's STYLE_SUFFIXES). Must be skipped under those
    presets, not applied and left to fight the prompt."""
    for preset in ("anime", "oil_painting", "sketch"):
        assert merge_negative_prompt("sdxl", None, preset) is None
        assert merge_negative_prompt("sdxl", "extra shadows", preset) == "extra shadows"


def test_merge_negative_prompt_applies_under_photoreal_style_presets():
    for preset in (None, "photorealistic", "cinematic"):
        assert merge_negative_prompt("sdxl", None, preset) == IMAGE_MODELS["sdxl"].default_negative
