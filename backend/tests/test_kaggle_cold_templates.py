"""Integrity tests for the cold one-shot Kaggle notebook templates
(backend/app/kaggle_templates/image_{sdxl,flux}/notebook.ipynb).

Same rationale as test_kaggle_session_templates.py: these are plain .ipynb
files, not Python modules, so a bad edit would otherwise only surface the
next time someone actually pushes a cold job to Kaggle.
"""

import json

import pytest

from app.core.image_models import IMAGE_MODELS
from app.core.kaggle import _PLACEHOLDER

_COLD_TEMPLATE_PATHS = sorted({spec.template for spec in IMAGE_MODELS.values()})


@pytest.fixture(scope="module")
def cold_notebooks():
    return {path: json.loads(path.read_text(encoding="utf-8")) for path in _COLD_TEMPLATE_PATHS}


def test_at_least_two_cold_templates_registered():
    assert len(_COLD_TEMPLATE_PATHS) >= 2


def test_cold_templates_are_valid_json(cold_notebooks):
    for path, nb in cold_notebooks.items():
        assert "cells" in nb, path


def test_cold_templates_contain_payload_placeholder(cold_notebooks):
    for path, nb in cold_notebooks.items():
        full_source = "".join("".join(c["source"]) for c in nb["cells"])
        assert _PLACEHOLDER in full_source, f"{path} is missing the payload placeholder"


def test_cold_template_code_cells_all_compile(cold_notebooks):
    for path, nb in cold_notebooks.items():
        for i, cell in enumerate(nb["cells"]):
            if cell.get("cell_type") not in (None, "code"):
                continue
            source = "".join(cell["source"])
            try:
                compile(source, f"{path.name}-cell{i}", "exec")
            except SyntaxError as e:
                pytest.fail(f"{path} cell {i} does not compile: {e}")


def test_sdxl_cold_template_has_fp16_vae_fix(cold_notebooks):
    """Q1.2: same fp16-overflow black-image fix as the SDXL session
    template, applied to the cold one-shot path's inference cell. FLUX is
    deliberately unaffected (different VAE architecture)."""
    for path, nb in cold_notebooks.items():
        full_source = "".join("".join(c["source"]) for c in nb["cells"])
        if "sdxl" in str(path).lower():
            assert "madebyollin/sdxl-vae-fp16-fix" in full_source, f"{path} missing the VAE fix"
            assert "pipe.vae = vae" in full_source, f"{path} missing the VAE assignment"
            assert full_source.index("pipe.vae = vae") < full_source.index(
                'pipe = pipe.to("cuda")'
            ), f"{path}: VAE must be assigned before the pipeline moves to cuda"
        else:
            assert "madebyollin/sdxl-vae-fp16-fix" not in full_source, (
                f"{path}: SDXL-only VAE fix leaked into a non-SDXL template"
            )
