from typing import List, Optional, Tuple, Dict
from app.exceptions import NoEndpointError
from app.registry.loader import Registry
from app.core.rate_limiter import EndpointRateLimiter
from app.core.llm_core import _detect_provider, _provider_headers

class Resolver:
    def __init__(self, registry: Registry, rate_limiter: EndpointRateLimiter, secrets: Dict[str, str]):
        self._registry = registry
        self._rate_limiter = rate_limiter
        self._secrets = secrets

    def _resolve_key(self, ep, user_id: Optional[str]) -> str:
        """Resolve the API key for an endpoint: user's BYOK key first, then shared secret."""
        if user_id:
            # Import here to avoid a hard dependency on Supabase at import time / in tests.
            from app.core import key_store
            user_key = key_store.get_key(user_id, ep.provider)
            if user_key:
                return user_key
        return self._secrets.get(ep.secret) or ""

    def pick(self, model_id: str, user_id: Optional[str] = None) -> List[Tuple[str, str, Dict[str, str], str, str]]:
        """
        Picks all available endpoints for a canonical model_id, sorted by priority.
        If model_id is a known provider name or alias, we pick all active endpoints for that provider.
        When user_id is given, the user's BYOK key for each provider is preferred over the
        shared Docker secret. Endpoints with a usable key come first; if no endpoint has any
        key (e.g. in tests / unconfigured dev), all available endpoints are returned so the
        legacy shared-key path is preserved.
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
        unkeyed = []
        for ep in available:
            api_key = self._resolve_key(ep, user_id)
            provider = _detect_provider(ep.base_url)
            headers = _provider_headers(provider, api_key, ep.base_url)
            entry = (ep.base_url, ep.provider_model_id, headers, ep.id, ep.provider)
            if api_key:
                keyed.append(entry)
            else:
                unkeyed.append(entry)
        # Prefer endpoints with a usable key; fall back to all available if none have one.
        return keyed or unkeyed

    def pick_by_capability(self, level: str, visibility: str = "user") -> List[Tuple[str, str, Dict[str, str], str, str]]:
        """
        Picks all available endpoints at a given capability level.
        Returns a list of tuples: (base_url, provider_model_id, headers, endpoint_id, provider)
        """
        matching = (
            self._registry.internal_models(level) 
            if visibility == "internal" 
            else [m for m in self._registry.user_models() if m.capability_level == level]
        )
        for model in matching:
            try:
                return self.pick(model.id)
            except NoEndpointError:
                continue
        raise NoEndpointError(f"No available endpoint at capability level '{level}'")

    def pick_model_by_capability(self, level: str, visibility: str = "user") -> str:
        """
        Selects the first canonical model_id matching the capability level that has available endpoints.
        """
        matching = (
            self._registry.internal_models(level) 
            if visibility == "internal" 
            else [m for m in self._registry.user_models() if m.capability_level == level]
        )
        for model in matching:
            endpoints = self._registry.endpoints_for(model.id)
            available = [ep for ep in endpoints if ep.active and self._rate_limiter.can_use(ep)]
            if available:
                return model.id
        raise NoEndpointError(f"No available model at capability level '{level}'")
