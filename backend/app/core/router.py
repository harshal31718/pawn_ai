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

from app.constants import (
    ROLE_LEVELS,
    ROLE_TASK_TYPES,
    ROUTER_HEAVY_CHAR_THRESHOLD,
    ROUTER_LIGHT_CHAR_THRESHOLD,
)
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
# Found live (2026-07-16): a short, casually-phrased memory-recall request
# ("search the memory of project, i asked you to remember X in another
# chat") is heuristically "light" (under ROUTER_LIGHT_CHAR_THRESHOLD, no
# heavy keyword) -> needs_agent=False -> direct_answer_node, which has ZERO
# tools bound. search_memory/doc_search are only ever reachable through the
# agent loop, so a message like this could never actually search memory no
# matter how it was phrased -- the model correctly (and unhelpfully)
# reported it had no such access. Unlike _IMAGE_GEN_KEYWORDS this needs no
# has_*_creds gate: search_memory/doc_search are bound whenever the chat has
# a scope at all (registry.py's `ctx.scope_type is not None`), which is true
# for every real chat.
_MEMORY_RECALL_KEYWORDS = [
    "search the memory", "search memory", "search your memory",
    "remember", "recall", "you told me", "i told you",
    "we discussed", "we talked about", "mentioned before",
    "earlier chat", "previous chat", "other chat", "another chat",
    "last time", "what did i say", "what did i tell you",
]
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


# C2: task-type inference keywords. Purely heuristic and deliberately cheap --
# task_type is a selection PREFERENCE, not a hard filter, so a miss costs a
# slightly worse model pick, never a failure. That asymmetry is why this doesn't
# get its own LLM tier: it isn't worth a round-trip.
# Order matters in _infer_task_type: earlier entries win ties.
_CODING_KEYWORDS = [
    "code", "function", "bug", "debug", "refactor", "compile", "stack trace",
    "traceback", "exception", "syntax", "api", "regex", "sql", "query",
    "python", "javascript", "typescript", "rust", "golang", "java", "c++",
    "class", "method", "variable", "import", "npm", "pip", "git",
]
_REASONING_KEYWORDS = [
    "prove", "derive", "solve", "calculate", "analyze", "compare", "evaluate",
    "why", "explain why", "reason", "logic", "math", "equation", "theorem",
    "step by step", "trade-off", "tradeoff", "pros and cons",
]
_SUMMARIZATION_KEYWORDS = [
    "summarize", "summarise", "summary", "tldr", "tl;dr", "recap",
    "key points", "in short", "condense", "abstract",
]


class RouteDecision(TypedDict):
    difficulty: str  # "light" | "heavy"
    needs_agent: bool
    task_type: str  # one of constants.TASK_TYPES


def _infer_task_type(text: str, has_image: bool = False) -> str:
    """Infer the task type from user text. Heuristic-only by design (see the
    keyword-list comment above).

    A fenced code block is treated as a strong coding signal on its own -- it's
    far more reliable than any keyword, since prose about code rarely fences it.
    """
    if has_image:
        return "vision"
    if "```" in text or _matches_any_keyword(text, _CODING_KEYWORDS):
        return "coding"
    if _matches_any_keyword(text, _SUMMARIZATION_KEYWORDS):
        return "summarization"
    if _matches_any_keyword(text, _REASONING_KEYWORDS):
        return "reasoning"
    return "general"


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
        or _matches_any_keyword(text, _MEMORY_RECALL_KEYWORDS)
    )


def _heuristic_classify(
    text: str, has_doc: bool, has_tools_likely: bool, has_search_key: bool, has_kaggle_creds: bool = False,
    task_type: str = "general",
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

    return {
        "difficulty": difficulty,
        "needs_agent": _needs_agent(difficulty, text, has_search_key, has_kaggle_creds),
        "task_type": task_type,
    }


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
    task_type: str = "general",
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
        return {"difficulty": "heavy", "needs_agent": True, "task_type": task_type}

    return {
        "difficulty": difficulty,
        "needs_agent": _needs_agent(difficulty, text, has_search_key, has_kaggle_creds),
        "task_type": task_type,
    }


async def classify(
    messages: List[Dict[str, Any]],
    has_doc: bool,
    has_tools_likely: bool,
    resolver: Optional[Resolver] = None,
    rate_limiter: Optional[EndpointRateLimiter] = None,
    user_id: Optional[str] = None,
    has_search_key: bool = False,
    has_kaggle_creds: bool = False,
    has_image: bool = False,
) -> RouteDecision:
    """Classify a message's difficulty ('light'/'heavy'), whether it needs
    the full agent, and (C2) its task type. `has_doc` (a doc is attached) and
    `has_tools_likely` (the previous assistant turn used tools) are precomputed
    by the caller, same as `has_search_key` (the user has a Tavily/Brave key
    configured) and `has_kaggle_creds` (F-11: the user can actually use
    generate_image). `has_image` (C2) forces task_type='vision'.

    `resolver`/`rate_limiter` are only needed for the LLM fallback tier; if
    omitted (or the heuristic tier already decided), no model call is made.
    When the fallback tier would be needed but no resolver is available, this
    fails toward capability (heavy/needs_agent=True) rather than guessing.

    task_type is computed ONCE here and threaded into whichever tier decides,
    rather than at each of the four RouteDecision construction sites -- it
    depends only on the user text, so recomputing it per tier would risk the
    tiers disagreeing for no benefit.
    """
    text = _total_user_text(messages)
    task_type = _infer_task_type(text, has_image=has_image)

    decision = _heuristic_classify(
        text, has_doc, has_tools_likely, has_search_key, has_kaggle_creds, task_type
    )
    if decision is not None:
        return decision

    if resolver is None or rate_limiter is None:
        return {"difficulty": "heavy", "needs_agent": True, "task_type": task_type}

    return await _llm_fallback_classify(
        text, resolver, rate_limiter, user_id, has_search_key, has_kaggle_creds, task_type
    )


def resolve_final_model(
    difficulty: str,
    user_model_id: Optional[str],
    resolver: Resolver,
    user_id: Optional[str] = None,
    task_type: Optional[str] = None,
) -> str:
    """Resolves which model serves the FINAL user-facing answer. The user's
    explicit model pick (ModelSwitcher) always wins here, regardless of
    difficulty -- the router only governs internal (orchestrator/subagent/
    summarizer) calls. Falls back to ROLE_LEVELS['final_light'/'final_heavy']
    resolved through the capability resolver when no explicit pick was made.
    """
    if user_model_id:
        return user_model_id
    role = "final_heavy" if difficulty == "heavy" else "final_light"
    level = ROLE_LEVELS[role]
    # C2/C3: prefer the caller's inferred task type; fall back to the role's own
    # declared type. A role's declaration is the better default when no text was
    # classified (e.g. the mode_hint short-circuits), and the inferred type is
    # the better signal when there was.
    effective_task_type = task_type or ROLE_TASK_TYPES.get(role)
    return resolver.pick_model_by_capability(
        level, user_id=user_id, task_type=effective_task_type
    )
