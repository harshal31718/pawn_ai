"""C-series: capability-first model routing.

Covers rank_candidates' ordering and filters (C3), the task-type axis (C2), the
quality-rank tie band (C1), and ranked failover (C4).

Registry under test is the seeded fixture (app/registry/seed.py), whose shape is
documented in test_resolver.py. Relevant quality_ranks:

  balanced  gemini-2.5-flash 10 [google]
  balanced  gpt-oss-120b     20 [cerebras]
  balanced  llama-3.3-70b    20 [groq, huggingface]
  fast      gemini-2.5-flash-lite 20 [google]
  fast      glm-4.7          60 [cerebras]
  research  deepseek-r1      50 [github, huggingface, openrouter]

Only ACTIVE endpoints are listed. Notably qwen-3-32b is absent: its sole seed
endpoint (cerebras) has active=False, so it is never selectable and cannot be
used in these tests -- verified rather than assumed.

gpt-oss-120b and llama-3.3-70b share rank 20 ON PURPOSE: they are the only two
usable balanced models besides gemini, hence the only viable tie pair for the
live-tiebreak tests. Keyed to {cerebras, groq} they each expose exactly one
reachable endpoint, which makes their headroom easy to control.
"""
import pytest
from unittest.mock import patch

from app.constants import QUALITY_TIE_BAND, ROLE_TASK_TYPES, TASK_TYPE_TAGS, TASK_TYPES
from app.core.rate_limiter import EndpointRateLimiter
from app.exceptions import NoEndpointError
from app.registry.loader import load_registry
from app.resolver.resolver import Resolver


def _resolver():
    return Resolver(load_registry(), EndpointRateLimiter())


def _keys(*allowed):
    allowed_set = set(allowed)
    return patch(
        "app.core.key_store.get_key",
        side_effect=lambda user_id, provider: "KEY" if provider in allowed_set else None,
    )


# ── C3: ordering is quality-first ────────────────────────────────────────────

def test_rank_candidates_orders_by_quality_rank():
    r = _resolver()
    with _keys("google", "cerebras", "groq"):
        ranked = r.rank_candidates("balanced", user_id="u")
    assert ranked[0] == "gemini-2.5-flash"       # rank 10 beats both rank-20s
    assert set(ranked) == {"gemini-2.5-flash", "gpt-oss-120b", "llama-3.3-70b"}


def test_rank_candidates_returns_all_usable_not_just_one():
    """C3 returns a full ordered list -- that's what makes C4's ranked failover
    possible. The old API could only ever surface a single pick."""
    r = _resolver()
    with _keys("google", "cerebras", "groq"):
        assert len(r.rank_candidates("balanced", user_id="u")) == 3


def test_rank_candidates_excludes_models_without_a_usable_key():
    r = _resolver()
    with _keys("google"):
        ranked = r.rank_candidates("balanced", user_id="u")
    assert ranked == ["gemini-2.5-flash"]
    assert "gpt-oss-120b" not in ranked      # cerebras-only, no key


def test_pick_model_by_capability_is_the_top_of_rank_candidates():
    r = _resolver()
    with _keys("google", "cerebras", "groq"):
        assert r.pick_model_by_capability("balanced", user_id="u") == \
            r.rank_candidates("balanced", user_id="u")[0]


def test_no_candidates_raises_no_endpoint_error():
    r = _resolver()
    with _keys("nonexistent-provider"):
        with pytest.raises(NoEndpointError):
            r.pick_model_by_capability("balanced", user_id="u")


# ── C3: hard filters ─────────────────────────────────────────────────────────

def test_require_tools_excludes_non_tool_models():
    """deepseek-r1 has supports_tools=False in the seed registry (F-11: its
    HuggingFace endpoint leaks tool-call tokens as visible text instead of a
    structured tool_calls field), so it must be absent when tools are required
    and present when they aren't."""
    registry = load_registry()
    assert registry.get_model("deepseek-r1").supports_tools is False, "fixture assumption"

    r = _resolver()
    with _keys("github", "huggingface", "openrouter"):
        assert "deepseek-r1" in r.rank_candidates("research", user_id="u")
        assert "deepseek-r1" not in r.rank_candidates(
            "research", user_id="u", require_tools=True
        )


