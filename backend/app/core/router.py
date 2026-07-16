"""Model router (Phase A / A.5) — classifies a message's difficulty and
whether it needs the full agent, so most traffic can take the direct-answer
fast path (A.6) instead of paying for orchestration.

Self-contained this session: no dependency on agent/graph.py — A.6 wires
this in. The heuristic tier is pure/synchronous; the LLM fallback tier is
async (needs one chat_complete call) and only runs when the heuristic tier
can't decide.
"""

import re
import sys
from typing import Any, Dict, List, Optional, TypedDict

from app.constants import ROLE_LEVELS, ROUTER_HEAVY_CHAR_THRESHOLD, ROUTER_LIGHT_CHAR_THRESHOLD
from app.core.normalize import chat_complete
from app.core.rate_limiter import EndpointRateLimiter
from app.resolver.resolver import Resolver

_HEAVY_KEYWORDS = ["plan", "analyze", "debug", "prove", "compare", "research", "step by step", "why"]
_TIME_SENSITIVE_KEYWORDS = ["latest", "today", "current", "news", "price", "202"]
# F-11: without this, "generate an image of X" (short, no URL, no heavy
# keyword) heuristically classifies light+needs_agent=False -- the
# direct_answer fast path has NO tools bound at all, so generate_image can
# never actually be invoked no matter how the model would otherwise respond.
# Gated on has_kaggle_creds (mirrors _TIME_SENSITIVE_KEYWORDS's has_search_key
# gate) so this only forces agent routing when the tool would really be
# available.
_IMAGE_GEN_KEYWORDS = [
    "generate an image", "generate image", "generate a picture", "generate a photo",
    "create an image", "create a picture", "make an image", "make a picture",
    "draw a picture", "draw me", "image of", "picture of",
]
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


class RouteDecision(TypedDict):
    difficulty: str  # "light" | "heavy"
    needs_agent: bool


def _total_user_text(messages: List[Dict[str, Any]]) -> str:
    return "\n".join(m.get("content") or "" for m in messages if m.get("role") == "user")


def _matches_any_keyword(text: str, keywords: List[str]) -> bool:
    return any(re.search(r"\b" + re.escape(kw) + r"\b", text, re.IGNORECASE) for kw in keywords)


def _has_url(text: str) -> bool:
    return _URL_RE.search(text) is not None


def _needs_agent(difficulty: str, text: str, has_search_key: bool, has_kaggle_creds: bool = False) -> bool:
    return (
        difficulty == "heavy"
        or _has_url(text)
        or (has_search_key and _matches_any_keyword(text, _TIME_SENSITIVE_KEYWORDS))
        or (has_kaggle_creds and _matches_any_keyword(text, _IMAGE_GEN_KEYWORDS))
    )


def _heuristic_classify(
    text: str, has_doc: bool, has_tools_likely: bool, has_search_key: bool, has_kaggle_creds: bool = False
) -> Optional[RouteDecision]:
    """Returns a RouteDecision if the rule tier can decide, else None (defer
    to the LLM fallback tier)."""
    is_heavy = (
        len(text) > ROUTER_HEAVY_CHAR_THRESHOLD
        or "```" in text
        or _matches_any_keyword(text, _HEAVY_KEYWORDS)
        or has_doc
        or has_tools_likely
    )
    if is_heavy:
        difficulty = "heavy"
    elif len(text) < ROUTER_LIGHT_CHAR_THRESHOLD:
        difficulty = "light"
    else:
        return None  # ambiguous band — defer to the LLM fallback tier

    return {"difficulty": difficulty, "needs_agent": _needs_agent(difficulty, text, has_search_key, has_kaggle_creds)}


_CLASSIFY_SYSTEM_PROMPT = (
    "Classify the difficulty of the following user message as either 'light' "
    "(a simple, quick question a model can answer directly) or 'heavy' "
    "(requires research, multi-step reasoning, or careful analysis). "
    "Respond with exactly one word: light or heavy."
)


async def _llm_fallback_classify(
    text: str,
    resolver: Resolver,
    rate_limiter: EndpointRateLimiter,
    user_id: Optional[str],
    has_search_key: bool,
    has_kaggle_creds: bool = False,
) -> RouteDecision:
    """One chat_complete call on the 'fast' capability level. ANY failure
    (no available model, upstream error, unparseable response) defaults to
    heavy/needs_agent=True — fail toward capability, not away."""
    try:
        # user_id matters here: post-BYOK there are no shared keys, so picking
        # without it can select a model the user holds no key for and waste a
        # failover hop inside chat_complete (rescued, but suboptimal).
        model_id = resolver.pick_model_by_capability(ROLE_LEVELS["orchestrator"], user_id=user_id)
        result = await chat_complete(
            model_id,
            [
                {"role": "system", "content": _CLASSIFY_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            resolver,
            rate_limiter,
            user_id=user_id,
        )
        content = (result.get("content") or "").strip().lower()
        if "light" in content and "heavy" not in content:
            difficulty = "light"
        elif "heavy" in content:
            difficulty = "heavy"
        else:
            raise ValueError(f"unparseable classification response: {content!r}")
    except Exception as e:
        print(f"Router LLM fallback tier failed, defaulting to heavy: {e}", file=sys.stderr)
        return {"difficulty": "heavy", "needs_agent": True}

    return {"difficulty": difficulty, "needs_agent": _needs_agent(difficulty, text, has_search_key, has_kaggle_creds)}


async def classify(
    messages: List[Dict[str, Any]],
    has_doc: bool,
    has_tools_likely: bool,
    resolver: Optional[Resolver] = None,
    rate_limiter: Optional[EndpointRateLimiter] = None,
    user_id: Optional[str] = None,
    has_search_key: bool = False,
    has_kaggle_creds: bool = False,
) -> RouteDecision:
    """Classify a message's difficulty ('light'/'heavy') and whether it needs
    the full agent. `has_doc` (a doc is attached) and `has_tools_likely` (the
    previous assistant turn used tools) are precomputed by the caller, same
    as `has_search_key` (the user has a Tavily/Brave key configured) and
    `has_kaggle_creds` (F-11: the user can actually use generate_image).

    `resolver`/`rate_limiter` are only needed for the LLM fallback tier; if
    omitted (or the heuristic tier already decided), no model call is made.
    When the fallback tier would be needed but no resolver is available, this
    fails toward capability (heavy/needs_agent=True) rather than guessing.
    """
    text = _total_user_text(messages)

    decision = _heuristic_classify(text, has_doc, has_tools_likely, has_search_key, has_kaggle_creds)
    if decision is not None:
        return decision

    if resolver is None or rate_limiter is None:
        return {"difficulty": "heavy", "needs_agent": True}

    return await _llm_fallback_classify(text, resolver, rate_limiter, user_id, has_search_key, has_kaggle_creds)


def resolve_final_model(
    difficulty: str,
    user_model_id: Optional[str],
    resolver: Resolver,
    user_id: Optional[str] = None,
) -> str:
    """Resolves which model serves the FINAL user-facing answer. The user's
    explicit model pick (ModelSwitcher) always wins here, regardless of
    difficulty -- the router only governs internal (orchestrator/subagent/
    summarizer) calls. Falls back to ROLE_LEVELS['final_light'/'final_heavy']
    resolved through the capability resolver when no explicit pick was made.
    """
    if user_model_id:
        return user_model_id
    level = ROLE_LEVELS["final_heavy"] if difficulty == "heavy" else ROLE_LEVELS["final_light"]
    return resolver.pick_model_by_capability(level, user_id=user_id)
