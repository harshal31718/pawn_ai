from starlette.concurrency import run_in_threadpool

from app.core import image_session
from app.core.image_models import DEFAULT_IMAGE_MODEL, IMAGE_MODELS
from app.exceptions import ProviderError

from .base import ToolContext, ToolSpec

GENERATE_IMAGE_PARAMETERS = {
    "type": "object",
    "properties": {
        "prompt": {"type": "string", "description": "What to generate, in plain English."},
        "model": {
            "type": "string",
            "description": f"Which image model to use. One of: {', '.join(IMAGE_MODELS)}.",
            "enum": list(IMAGE_MODELS),
        },
    },
    "required": ["prompt"],
}


async def _generate_image_handler(args: dict, ctx: ToolContext) -> str:
    prompt = (args.get("prompt") or "").strip()
    if not prompt:
        return "TOOL_ERROR: no prompt provided"
    model = args.get("model") or DEFAULT_IMAGE_MODEL
    if model not in IMAGE_MODELS:
        return f"TOOL_ERROR: unknown image model '{model}'. Available: {', '.join(IMAGE_MODELS)}."

    try:
        # Warm session first (matches the Lab's own routing in routes/generate.py):
        # a live session serves in seconds, so it's always preferred over a cold
        # one-shot run when one is already up for this model.
        status = await run_in_threadpool(image_session.get_session_status, ctx.user_id, model)
        if status.get("alive") and status.get("session_id"):
            job_id = await run_in_threadpool(
                image_session.submit_session_job, ctx.user_id, status["session_id"], prompt, None
            )
        else:
            job_id, created = await run_in_threadpool(
                image_session.create_cold_job, ctx.user_id, model, prompt, None
            )
            if created:
                # Shared with routes/generate.py's own cold-job spawn -- same
                # lock/task registry regardless of entry point, so a cold run
                # triggered from chat and one triggered from Image Lab for the
                # same (user, model) can never race the same kernel slug.
                image_session.spawn_cold_job_bg(ctx.user_id, model, job_id)
    except ProviderError as e:
        return f"TOOL_ERROR: {e.message}"
    except RuntimeError as e:
        # create_cold_job raises this if a warm session started between the status
        # check above and the create call -- rare race, safe to surface as a retry hint.
        return f"TOOL_ERROR: {e}"

    return f"Image generation started (job_id={job_id}). It will appear inline once ready."


GENERATE_IMAGE_TOOL = ToolSpec(
    name="generate_image",
    description=(
        "Generates an image from a text prompt using Image Lab's Kaggle pipeline. "
        "Returns immediately with a job id -- the image renders inline once ready, "
        "it does not block this turn."
    ),
    parameters=GENERATE_IMAGE_PARAMETERS,
    handler=_generate_image_handler,
)
