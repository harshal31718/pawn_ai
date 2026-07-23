from typing import List, Optional, Tuple, Dict
from app.exceptions import NoEndpointError
from app.registry.loader import Registry
from app.registry.schemas import ModelEntry
from app.core.rate_limiter import EndpointRateLimiter
from app.core.llm_core import _detect_provider, _provider_headers
from app.constants import QUALITY_TIE_BAND, TASK_TYPE_TAGS

# Bare provider names/aliases usable in place of a model_id (the "give me any
# endpoint from this provider" path in Resolver.pick). Every provider that
# appears in data/registry/endpoints.json must be a value here, or that path
# silently returns nothing for it. Kept module-level (not a local inside pick)
# so tests can assert it stays in sync with the shipped registry.
PROVIDER_ALIASES: Dict[str, str] = {
    "google": "google",
    "gemini": "google",
    "cerebras": "cerebras",
    "groq": "groq",
    "huggingface": "huggingface",
    "github": "github",
    "openrouter": "openrouter",
    "mistral": "mistral",
    "nvidia": "nvidia",
    "nim": "nvidia",
    "zhipu": "zhipu",
    "glm": "zhipu",
    "sambanova": "sambanova",
    "kluster": "kluster",
}


class Resolver:
    def __init__(self, registry: Registry, rate_limiter: EndpointRateLimiter):
        self._registry = registry
        self._rate_limiter = rate_limiter

    def _resolve_key(self, ep, user_id: Optional[str]) -> str:
        """Resolve the API key for an endpoint.

        Phase 1b: two possible sources, gated by `ep.key_source`.
          - "byok"   (default): only the user's own Settings-configured key.
            Unchanged from pre-Phase-1b behavior.
          - "pool":  only the operator's shared free-tier key
            (`config.read_pool_key`); the user's own BYOK key for this
            provider, if any, is deliberately ignored.
          - "either": try the pool key FIRST, fall back to the user's BYOK key.
            This precedence (pool before BYOK) is a deliberate 2026-07-21 call —
            it conserves each user's own provider-side limits by spending the
            operator's shared pool first, rather than the more obvious
            "use what's yours before touching the shared pot" ordering.

        Returns "" when no usable key exists for this endpoint under its
        key_source policy.
        """
        key_source = getattr(ep, "key_source", "byok")

        if key_source in ("pool", "either"):
            # Import here (not at module load) to keep config.py's secret
            # reads lazy and mockable in tests, matching key_store's own
            # deferred-import convention below.
            from app.config import read_pool_key
            pool_key = read_pool_key(ep.provider)
            if pool_key:
                return pool_key
            if key_source == "pool":
                return ""

        if not user_id:
            return ""
        # Import here to avoid a hard dependency on Supabase at import time / in tests.
        from app.core import key_store
        return key_store.get_key(user_id, ep.provider) or ""

    def pick(self, model_id: str, user_id: Optional[str] = None) -> List[Tuple[str, str, Dict[str, str], str, str]]:
        """
        Picks all available endpoints for a canonical model_id, sorted by priority.
        If model_id is a known provider name or alias, we pick all active endpoints for that provider.
        Endpoints are keyed exclusively with the user's BYOK key (configured in Settings).
        Only endpoints with a usable key are returned; if the user has no key for any
        available provider, a NoEndpointError is raised prompting them to add one.
        Returns a list of tuples: (base_url, provider_model_id, headers, endpoint_id, provider)
        """
        provider_map = PROVIDER_ALIASES

        if model_id in provider_map:
            prov = provider_map[model_id]
            endpoints = [ep for ep in self._registry._endpoints if ep.provider == prov]
            endpoints.sort(key=lambda ep: ep.priority)
        else:
            endpoints = self._registry.endpoints_for(model_id)

        # R2: quota is per-user under BYOK (each user calls with their own key), so
        # admission must consult THIS user's counters, not a global bucket.
        available = [
            ep for ep in endpoints
            if ep.active and self._rate_limiter.can_use(ep, user_id=user_id)
        ]
        if not available:
            raise NoEndpointError(f"All endpoints for '{model_id}' are rate-limited or inactive.")

        keyed = []
        missing_providers = set()
        for ep in available:
            api_key = self._resolve_key(ep, user_id)
            if not api_key:
                missing_providers.add(ep.provider)
                continue
            provider = _detect_provider(ep.base_url)
            headers = _provider_headers(provider, api_key, ep.base_url)
            keyed.append((ep.base_url, ep.provider_model_id, headers, ep.id, ep.provider))

        if not keyed:
            provs = ", ".join(sorted(missing_providers)) or model_id
            raise NoEndpointError(
                f"No API key configured for {provs}. Add your provider key in Settings to use this model."
            )
        return keyed

    def _has_usable_endpoint(self, model_id: str, user_id: Optional[str]) -> bool:
        """True if the model has ≥1 active, non-cooled-down endpoint that the user
        holds a key for. When user_id is None the key check is skipped (the key is
        applied later in pick()), preserving the pre-BYOK behavior used by tests."""
        endpoints = self._registry.endpoints_for(model_id)
        for ep in endpoints:
            if not (ep.active and self._rate_limiter.can_use(ep, user_id=user_id)):
                continue
            if user_id is not None and not self._resolve_key(ep, user_id):
                continue
            return True
        return False

    def _best_headroom(self, model_id: str, user_id: Optional[str] = None) -> float:
        """C3 live tiebreak signal: the LOWEST usage_pct across this model's
        active endpoints, i.e. how much room its healthiest provider still has.
        0.0 = untouched, 1.0 = at the limit. Lower sorts better.

        Min (not mean) is correct here: the model only needs ONE healthy
        endpoint to serve a request, so a single fresh provider makes the model
        a good choice regardless of how exhausted its siblings are.

        R2: scoped to `user_id`, because quota is per-user under BYOK. Reading a
        global bucket here would rank models by OTHER users' consumption.
        Since R2 this reflects real token counts across day/month windows and
        survives restarts; when nothing has been recorded every model scores
        0.0, so ordering degrades cleanly to quality_rank alone.
        """
        endpoints = self._registry.endpoints_for(model_id)
        pcts = [
            self._rate_limiter.usage_pct(ep, user_id=user_id)
            for ep in endpoints
            if ep.active
        ]
        return min(pcts) if pcts else 1.0

    def _recent_failures(self, model_id: str, user_id: Optional[str] = None) -> int:
        """C3 live tiebreak signal: total consecutive failures recorded across
        this model's active endpoints. Lower sorts better, so a model that just
        started erroring loses to an equally-ranked healthy peer. Scoped per
        user for the same reason as _best_headroom."""
        total = 0
        for ep in self._registry.endpoints_for(model_id):
            if not ep.active:
                continue
            total += self._rate_limiter.failure_count(ep.id, user_id=user_id)
        return total

    def pick_by_capability(self, level: str, visibility: str = "user", user_id: Optional[str] = None) -> List[Tuple[str, str, Dict[str, str], str, str]]:
        """
        Picks all available endpoints at a given capability level.
        When user_id is given, only models the user holds a key for are considered.
        Returns a list of tuples: (base_url, provider_model_id, headers, endpoint_id, provider)
        """
        matching = (
            self._registry.internal_models(level)
            if visibility == "internal"
            else [m for m in self._registry.user_models() if m.capability_level == level]
        )
        for model in matching:
            if user_id is not None and not self._has_usable_endpoint(model.id, user_id):
                continue
            try:
                return self.pick(model.id, user_id=user_id)
            except NoEndpointError:
                continue
        raise NoEndpointError(f"No available endpoint at capability level '{level}'")

    def rank_candidates(
        self,
        level: str,
        visibility: str = "user",
        user_id: Optional[str] = None,
        require_tools: bool = False,
        require_vision: bool = False,
        exclude_model_ids: Optional[set[str]] = None,
        task_type: Optional[str] = None,
    ) -> List[str]:
        """C3: every usable model at `level`, ordered BEST FIRST.

        This replaces the old first-match-wins behaviour, where selection was
        decided by row order in data/registry/models.json -- arbitrary, and
        actively wrong once R1 grew the registry to 31 models (a research task
        could land on an experimental OpenRouter freebie ahead of
        gemini-2.5-pro purely on file position).

        Ordering, in strict precedence:

          1. HARD FILTERS (below) -- level, require_tools, require_vision,
             exclude_model_ids, and "has >=1 active endpoint this user can
             actually reach". These remove candidates entirely.
          2. Task-type match -- a model whose capability_tags satisfy
             `task_type` sorts ahead of one that doesn't. A PREFERENCE, never a
             filter: if nothing at this level carries the tag, every candidate
             ties here and selection degrades to level-only rather than
             failing.
          3. quality_rank (curated, lower is better), bucketed into bands of
             QUALITY_TIE_BAND so near-equals are treated as comparable.
          4. LIVE TIEBREAK within a band -- most quota headroom, then fewest
             recent failures.
          5. model id, purely so the order is deterministic when everything
             above ties (important for reproducible tests).

        Note what is NOT here: provider identity, tier (free/paid), and key
        source. Selection is capability-and-quality only; who serves the model
        is an availability concern resolved later, in pick(). This is what
        retires the old F-6 Groq-priority special case -- Groq models still tend
        to win fast-tier work, but now on merit (generous limits => high
        headroom) rather than a hardcoded provider name in the resolver.
        """
        matching = (
            self._registry.internal_models(level)
            if visibility == "internal"
            else [m for m in self._registry.user_models() if m.capability_level == level]
        )

        wanted_tags = set(TASK_TYPE_TAGS.get(task_type, ())) if task_type else set()

        candidates = []
        for model in matching:
            if require_tools and not model.supports_tools:
                continue
            if require_vision and not model.supports_vision:
                continue
            if exclude_model_ids and model.id in exclude_model_ids:
                continue
            if not self._has_usable_endpoint(model.id, user_id):
                continue
            candidates.append(model)

        def sort_key(m: ModelEntry):
            tag_miss = 0 if (wanted_tags and wanted_tags & set(m.capability_tags)) else 1
            band = m.quality_rank // QUALITY_TIE_BAND
            return (
                tag_miss,
                band,
                self._best_headroom(m.id, user_id),
                self._recent_failures(m.id, user_id),
                m.id,
            )

        candidates.sort(key=sort_key)
        return [m.id for m in candidates]

    def pick_model_by_capability(
        self,
        level: str,
        visibility: str = "user",
        user_id: Optional[str] = None,
        require_tools: bool = False,
        require_vision: bool = False,
        exclude_model_ids: Optional[set[str]] = None,
        task_type: Optional[str] = None,
    ) -> str:
        """Selects the BEST canonical model_id at `level` -- a thin wrapper over
        rank_candidates (C3), kept so all existing call sites work unchanged.

        When user_id is given, the model must have >=1 endpoint whose provider
        the user has configured a key for. require_tools excludes models with
        supports_tools=False (orchestrator/agent picks needing native tool
        calling). require_vision excludes supports_vision=False -- a HARD
        filter, deliberately unlike the task_type preference, because handing
        image content to a text-only model is a correctness bug rather than a
        quality regression (see Q3.1 / chat_complete_single_model).
        exclude_model_ids skips models the caller already tried, e.g.
        vision_enhance.py stepping past a failed pick onto the next
        vision-capable model.
        """
        ranked = self.rank_candidates(
            level,
            visibility=visibility,
            user_id=user_id,
            require_tools=require_tools,
            require_vision=require_vision,
            exclude_model_ids=exclude_model_ids,
            task_type=task_type,
        )
        if not ranked:
            raise NoEndpointError(f"No available model at capability level '{level}'")
        return ranked[0]

    def usable_user_models(self, user_id: Optional[str]) -> List[ModelEntry]:
        """User-facing models that have ≥1 active endpoint the user holds a key for."""
        return [
            m for m in self._registry.user_models()
            if self._has_usable_endpoint(m.id, user_id)
        ]

    def fallback_models(
        self, model_id: str, user_id: Optional[str], task_type: Optional[str] = None
    ) -> List[str]:
        """Ordered list of model_ids to try for a request: the requested model
        first, then other usable models for cross-model failover.

        C4: the tail is now QUALITY-ORDERED via rank_candidates rather than
        registry file order, so failover walks down a ranked list instead of an
        arbitrary one. Same-capability-level models still come before the rest,
        preserving the pre-C4 contract (requested model first, de-duplicated) --
        only the ordering *within* each group improves.

        Deliberately NOT filtered by require_tools/require_vision: this is the
        generic failover path used by chat_stream/chat_complete, and callers
        with a hard capability requirement must not rely on it (see
        normalize.chat_complete_single_model, added in Q3.1 precisely because
        this list is unfiltered and could otherwise hand an image-containing
        prompt to a text-only model).
        """
        ordered: List[str] = [model_id]
        requested = self._registry.get_model(model_id)
        level = requested.capability_level if requested else None

        # Same-level models, best first.
        if level is not None:
            for mid in self.rank_candidates(level, user_id=user_id, task_type=task_type):
                if mid not in ordered:
                    ordered.append(mid)

        # Then everything else usable, also ranked within its own level so the
        # tail is ordered rather than arbitrary.
        other_levels = [
            lvl for lvl in ("research", "balanced", "fast") if lvl != level
        ]
        for lvl in other_levels:
            for mid in self.rank_candidates(lvl, user_id=user_id, task_type=task_type):
                if mid not in ordered:
                    ordered.append(mid)

        return ordered
