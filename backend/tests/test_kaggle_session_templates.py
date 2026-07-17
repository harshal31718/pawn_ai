"""Integrity tests for the warm-session Kaggle notebook templates
(backend/app/kaggle_templates/image_{sdxl,flux}_session/notebook.ipynb).

These are plain .ipynb files, not Python modules — nothing else in the test
suite parses or compiles them, so a bad edit (invalid JSON, a syntax error
in a code cell, the payload placeholder silently dropped) would otherwise
only surface the next time someone actually pushes a session to Kaggle.
Locks in the shape the O.5/plan_imagelab_session_issues dead-session-
detection fix depends on: cell-0's rendezvous/supervisor machinery must
stay byte-identical between the two model-specific templates so a fix
applied to one always applies to both.
"""

import json

import pytest

from app.constants import KAGGLE_TEMPLATES_DIR
from app.core.image_models import IMAGE_MODELS
from app.core.kaggle import _PLACEHOLDER

_SESSION_TEMPLATE_PATHS = sorted(
    {spec.session_template for spec in IMAGE_MODELS.values() if spec.session_template}
)


@pytest.fixture(scope="module")
def session_notebooks():
    """{path: parsed nbformat dict} for every registered warm-session template."""
    return {path: json.loads(path.read_text(encoding="utf-8")) for path in _SESSION_TEMPLATE_PATHS}


def test_at_least_two_session_templates_registered():
    """Sanity check the fixture itself found the sdxl+flux templates -- a
    typo in image_models.py's session_template paths would otherwise make
    every test below vacuously pass over zero notebooks."""
    assert len(_SESSION_TEMPLATE_PATHS) >= 2


def test_session_templates_are_valid_json(session_notebooks):
    for path, nb in session_notebooks.items():
        assert "cells" in nb, path


def test_session_templates_contain_payload_placeholder(session_notebooks):
    for path, nb in session_notebooks.items():
        full_source = "".join("".join(c["source"]) for c in nb["cells"])
        assert _PLACEHOLDER in full_source, f"{path} is missing the payload placeholder"


def test_session_template_code_cells_all_compile(session_notebooks):
    for path, nb in session_notebooks.items():
        for i, cell in enumerate(nb["cells"]):
            if cell.get("cell_type") != "code":
                continue
            source = "".join(cell["source"])
            try:
                compile(source, f"{path.name}-cell{i}", "exec")
            except SyntaxError as e:
                pytest.fail(f"{path} cell {i} does not compile: {e}")


def test_session_templates_have_exactly_four_cells(session_notebooks):
    """setup/state (cell 0) -> deps install (1) -> model load (2) -> serve
    loop (3). A cell count drift here means the sdxl/flux templates have
    structurally diverged in a way the rest of this test module assumes
    they haven't."""
    for path, nb in session_notebooks.items():
        assert len(nb["cells"]) == 4, path


def test_session_template_cell0_bodies_are_identical(session_notebooks):
    """cell-0 (payload decode, REST helpers, heartbeat_during, the
    supervisor daemon) is deliberately model-agnostic and must stay
    byte-identical across every warm-session template -- only the leading
    comment header (model name) is allowed to differ. A dead-session-
    detection fix applied to one template must apply to all of them; this
    test fails loudly if a future edit touches only one."""
    marker = "import base64, json, time, datetime, io\n"
    bodies = {}
    for path, nb in session_notebooks.items():
        src = "".join(nb["cells"][0]["source"])
        assert marker in src, f"{path} cell 0 is missing the expected setup marker"
        bodies[path] = src.split(marker, 1)[1]
    distinct = set(bodies.values())
    assert len(distinct) == 1, (
        "Session template cell-0 bodies have diverged: "
        + ", ".join(str(p) for p in bodies)
    )


def test_session_template_writes_never_raise_unhandled(session_notebooks):
    """The core O.5 guarantee: PATCH calls to PostgREST must never be a bare
    `requests.patch(...)` with no error handling -- that's exactly the shape
    that let a dead tunnel's DNS error kill a session before its first
    heartbeat. Every write goes through the shared, never-raising
    _rest_patch helper instead."""
    for path, nb in session_notebooks.items():
        src = "".join(nb["cells"][0]["source"])
        assert "def _rest_patch(" in src, path
        assert "def patch_session(fields):\n    _rest_patch(" in src, path
        assert "def patch_job(job_id, fields):\n    _rest_patch(" in src, path


def test_session_template_next_job_honors_queue_pos(session_notebooks):
    """G1: manual queue reordering only works if the kernel's own dequeue
    query respects queue_pos ahead of the plain created_at FIFO order --
    otherwise the backend's reorder_queue() call would silently have no
    effect on which job actually runs next."""
    for path, nb in session_notebooks.items():
        src = "".join(nb["cells"][0]["source"])
        assert '"order": "queue_pos.asc.nullslast,created_at.asc"' in src, path
        assert '"order": "created_at.asc"' not in src, (
            f"{path}: old plain-FIFO order string should be fully replaced, not duplicated"
        )


