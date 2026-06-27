import json
from typing import List, Dict, Optional

from app.constants import MODELS_FILE, ENDPOINTS_FILE
from app.registry.schemas import ModelEntry, EndpointEntry
from app.registry.seed import seed_registry

class Registry:
    def __init__(self, models: List[ModelEntry], endpoints: List[EndpointEntry]):
        self._models: Dict[str, ModelEntry] = {m.id: m for m in models}
        self._endpoints: List[EndpointEntry] = endpoints

    def get_model(self, model_id: str) -> Optional[ModelEntry]:
        """Returns the ModelEntry matching model_id, or None if not found."""
        return self._models.get(model_id)

    def endpoints_for(self, model_id: str) -> List[EndpointEntry]:
        """Returns active endpoints for the given model_id, sorted by priority (ascending)."""
        candidates = [
            e for e in self._endpoints 
            if e.model_id == model_id and e.active
        ]
        candidates.sort(key=lambda e: e.priority)
        return candidates

    def user_models(self) -> List[ModelEntry]:
        """Returns all active user-facing models."""
        return [
            m for m in self._models.values() 
            if m.visibility == "user" and m.active
        ]

    def internal_models(self, level: str) -> List[ModelEntry]:
        """Returns active internal-facing models matching the capability_level."""
        return [
            m for m in self._models.values() 
            if m.visibility == "internal" and m.capability_level == level and m.active
        ]

def load_registry() -> Registry:
    """Seeds the registry files if missing, loads the model entries, and returns a Registry instance."""
    seed_registry()
    
    with open(MODELS_FILE, "r", encoding="utf-8") as f:
        models_raw = json.load(f)
    with open(ENDPOINTS_FILE, "r", encoding="utf-8") as f:
        endpoints_raw = json.load(f)
        
    models = [ModelEntry(**m) for m in models_raw]
    endpoints = [EndpointEntry(**e) for e in endpoints_raw]
    
    return Registry(models, endpoints)
