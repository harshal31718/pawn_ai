"""Kaggle-backed generation route.

POST /generate — body {modality, input?, prompt?}. Today only modality="cube"
(Milestone A.0, proves the Kaggle round-trip); "image" arrives once the cube
path is green.

The Kaggle call runs in run_in_threadpool (it blocks for minutes). A per-user
lock serialises a single user's runs — one kernel slug is single-writer, so two
concurrent runs would clobber the same kernel version. Different users run in
parallel.
"""

import asyncio

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.core import generate

router = APIRouter(prefix="/generate", tags=["generate"])

_user_locks: dict[str, asyncio.Lock] = {}


def _lock_for(user_id: str) -> asyncio.Lock:
    lock = _user_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _user_locks[user_id] = lock
    return lock


class GenerateRequest(BaseModel):
    modality: str = "image"
    input: int | None = None
    prompt: str | None = None


@router.post("")
async def generate_artifact(req: GenerateRequest, request: Request):
    user_id = request.state.user_id

    if req.modality != "cube":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Modality '{req.modality}' is not supported yet.",
        )
    if req.input is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Field 'input' is required for the cube modality.",
        )

    async with _lock_for(user_id):
        # NotConfiguredError / KaggleError propagate to their exception handlers.
        return await run_in_threadpool(generate.generate_cube, user_id, req.input)
