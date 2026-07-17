from typing import List, Optional, Tuple, Dict
from app.exceptions import NoEndpointError
from app.registry.loader import Registry
from app.registry.schemas import ModelEntry
from app.core.rate_limiter import EndpointRateLimiter
from app.core.llm_core import _detect_provider, _provider_headers

class Resolver:
    def __init__(self, registry: Registry, rate_limiter: EndpointRateLimiter):
        self._registry = registry
        self._rate_limiter = rate_limiter

    def _resolve_key(self, ep, user_id: Optional[str]) -> str:
        """Resolve the API key for an endpoint from the user's BYOK keys (Settings).

        Only per-user keys configured in Settings are used — there is no shared
        fallback of any kind. Returns "" when the user has no key for the provider.
        """
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
        provider_map = {
            "google": "google",
            "gemini": "google",
            "cerebras": "cerebras",
            "groq": "groq",
            "huggingface": "huggingface",
            "github": "github",
            "openrouter": "openrouter"
        }

        if model_id in provider_map:
            prov = provider_map[model_id]
            endpoints = [ep for ep in self._registry._endpoints if ep.provider == prov]
            endpoints.sort(key=lambda ep: ep.priority)
        else:
            endpoints = self._registry.endpoints_for(model_id)

        available = [ep for ep in endpoints if ep.active and self._rate_limiter.can_use(ep)]
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
            if not (ep.active and self._rate_limiter.can_use(ep)):
                continue
            if user_id is not None and not self._resolve_key(ep, user_id):
                continue
            return True
        return False

    def _has_groq_endpoint(self, model_id: str) -> bool:
        """True if any of this model's *active* endpoints are on Groq (
        endpoints_for() already filters to active) -- used by F-6's
        Groq-priority ordering. Does not check rate-limit/cooldown/key
        status; that's still handled by the existing _has_usable_endpoint
        fallback check in pick_model_by_capability, so a Groq endpoint that's
        active but currently rate-limited or keyless still correctly falls
        through to the next model."""
        return any(ep.provider == "groq" for ep in self._registry.endpoints_for(model_id))

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

    def pick_model_by_capability(
        self,
        level: str,
        visibility: str = "user",
        user_id: Optional[str] = None,
        require_tools: bool = False,
        require_vision: bool = False,
        exclude_model_ids: Optional[set[str]] = None,
    ) -> str:
        """
        Selects the first canonical model_id matching the capability level that has
        available endpoints. When user_id is given, the model must have ≥1 endpoint
        whose provider the user has configured a key for. When require_tools is True,
        models with supports_tools=False are excluded (used for orchestrator/agent
        picks that need native tool calling). When require_vision is True, models with
        supports_vision=False are excluded (used for the vision-grounded prompt
        enhancer — see plan_vision_prompt_enhancement.md). exclude_model_ids skips
        models already tried by the caller -- used by vision_enhance.py to step past
        a Groq pick (preferred by the F-6 sort below when the user holds a Groq key)
        onto the next vision-capable model (effectively Gemini) after Groq fails.
        """
        matching = (
            self._registry.internal_models(level)
            if visibility == "internal"
            else [m for m in self._registry.user_models() if m.capability_level == level]
        )
        # F-6: if the user holds a Groq key, prefer models at this capability
        # level that have a Groq endpoint (large rate limits, fast generation)
        # -- stable sort so relative order is otherwise unchanged, and the
        # existing per-model usable-endpoint check below still falls through
        # to the next model if the prioritized one turns out rate-limited/
        # cooled-down/keyless. ModelEntry itself carries no provider (a model
        # can span several providers via its endpoints), so "has a Groq
        # endpoint" is checked via the registry rather than a model attribute.
        if user_id is not None:
            from app.core import key_store
            if key_store.get_key(user_id, "groq"):
                matching = sorted(matching, key=lambda m: not self._has_groq_endpoint(m.id))
        for model in matching:
            if require_tools and not model.supports_tools:
                continue
            if require_vision and not model.supports_vision:
                continue
            if exclude_model_ids and model.id in exclude_model_ids:
                continue
            if self._has_usable_endpoint(model.id, user_id):
                return model.id
        raise NoEndpointError(f"No available model at capability level '{level}'")

    def usable_user_models(self, user_id: Optional[str]) -> List[ModelEntry]:
        """User-facing models that have ≥1 active endpoint the user holds a key for."""
        return [
            m for m in self._registry.user_models()
            if self._has_usable_endpoint(m.id, user_id)
        ]

    def fallback_models(self, model_id: str, user_id: Optional[str]) -> List[str]:
        """Ordered list of model_ids to try for a request: the requested model first,
        then other usable user models for cross-model failover. Models sharing the
        requested model's capability_level come before the rest. De-duplicated."""
        ordered: List[str] = [model_id]
        requested = self._registry.get_model(model_id)
        level = requested.capability_level if requested else None

        usable = self.usable_user_models(user_id)
        same_level = [m.id for m in usable if level is not None and m.capability_level == level]
        others = [m.id for m in usable if m.id not in same_level]

        for mid in same_level + others:
            if mid not in ordered:
                ordered.append(mid)
        return ordered