def test_require_vision_is_a_hard_filter_not_a_preference():
    """REGRESSION GUARD (Q3.1 bug class). Task-type became a soft *preference*
    in C2; require_vision must NOT follow it. Handing image content to a
    text-only model is a correctness bug, not a quality regression.

    No seed model sets supports_vision, so the correct behaviour is an EMPTY
    candidate list and a raised NoEndpointError -- emphatically not "fall back
    to the best text model". Asserting emptiness is what makes this meaningful:
    if require_vision ever degrades into a preference, this list becomes
    non-empty and the test fails.
    """
    registry = load_registry()
    assert not any(
        m.supports_vision for m in registry.user_models()
    ), "fixture assumption: no seed model is vision-capable"

    r = _resolver()
    with _keys("google", "cerebras", "groq"):
        assert r.rank_candidates("balanced", user_id="u", require_vision=True) == []
        assert r.rank_candidates("balanced", user_id="u") != []   # control
        with pytest.raises(NoEndpointError):
            r.pick_model_by_capability("balanced", user_id="u", require_vision=True)


def test_exclude_model_ids_removes_that_model():
    r = _resolver()
    with _keys("google", "cerebras", "groq"):
        ranked = r.rank_candidates(
            "balanced", user_id="u", exclude_model_ids={"gemini-2.5-flash"}
        )
    assert "gemini-2.5-flash" not in ranked
    assert len(ranked) >= 1


# ── C1/C3: the quality tie band + live tiebreak ──────────────────────────────

TIE_PAIR = ("gpt-oss-120b", "llama-3.3-70b")


def test_models_in_the_same_band_are_tied():
    """Both rank 20 -> same band, so live signals decide between them."""
    registry = load_registry()
    a = registry.get_model(TIE_PAIR[0]).quality_rank
    b = registry.get_model(TIE_PAIR[1]).quality_rank
    assert a // QUALITY_TIE_BAND == b // QUALITY_TIE_BAND


def test_headroom_breaks_ties_within_a_band():
    """The point of the tie band: between two equally-ranked models, the one
    with more quota left wins. Without a band, curated ranks would form a total
    order and this signal could never fire at all.
    """
    r = _resolver()
    with _keys("cerebras", "groq"):
        baseline = [m for m in r.rank_candidates("balanced", user_id="u") if m in TIE_PAIR]
        assert baseline == ["gpt-oss-120b", "llama-3.3-70b"], "deterministic default order"

        # Burn the leader's reachable endpoint JUST enough to create a headroom
        # gap, without tripping can_use()'s own 90%-of-rpm_limit cutoff (30 rpm
        # here -> 27) -- overshooting that would make _has_usable_endpoint drop
        # gpt-oss-120b from the ranking ENTIRELY (its only reachable endpoint
        # under these keys), which fails this test for a different reason than
        # intended (missing from `after` rather than merely reordered). 25 of 30
        # clears 0.0 vs 0.83 headroom, comfortably enough to flip the tie while
        # staying under the disqualifying threshold. user_id="u" is required --
        # R2 keys the rate limiter per-user, and rank_candidates above reads
        # user "u"'s bucket; omitting it burns the SHARED_USER bucket instead,
        # which the ranking call never looks at, silently no-op'ing this test.
        # (Both of these were only caught once real pytest actually ran this
        # session -- a standalone re-implementation had missed them.)
        for _ in range(25):
            r._rate_limiter.record_call("ep-gpt-oss-120b-cerebras", user_id="u")

        after = [m for m in r.rank_candidates("balanced", user_id="u") if m in TIE_PAIR]
    assert after == ["llama-3.3-70b", "gpt-oss-120b"], "headroom must break the tie"


def test_quality_beats_headroom_across_bands():
    """Quality-FIRST: an exhausted top-ranked model still outranks a healthy
    model from a worse band. Headroom only ever reorders within a band."""
    r = _resolver()
    with _keys("google", "cerebras", "groq"):
        for _ in range(200):
            r._rate_limiter.record_call("ep-gemini-2.5-flash-google")
        ranked = r.rank_candidates("balanced", user_id="u")
    assert ranked[0] == "gemini-2.5-flash"


