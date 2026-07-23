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
    supports_vision: bool = False
    # C1: curated preference ordering WITHIN a capability_level -- lower is
    # better. Sparse (10/20/30...) so models can be inserted between existing
    # ones without renumbering, and so "within QUALITY_TIE_BAND of each other"
    # is a meaningful notion of comparable (see constants.QUALITY_TIE_BAND).
    # Ranks never compete across levels. The default is deliberately the worst
    # possible value: a newly-added, uncurated model must never silently
    # outrank a curated one. Justifications: workspace/plan/router_failover/
    # 02_quality_ranks.md (local-only).
    quality_rank: int = 999

class EndpointEntry(BaseModel):
    id: str
    model_id: str
    # Must stay in sync with key_store.VALID_PROVIDERS and resolver.pick()'s
    # provider_map. Adding a provider to data/registry/endpoints.json without
    # adding it here fails registry load with a Pydantic ValidationError.
    provider: Literal[
        "google", "cerebras", "groq", "huggingface", "github", "openrouter",
        "mistral", "nvidia", "zhipu", "sambanova", "kluster",
    ]
    provider_model_id: str
    base_url: str
    priority: int
    rpm_limit: Optional[int] = None
    rpd_limit: Optional[int] = None
    tpm_limit: Optional[int] = None
    tpd_limit: Optional[int] = None
    active: bool
    last_verified: str
    # Phase 1b: which key source(s) this endpoint may draw from.
    #   "byok"   -- only the user's own Settings-configured key (today's only
    #               behaviour, and the default so every pre-Phase-1b row is
    #               unaffected without being touched).
    #   "pool"   -- only the operator's shared free-tier key
    #               (`config.read_pool_key`); ignores any BYOK key the user
    #               may hold for this provider. Not used by any endpoint yet;
    #               a lever for forcing specific models onto the pool later.
    #   "either" -- may use either. Precedence is POOL FIRST, BYOK fallback
    #               (user's explicit 2026-07-21 call, made to conserve users'
    #               own provider-side limits ahead of the operator's shared
    #               ones) -- see resolver.Resolver._resolve_key.
    key_source: Literal["byok", "pool", "either"] = "byok"

class ModelResponse(BaseModel):
    model_id: str
    display_name: str
    capability_level: Optional[str]
    capability_tags: List[str]
    context_window: int
    endpoint_count: int
    providers: List[str] = []

