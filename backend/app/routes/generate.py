"""Kaggle-backed generation route.

POST /generate — body {modality, input?, prompt?}.
POST /generate/connect — verify connection and push the notebook.

The Kaggle call runs in run_in_threadpool (it blocks for minutes). A per-user
lock serialises a single user's runs — one kernel slug is single-writer, so two
concurrent runs would clobber the same kernel version. Different users run in
parallel.
"""

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.core import generate, image_session, vision_enhance
from app.core.image_models import DEFAULT_IMAGE_MODEL, get_image_model
from app.core.image_presets import get_preset_suffix, get_subject_type_suffix
from app.core.image_session import ImageJobParams

router = APIRouter(prefix="/generate", tags=["generate"])

# Locks are keyed per (user, model/modality): a kernel slug is single-writer, so two
# concurrent runs of the SAME model would clobber the same version — but a user may
# run different models in parallel, and different users never block each other.
_locks: dict[str, asyncio.Lock] = {}


def _lock_for(key: str) -> asyncio.Lock:
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock


# Q3.1 pass 2: 3-state selection mechanism (plan §3.1.4) -- Auto (rule-based
# gate decides, default), Always (force the enhancer), Off (never enhance).
EnhanceMode = Literal["auto", "always", "off"]


class GenerateRequest(BaseModel):
    modality: str = "image"
    input: int | None = None
    prompt: str | None = None
    model: str = DEFAULT_IMAGE_MODEL
    params: ImageJobParams = ImageJobParams()
    init_image_b64: str | None = None   # direct base64 upload
    init_job_id: str | None = None      # refine an existing done job
    enhance_prompt: EnhanceMode = "auto"


class ConnectRequest(BaseModel):
    model: str = DEFAULT_IMAGE_MODEL


class SessionStartRequest(BaseModel):
    model: str = DEFAULT_IMAGE_MODEL
    duration_minutes: int = 60
    max_images: int | None = None


class SessionJobRequest(BaseModel):
    session_id: str
    prompt: str
    params: ImageJobParams = ImageJobParams()
    init_image_b64: str | None = None   # direct base64 upload
    init_job_id: str | None = None      # refine an existing done job
    enhance_prompt: EnhanceMode = "auto"


class SessionStopRequest(BaseModel):
    session_id: str


class SessionExtendRequest(BaseModel):
    session_id: str
    add_minutes: int = 30


class ReorderQueueRequest(BaseModel):
    session_id: str
    job_ids: list[str]


async def _resolve_init_image(
    init_image_b64: str | None,
    init_job_id: str | None,
    user_id: str,
) -> str | None:
    """Resolve the init image for img2img: direct upload takes priority; otherwise
    fetch the image_b64 from an existing job (scoped to user_id so users can't
    refine each other's jobs)."""
    if init_image_b64:
        return init_image_b64
    if init_job_id:
        job = await run_in_threadpool(image_session.get_job, user_id, init_job_id)
        if job and job.get("image_b64"):
            return job["image_b64"]
    return None


async def _apply_prompt_enhancement(
    prompt: str,
    model_id: str,
    mode: EnhanceMode,
    image_b64: str | None,
    request: Request,
    user_id: str,
) -> tuple[str, str | None, str | None, str | None]:
    """Q3.1 pass 2: runs the vision-grounded enhancer (vision_enhance.py, Q3.1
    pass 1) ahead of style/subject suffix composition, per the rule-based-
    default/LLM-based-extra selection mechanism in
    phase_Q3_prompting_presets.md §3.1.4. `image_b64`, when present, is the
    resolved img2img reference image -- enhancement still runs text-only
    without one.

    Returns (prompt_to_use, original_prompt, enhanced_prompt, extra_negative).
    The last three are None whenever nothing changed (mode="off", the target
    model has no PromptSchema, the Auto gate says the prompt is already
    scaffolded, or the enhancer degraded to the raw prompt) -- callers persist
    "no enhancement happened" honestly instead of storing a duplicate of the
    prompt as its own "enhanced" version.
    """
    if mode == "off":
        return prompt, None, None, None
    schema = get_image_model(model_id).prompt_schema
    if schema is None:
        return prompt, None, None, None
    if mode == "auto" and not vision_enhance.needs_enhancement(prompt):
        return prompt, None, None, None
    result = await vision_enhance.enhance_with_vision(
        prompt,
        image_b64,
        schema,
        request.app.state.resolver,
        request.app.state.rate_limiter,
        user_id=user_id,
    )
    if result["degraded"]:
        return prompt, None, None, None
    return result["prompt"], prompt, result["prompt"], result.get("negative")


