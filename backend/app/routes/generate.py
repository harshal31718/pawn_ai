"""Kaggle-backed generation route.

POST /generate — body {modality, input?, prompt?}.
POST /generate/connect — verify connection and push the notebook.

The Kaggle call runs in run_in_threadpool (it blocks for minutes). A per-user
lock serialises a single user's runs — one kernel slug is single-writer, so two
concurrent runs would clobber the same kernel version. Different users run in
parallel.
"""

import asyncio

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.core import generate, image_session
from app.core.image_models import DEFAULT_IMAGE_MODEL
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


STYLE_SUFFIXES: dict[str, str] = {
    "photorealistic": ", RAW photo, 8K, ultra detailed, photorealistic, DSLR",
    "cinematic": ", cinematic shot, anamorphic lens, dramatic lighting, film grain",
    "anime": ", anime style, studio ghibli, detailed illustration, vibrant colors",
    "oil_painting": ", oil painting, impressionist, thick brushstrokes, canvas texture",
    "sketch": ", pencil sketch, charcoal drawing, black and white, cross-hatching",
}


class GenerateRequest(BaseModel):
    modality: str = "image"
    input: int | None = None
    prompt: str | None = None
    model: str = DEFAULT_IMAGE_MODEL
    params: ImageJobParams = ImageJobParams()
    init_image_b64: str | None = None   # direct base64 upload
    init_job_id: str | None = None      # refine an existing done job


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


class SessionStopRequest(BaseModel):
    session_id: str


class SessionExtendRequest(BaseModel):
    session_id: str
    add_minutes: int = 30


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
        if req.params.style_preset:
            prompt += STYLE_SUFFIXES.get(req.params.style_preset, "")
        init_b64 = await _resolve_init_image(req.init_image_b64, req.init_job_id, user_id)
        params = req.params
        if init_b64:
            params_dict = params.model_dump()
            params_dict["init_image_b64"] = init_b64
            if params_dict.get("strength") is None:
                params_dict["strength"] = 0.6
            params = image_session.ImageJobParams(**params_dict)
        # Non-blocking: create a durable job row (de-duped per user+model) and run
        # the slow Kaggle round-trip as a fire-and-forget background task, returning
        # the job id immediately. Unknown model → UnknownModelError (400) here.
        # RuntimeError → 400: raised when a live warm session already exists for this
        # model (cold job would waste a GPU slot alongside the running warm kernel).
        try:
            job_id, created = await run_in_threadpool(
                image_session.create_cold_job, user_id, req.model, prompt, params
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
    if req.params.style_preset:
        prompt += STYLE_SUFFIXES.get(req.params.style_preset, "")
    init_b64 = await _resolve_init_image(req.init_image_b64, req.init_job_id, user_id)
    params = req.params
    if init_b64:
        params_dict = params.model_dump()
        params_dict["init_image_b64"] = init_b64
        params_dict.setdefault("strength", 0.6)
        params = image_session.ImageJobParams(**params_dict)
    job_id = await run_in_threadpool(
        image_session.submit_session_job, user_id, req.session_id, prompt, params
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