def test_ordering_is_deterministic_with_no_usage_recorded():
    r = _resolver()
    with _keys("google", "cerebras", "groq"):
        assert r.rank_candidates("balanced", user_id="u") == \
            r.rank_candidates("balanced", user_id="u")


# ── C2: the task-type axis ───────────────────────────────────────────────────

def test_task_type_prefers_tagged_models():
    """gemini-2.5-flash carries 'coding'; qwen-3-32b (seed) does not."""
    r = _resolver()
    with _keys("google", "cerebras", "groq"):
        ranked = r.rank_candidates("balanced", user_id="u", task_type="coding")
    registry = load_registry()
    tagged = [m for m in ranked if "coding" in registry.get_model(m).capability_tags]
    untagged = [m for m in ranked if "coding" not in registry.get_model(m).capability_tags]
    if tagged and untagged:
        assert ranked.index(tagged[0]) < ranked.index(untagged[0])


def test_task_type_is_a_preference_not_a_filter():
    """No model at this level carries the tag -> selection must degrade to
    level-only ordering, NOT return an empty list."""
    r = _resolver()
    with _keys("google", "cerebras", "groq"):
        with_tag = r.rank_candidates("balanced", user_id="u", task_type="vision")
        without = r.rank_candidates("balanced", user_id="u")
    assert set(with_tag) == set(without), "no candidate may be dropped by task_type"


def test_unknown_task_type_degrades_gracefully():
    r = _resolver()
    with _keys("google", "cerebras", "groq"):
        assert r.rank_candidates("balanced", user_id="u", task_type="not-a-real-type") == \
            r.rank_candidates("balanced", user_id="u")


# ── C2: constants are coherent ───────────────────────────────────────────────

def test_every_task_type_has_a_tag_mapping():
    for t in TASK_TYPES:
        assert t in TASK_TYPE_TAGS and TASK_TYPE_TAGS[t]


def test_every_role_task_type_is_a_valid_task_type():
    for role, t in ROLE_TASK_TYPES.items():
        assert t in TASK_TYPES, f"{role} declares unknown task type {t!r}"


def test_role_task_types_covers_every_role_level():
    """ROLE_TASK_TYPES is parallel to ROLE_LEVELS; a role in one but not the
    other silently falls back to 'general', which is easy to miss."""
    from app.constants import ROLE_LEVELS
    assert set(ROLE_TASK_TYPES) == set(ROLE_LEVELS)


# ── C4: ranked failover ──────────────────────────────────────────────────────

def test_fallback_models_preserves_requested_first_and_dedupes():
    r = _resolver()
    with _keys("google", "cerebras", "groq"):
        fb = r.fallback_models("llama-3.3-70b", user_id="u")
    assert fb[0] == "llama-3.3-70b"
    assert len(fb) == len(set(fb))


def test_fallback_models_tail_is_quality_ordered():
    """The whole point of C4: after the requested model, failover walks a ranked
    list rather than registry file order."""
    r = _resolver()
    with _keys("google", "cerebras", "groq"):
        fb = r.fallback_models("llama-3.3-70b", user_id="u")
    same_level = [m for m in fb[1:] if m in ("gemini-2.5-flash", "gpt-oss-120b")]
    assert same_level[0] == "gemini-2.5-flash", "best same-level model must come first"


def test_fallback_models_same_level_before_other_levels():
    r = _resolver()
    with _keys("google", "cerebras", "groq"):
        fb = r.fallback_models("gemini-2.5-flash", user_id="u")   # balanced
    assert fb.index("gpt-oss-120b") < fb.index("gemini-2.5-flash-lite")


def test_fallback_models_excludes_unkeyed_models():
    r = _resolver()
    with _keys("google"):
        fb = r.fallback_models("gemini-2.5-flash", user_id="u")
    assert "gpt-oss-120b" not in fb and "glm-4.7" not in fb
