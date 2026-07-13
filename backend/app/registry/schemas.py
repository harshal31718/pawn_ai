from pydantic import BaseModel
from typing import Literal, List, Optional

class ModelEntry(BaseModel):
    id: str
    display_name: str
    type: Literal["chat", "embedding", "reasoning"]
    visibility: Literal["user", "internal"]
    tier: Literal["free", "paid"]
    capability_level: Optional[Literal["fast", "balanced", "research"]]
    capability_tags: List[str]
    context_window: int
    active: bool
    supports_tools: bool = True

class EndpointEntry(BaseModel):
    id: str
    model_id: str
    provider: Literal["google", "cerebras", "groq", "huggingface", "github", "openrouter"]
    provider_model_id: str
    base_url: str
    secret: str
    priority: int
    rpm_limit: Optional[int] = None
    rpd_limit: Optional[int] = None
    tpm_limit: Optional[int] = None
    tpd_limit: Optional[int] = None
    active: bool
    last_verified: str

class ModelResponse(BaseModel):
    model_id: str
    display_name: str
    capability_level: Optional[str]
    capability_tags: List[str]
    context_window: int
    endpoint_count: int
    providers: List[str] = []

