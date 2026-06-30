from typing import List, Optional, Tuple, Dict
from app.exceptions import NoEndpointError
from app.registry.loader import Registry
from app.registry.schemas import ModelEntry
from app.core.rate_limiter import EndpointRateLimiter
from app.core.llm_core import _detect_provider, _provider_headers

class Resolver:
    def __init__(self, registry: Registry, rate_limiter: EndpointRateLimiter, secrets: Dict[str, str]):
        self._registry = registry
        self._rate_limiter = rate_limiter
        self._secrets = secrets

    def _resolve_key(self, ep, user_id: Optional[str]) -> str:
        """Resolve the API key for an endpoint from the user's BYOK keys (Settings).

        Only per-user keys configured in Settings are used — there is no shared
        Docker-secret fallback. Returns "" when the user has no key for the provider.
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

    def pick_model_by_capability(self, level: str, visibility: str = "user", user_id: Optional[str] = None) -> str:
        """
        Selects the first canonical model_id matching the capability level that has
        available endpoints. When user_id is given, the model must have ≥1 endpoint
        whose provider the user has configured a key for.
        """
        matching = (
            self._registry.internal_models(level)
            if visibility == "internal"
            else [m for m in self._registry.user_models() if m.capability_level == level]
        )
        for model in matching:
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