def _finalize_original_prompt(
    original_prompt: str | None, pre_suffix_prompt: str, final_prompt: str
) -> str | None:
    """G1: broadens original_prompt (Q3.1 pass 2) to also cover suffix-only jobs
    (style/subject-type preset appended, no enhancer run). If the enhancer already
    set it, that's the true pre-enhancement raw text and takes precedence -- suffix
    composition happening on top of an enhanced prompt doesn't change what the user
    originally typed. Otherwise, falls back to the pre-suffix text only when suffix
    composition actually changed the prompt, keeping the "None means nothing
    changed" contract intact for plain jobs with no preset and no enhancement."""
    if original_prompt is not None:
        return original_prompt
    return pre_suffix_prompt if final_prompt != pre_suffix_prompt else None


@router.post("/connect")
async def connect_kaggle(request: Request, req: ConnectRequest | None = None):
    user_id = request.state.user_id
    model = req.model if req else DEFAULT_IMAGE_MODEL
    async with _lock_for(f"{user_id}:{model}"):
        await run_in_threadpool(generate.connect_kaggle, user_id, model)
    return {"status": "ok"}


@router.post("")
async def generate_artifact(req: GenerateRequest, request: Request):
    user_id = request.state.user_id

    if req.modality == "cube":
        if req.input is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Field 'input' is required for the cube modality.",
            )
        async with _lock_for(f"{user_id}:cube"):
            return await run_in_threadpool(generate.generate_cube, user_id, req.input)

    elif req.modality == "image":
        if not req.prompt or not req.prompt.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Field 'prompt' is required for the image modality.",
            )
        prompt = req.prompt.strip()
        init_b64 = await _resolve_init_image(req.init_image_b64, req.init_job_id, user_id)
        prompt, original_prompt, enhanced_prompt, extra_negative = await _apply_prompt_enhancement(
            prompt, req.model, req.enhance_prompt, init_b64, request, user_id
        )
        pre_suffix_prompt = prompt
        if req.params.style_preset:
            prompt += get_preset_suffix(req.params.style_preset, req.model)
        if req.params.subject_type:
            prompt += get_subject_type_suffix(req.params.subject_type, req.model)
        original_prompt = _finalize_original_prompt(original_prompt, pre_suffix_prompt, prompt)
        params = req.params
        params_dict = params.model_dump()
        mutated = False
        if init_b64:
            params_dict["init_image_b64"] = init_b64
            if params_dict.get("strength") is None:
                params_dict["strength"] = 0.6
            mutated = True
        if extra_negative:
            existing_negative = params_dict.get("negative_prompt")
            params_dict["negative_prompt"] = (
                f"{existing_negative}, {extra_negative}" if existing_negative else extra_negative
            )
            mutated = True
        if mutated:
            params = image_session.ImageJobParams(**params_dict)
        # Non-blocking: create a durable job row (de-duped per user+model) and run
        # the slow Kaggle round-trip as a fire-and-forget background task, returning
        # the job id immediately. Unknown model → UnknownModelError (400) here.
        # RuntimeError → 400: raised when a live warm session already exists for this
        # model (cold job would waste a GPU slot alongside the running warm kernel).
        try:
            job_id, created = await run_in_threadpool(
                image_session.create_cold_job, user_id, req.model, prompt, params,
                original_prompt, enhanced_prompt,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        if created:
            # F-1 fix: spawn via image_session's own shared lock/task registry
            # (not this module's _lock_for/_spawn_bg) -- the chat generate_image
            # tool creates cold jobs too, and both entry points must serialize
            # against the SAME lock per (user, model), or two cold runs of the
            # same model triggered from different places (Image Lab UI vs. chat)
            # could race the same single-writer Kaggle kernel slug.
            image_session.spawn_cold_job_bg(user_id, req.model, job_id)
        return {"job_id": job_id, "status": "queued"}

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Modality '{req.modality}' is not supported yet.",
        )


# --- Warm sessions + durable jobs (Phase W) ---------------------------------
# Every generation is a durable image_jobs row tracked from the server, so the UI
# survives refresh/tab-switch and the button derives from job state (no duplicate
# submit). Supabase/Kaggle work is blocking → off-loaded to the threadpool.


