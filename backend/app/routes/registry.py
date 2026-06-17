from fastapi import APIRouter, Request
from typing import List

from app.registry.schemas import ModelResponse

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
        )
        for m in models
    ]
