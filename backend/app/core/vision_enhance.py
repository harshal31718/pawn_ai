"""Q3.1 (imageLab): vision-grounded prompt enhancement.

`enhance_with_vision` sends the user's raw prompt (and, for img2img, the
reference image) to a vision-capable model that rewrites it into the target
generation model's preferred prompt shape (see `image_models.PromptSchema`).
Provider chain: Groq (preferred by the resolver's existing F-6 sort when the
user holds a Groq key) -> Gemini (any other vision-capable model) on failure
-> the raw prompt unchanged if both fail. Never raises -- generation must
never block on this step (plan_vision_prompt_enhancement.md §3.2).
"""
from typing import Optional, TypedDict

from app.constants import ENHANCE_SKIP_WORD_THRESHOLD, ROLE_LEVELS
from app.core import normalize
from app.core.image_models import PromptSchema
from app.core.rate_limiter import EndpointRateLimiter
from app.exceptions import NoEndpointError, ProviderError
from app.resolver.resolver import Resolver

# Camera/lens/lighting/DOF/texture vocabulary -- a prompt already containing
# these is "already scaffolded" and doesn't need an enhancer pass (§3.1.4).
_SCAFFOLD_KEYWORDS = (
    "mm lens", "f/", "bokeh", "depth of field", "lighting", "golden hour",
    "backlit", "rim light", "film grain", "shot on", "camera", "lens",
    "composition", "aperture", "focal length",
)


class EnhanceResult(TypedDict):
    prompt: str
    negative: Optional[str]
    used_model: Optional[str]
    degraded: bool


def _looks_already_scaffolded(prompt: str) -> bool:
    """True if the raw prompt already reads like a scaffolded/detailed prompt
    (camera/lighting/DOF vocabulary present) -- a rewrite would add little."""
    lowered = prompt.lower()
    return any(keyword in lowered for keyword in _SCAFFOLD_KEYWORDS)


def needs_enhancement(prompt: str) -> bool:
    """Rule-based gate (§3.1.4): short/vague prompts get enhanced; long or
    already-scaffolded prompts are used as-is. This is the free, ~instant
    default tier -- the LLM call in `enhance_with_vision` is the "extra" tier,
    only reached when this says so (or the user forces `Always`)."""
    word_count = len(prompt.split())
    if word_count >= ENHANCE_SKIP_WORD_THRESHOLD and _looks_already_scaffolded(prompt):
        return False
    return True


def _build_messages(prompt: str, image_b64: Optional[str], system_prompt: str) -> list[dict]:
    user_content: object
    if image_b64:
        user_content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
        ]
    else:
        user_content = prompt
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


# Case-insensitive, earliest-match: the system prompt asks for a "Negative:"
# line, but live models don't always use that exact wording (e.g. "Avoid:" was
# observed live 2026-07-17) -- matching only the exact-case literal left the
# negative text stuck inside the positive prompt sent to the generation model
# instead of being split into its own field.
_NEGATIVE_MARKERS = ("negative prompt:", "negative:", "avoid:")


def _parse_enhancer_output(raw_text: str, wants_negative: bool) -> tuple[str, Optional[str]]:
    """The enhancer is instructed to output only the rewritten prompt (plus,
    for wants_negative models, a negative-prompt list). Split on the earliest
    negative-list marker if present; otherwise the whole output is the
    positive prompt and there's no negative."""
    text = raw_text.strip()
    if not wants_negative:
        return text, None
    lowered = text.lower()
    earliest: Optional[tuple[int, str]] = None
    for marker in _NEGATIVE_MARKERS:
        idx = lowered.find(marker)
        if idx != -1 and (earliest is None or idx < earliest[0]):
            earliest = (idx, marker)
    if earliest is None:
        return text, None
    idx, marker = earliest
    positive = text[:idx].strip().rstrip(",")
    negative = text[idx + len(marker):].strip()
    return positive, negative


async def enhance_with_vision(
    prompt: str,
    image_b64: Optional[str],
    target_model_schema: PromptSchema,
    resolver: Resolver,
    rate_limiter: EndpointRateLimiter,
    user_id: Optional[str] = None,
) -> EnhanceResult:
    """Tries a vision-capable model (Groq first, then Gemini) to rewrite
    `prompt` into `target_model_schema`'s shape. Falls back to the raw prompt,
    unchanged, if no vision model is available or every attempt errors --
    this function never raises."""
    tried: set[str] = set()
    for _ in range(2):  # one attempt per chain step: Groq, then Gemini -- see module docstring
        try:
            model_id = resolver.pick_model_by_capability(
                ROLE_LEVELS["vision_enhancer_primary"],
                user_id=user_id,
                require_vision=True,
                exclude_model_ids=tried,
            )
        except NoEndpointError:
            break
        tried.add(model_id)

        messages = _build_messages(prompt, image_b64, target_model_schema.system_prompt)
        try:
            # chat_complete_single_model, not chat_complete -- the latter's
            # cross-model fallback_models() fallback isn't vision-filtered and
            # would silently hand the image content to a non-vision model at
            # the same capability level. See normalize.py's docstring.
            result = await normalize.chat_complete_single_model(
                model_id=model_id,
                messages=messages,
                resolver=resolver,
                rate_limiter=rate_limiter,
                user_id=user_id,
            )
        except (ProviderError, NoEndpointError):
            continue

        content = result.get("content")
        if not content or not isinstance(content, str):
            continue

        positive, negative = _parse_enhancer_output(content, target_model_schema.wants_negative)
        if not positive:
            continue
        return {"prompt": positive, "negative": negative, "used_model": model_id, "degraded": False}

    return {"prompt": prompt, "negative": None, "used_model": None, "degraded": True}