@router.get("/jobs")
async def list_jobs(request: Request, model: str | None = None, limit: int = 20):
    user_id = request.state.user_id
    return await run_in_threadpool(image_session.list_jobs, user_id, model, limit)


@router.post("/session/start")
async def session_start(req: SessionStartRequest, request: Request):
    user_id = request.state.user_id
    # Serialise a model's session start with its cold runs (single-writer slug).
    async with _lock_for(f"{user_id}:{req.model}"):
        return await run_in_threadpool(
            image_session.start_session,
            user_id,
            req.model,
            req.duration_minutes,
            req.max_images,
        )


@router.get("/session/status")
async def session_status(request: Request, model: str = DEFAULT_IMAGE_MODEL):
    user_id = request.state.user_id
    return await run_in_threadpool(image_session.get_session_status, user_id, model)


@router.post("/session/job")
async def session_job(req: SessionJobRequest, request: Request):
    user_id = request.state.user_id
    if not req.prompt or not req.prompt.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Field 'prompt' is required.",
        )
    prompt = req.prompt.strip()
    # Per-model suffix variants (Q3.3b) and the enhancer's PromptSchema both need
    # the session's model, which isn't on this request -- unlike /generate's
    # req.model. One cheap lookup here beats duplicating submit_session_job's
    # liveness check.
    session_model = None
    if req.params.style_preset or req.params.subject_type or req.enhance_prompt != "off":
        session_model = await run_in_threadpool(
            image_session.get_session_model, user_id, req.session_id
        )
    init_b64 = await _resolve_init_image(req.init_image_b64, req.init_job_id, user_id)
    original_prompt = enhanced_prompt = extra_negative = None
    if session_model and req.enhance_prompt != "off":
        prompt, original_prompt, enhanced_prompt, extra_negative = await _apply_prompt_enhancement(
            prompt, session_model, req.enhance_prompt, init_b64, request, user_id
        )
    pre_suffix_prompt = prompt
    if session_model:
        if req.params.style_preset:
            prompt += get_preset_suffix(req.params.style_preset, session_model)
        if req.params.subject_type:
            prompt += get_subject_type_suffix(req.params.subject_type, session_model)
    original_prompt = _finalize_original_prompt(original_prompt, pre_suffix_prompt, prompt)
    params = req.params
    params_dict = params.model_dump()
    mutated = False
    if init_b64:
        params_dict["init_image_b64"] = init_b64
        if params_dict.get("strength") is None:
            params_dict["strength"] = 0.6
        mutated = True
    if extra_negative:
        existing_negative = params_dict.get("negative_prompt")
        params_dict["negative_prompt"] = (
            f"{existing_negative}, {extra_negative}" if existing_negative else extra_negative
        )
        mutated = True
    if mutated:
        params = image_session.ImageJobParams(**params_dict)
    job_id = await run_in_threadpool(
        image_session.submit_session_job, user_id, req.session_id, prompt, params,
        original_prompt, enhanced_prompt,
    )
    return {"job_id": job_id, "status": "queued"}


@router.post("/session/stop")
async def session_stop(req: SessionStopRequest, request: Request):
    user_id = request.state.user_id
    await run_in_threadpool(image_session.stop_session, user_id, req.session_id)
    return {"status": "ok"}


@router.post("/session/extend")
async def session_extend(req: SessionExtendRequest, request: Request):
    user_id = request.state.user_id
    return await run_in_threadpool(
        image_session.extend_session, user_id, req.session_id, req.add_minutes
    )


@router.get("/job/{job_id}")
async def get_job(job_id: str, request: Request):
    user_id = request.state.user_id
    job = await run_in_threadpool(image_session.get_job, user_id, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found."
        )
    return job


# --- G1: Generations tab management (delete, reorder) -----------------------


@router.delete("/job/{job_id}")
async def delete_job_route(job_id: str, request: Request):
    user_id = request.state.user_id
    ok = await run_in_threadpool(image_session.delete_job, user_id, job_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Job not found, not yours, or currently running.",
        )
    return {"status": "deleted"}


@router.post("/jobs/reorder")
async def reorder_jobs(req: ReorderQueueRequest, request: Request):
    user_id = request.state.user_id
    ok = await run_in_threadpool(
        image_session.reorder_queue, user_id, req.session_id, req.job_ids
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Queue changed since it was loaded -- refresh and try again.",
        )
    return {"status": "reordered"}