def test_session_template_cell1_wraps_pip_install(session_notebooks):
    """cell-1's dependency install must report failure (status='error')
    instead of dying uncaught with zero trace, mirroring cell-2's model-load
    error handling."""
    for path, nb in session_notebooks.items():
        src = "".join(nb["cells"][1]["source"])
        assert "try:" in src and "dependency install failed" in src, path


def test_sdxl_session_template_has_fp16_vae_fix(session_notebooks):
    """Q1.2: the stock fp16 SDXL VAE overflows fp16 (>65504 activations ->
    inf/NaN), producing random black/broken decodes. The SDXL session
    template's model-load cell (cell-2) must load madebyollin's fp16-fix VAE
    and assign it onto the pipeline before it's moved to cuda. FLUX uses a
    different VAE architecture and is deliberately unaffected."""
    for path, nb in session_notebooks.items():
        src = "".join(nb["cells"][2]["source"])
        if "sdxl" in path.name.lower() or "sdxl" in str(path).lower():
            assert "madebyollin/sdxl-vae-fp16-fix" in src, f"{path} missing the VAE fix"
            assert "pipe.vae = vae" in src, f"{path} missing the VAE assignment"
            assert src.index("pipe.vae = vae") < src.index('pipe = pipe.to("cuda")'), (
                f"{path}: VAE must be assigned before the pipeline moves to cuda"
            )
        else:
            assert "madebyollin/sdxl-vae-fp16-fix" not in src, (
                f"{path}: SDXL-only VAE fix leaked into a non-SDXL template"
            )


def test_sdxl_session_template_has_scheduler_and_tuned_cfg(session_notebooks):
    """Q1.3: SDXL's model-load cell (cell-2) must configure DPM++ 2M SDE
    Karras after the VAE fix and before the pipeline moves to cuda, and the
    serve loop's (cell-3) inference calls must default guidance_scale to the
    tuned photoreal value (5, not the old 7.5) for BOTH the text2img and
    img2img branches. FLUX is unaffected."""
    for path, nb in session_notebooks.items():
        cell2 = "".join(nb["cells"][2]["source"])
        cell3 = "".join(nb["cells"][3]["source"])
        if "sdxl" in path.name.lower() or "sdxl" in str(path).lower():
            assert "DPMSolverMultistepScheduler" in cell2, f"{path} missing the scheduler"
            assert "use_karras_sigmas=True" in cell2, f"{path} missing karras sigmas"
            assert 'algorithm_type="sde-dpmsolver++"' in cell2, f"{path} missing sde-dpmsolver++"
            assert "euler_at_final=True" in cell2, f"{path} missing euler_at_final"
            assert cell2.index("pipe.vae = vae") < cell2.index(
                "DPMSolverMultistepScheduler.from_config"
            ), f"{path}: scheduler must be configured after the VAE fix"
            assert cell2.index("DPMSolverMultistepScheduler.from_config") < cell2.index(
                'pipe = pipe.to("cuda")'
            ), f"{path}: scheduler must be configured before the pipeline moves to cuda"
            assert cell3.count('guidance_scale=p.get("guidance_scale", 5)') == 2, (
                f"{path}: both text2img and img2img branches must default CFG to 5"
            )
            assert 'guidance_scale=p.get("guidance_scale", 7.5)' not in cell3, (
                f"{path}: old CFG default 7.5 still present"
            )
        else:
            assert "DPMSolverMultistepScheduler" not in cell2, (
                f"{path}: SDXL-only scheduler swap leaked into a non-SDXL template"
            )


def test_session_template_serve_loop_honors_seed(session_notebooks):
    """Q1.4: both SDXL and FLUX serve loops (cell-3) must build a
    torch.Generator seeded from the job's `seed` param when present, and pass
    it into BOTH the text2img and img2img inference calls -- unlike Q1.2/Q1.3,
    this applies to every model's session template, not just SDXL."""
    for path, nb in session_notebooks.items():
        cell3 = "".join(nb["cells"][3]["source"])
        assert 'seed = p.get("seed")' in cell3, f"{path} missing seed extraction"
        assert (
            'generator = torch.Generator(device="cuda").manual_seed(seed) if seed is not None else None'
            in cell3
        ), f"{path} missing the generator construction"
        assert cell3.count("generator=generator,") == 2, (
            f"{path}: both text2img and img2img branches must pass the seeded generator"
        )
        assert cell3.index('seed = p.get("seed")') < cell3.index("generator=generator,"), (
            f"{path}: seed must be resolved before it's used in an inference call"
        )


def test_session_template_supervisor_has_unreachable_self_exit(session_notebooks):
    """The supervisor must eventually give up and free the GPU if PostgREST
    is unreachable for the kernel's entire life -- otherwise a dead-tunnel
    kernel just burns quota until Kaggle's own ~12h cap with no trace."""
    for path, nb in session_notebooks.items():
        src = "".join(nb["cells"][0]["source"])
        assert "_REST_UNREACHABLE_EXIT_SECONDS" in src, path
        assert "os._exit(1)" in src, path
