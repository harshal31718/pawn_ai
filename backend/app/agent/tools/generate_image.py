from starlette.concurrency import run_in_threadpool

from app.core import image_session
from app.exceptions import ProviderError

from .base import ToolContext, ToolSpec

# F-11: chat-triggered generation always uses SDXL and always goes through a
# warm session (never a cold one-shot) -- the LLM no longer picks the model.
# This closes a live bug: giving the model a "model" enum choice let it
# sometimes pick "flux" or malform the call entirely (a fallback model even
# emitted a broken textual tool-call once). One fixed, well-tested path only.
GENERATE_IMAGE_MODEL = "sdxl"
GENERATE_IMAGE_SESSION_MINUTES = 30

GENERATE_IMAGE_PARAMETERS = {
    "type": "object",
    "properties": {
        "prompt": {"type": "string", "description": "What to generate, in plain English."},
    },
    "required": ["prompt"],
}


async def _generate_image_handler(args: dict, ctx: ToolContext) -> str:
    prompt = (args.get("prompt") or "").strip()
    if not prompt:
        return "TOOL_ERROR: no prompt provided"

    try:
        # Reuse a live session if one's already up for sdxl (started from
        # here or from Image Lab directly -- same (user_id, model) row
        # either way, see core/image_session.py's start_session). Otherwise
        # start a fresh 30-minute warm session and queue onto it immediately
        # -- submit_session_job already queues correctly while a session is
        # still starting/installing/loading_model, so no separate wait step
        # is needed here.
        status = await run_in_threadpool(image_session.get_session_status, ctx.user_id, GENERATE_IMAGE_MODEL)
        if status.get("alive") and status.get("session_id"):
            session_id = status["session_id"]
            started_new = False
        else:
            session = await run_in_threadpool(
                image_session.start_session,
                ctx.user_id,
                GENERATE_IMAGE_MODEL,
                GENERATE_IMAGE_SESSION_MINUTES,
                None,  # max_images: uncapped, rely on the session timer alone to bound cost
            )
            session_id = session["session_id"]
            started_new = True

        job_id = await run_in_threadpool(
            image_session.submit_session_job, ctx.user_id, session_id, prompt, None
        )
    except ProviderError as e:
        return f"TOOL_ERROR: {e.message}"

    if started_new:
        return (
            f"Started a {GENERATE_IMAGE_SESSION_MINUTES}-minute SDXL image session and queued "
            f"your image (job_id={job_id}). It will appear inline once ready."
        )
    return f"Queued your image on the running SDXL session (job_id={job_id}). It will appear inline once ready."


GENERATE_IMAGE_TOOL = ToolSpec(
    name="generate_image",
    description=(
        "Generates an image from a text prompt using Image Lab's SDXL pipeline. "
        "Starts (or reuses) a 30-minute warm session -- the same session Image Lab "
        "shows, so a session started from either place can be continued from the "
        "other. Returns immediately with a job id; the image renders inline once "
        "ready, it does not block this turn."
    ),
    parameters=GENERATE_IMAGE_PARAMETERS,
    handler=_generate_image_handler,
)
