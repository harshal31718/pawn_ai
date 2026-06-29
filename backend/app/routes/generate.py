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


class GenerateRequest(BaseModel):
    modality: str = "image"
    input: int | None = None
    prompt: str | None = None
    model: str = DEFAULT_IMAGE_MODEL


class ConnectRequest(BaseModel):
    model: str = DEFAULT_IMAGE_MODEL


class SessionStartRequest(BaseModel):
    model: str = DEFAULT_IMAGE_MODEL
    duration_minutes: int = 60
    max_images: int | None = None


class SessionJobRequest(BaseModel):
    session_id: str
    prompt: str


class SessionStopRequest(BaseModel):
    session_id: str


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
        # Unknown model id is validated inside generate_image → UnknownModelError (400).
        async with _lock_for(f"{user_id}:{req.model}"):
            return await run_in_threadpool(
                generate.generate_image, user_id, req.prompt.strip(), req.model
            )

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Modality '{req.modality}' is not supported yet.",
        )


# --- Warm sessions + durable jobs (Phase W) ---------------------------------
# W.0 proves the persistent Kaggle loop + Supabase rendezvous with a CPU echo
# kernel. Supabase work is blocking → off-loaded to the threadpool.


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
    job_id = await run_in_threadpool(
        image_session.submit_session_job, user_id, req.session_id, req.prompt.strip()
    )
    return {"job_id": job_id, "status": "queued"}


@router.post("/session/stop")
async def session_stop(req: SessionStopRequest, request: Request):
    user_id = request.state.user_id
    await run_in_threadpool(image_session.stop_session, user_id, req.session_id)
    return {"status": "ok"}


@router.get("/job/{job_id}")
async def get_job(job_id: str, request: Request):
    user_id = request.state.user_id
    job = await run_in_threadpool(image_session.get_job, user_id, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found."
        )
    return job
