from fastapi import APIRouter, Request
from typing import List

from app.registry.providers import all_providers
from app.registry.schemas import ModelResponse, ProviderEntry

router = APIRouter(prefix="/registry")

@router.get("/models", response_model=List[ModelResponse])
async def get_models(request: Request):
    """Returns the user-facing model catalogue along with endpoint counts."""
    registry = request.app.state.registry
    models = registry.user_models()
    return [
        ModelResponse(
            model_id=m.id,
            display_name=m.display_name,
            capability_level=m.capability_level,
            capability_tags=m.capability_tags,
            context_window=m.context_window,
            endpoint_count=len(registry.endpoints_for(m.id)),
            providers=sorted(list(set(ep.provider for ep in registry.endpoints_for(m.id)))),
        )
        for m in models
    ]


@router.get("/providers", response_model=List[ProviderEntry])
async def get_providers():
    """2026-07-23: the single source of truth for "what is a provider" --
    frontend fetches this once (AppContext) instead of hardcoding provider
    lists (ApiKeysSection.tsx's old PROVIDERS/MORE_PROVIDERS/SEARCH_PROVIDERS
    arrays, and the duplicated formatProviderName() functions)."""
    return all_providers()
