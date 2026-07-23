from pydantic import BaseModel, field_validator
from typing import Literal, List, Optional


class ProviderEntry(BaseModel):
    """2026-07-23: single source of truth for "what is a provider" --
    replaces what used to be separately hardcoded in
    key_store.VALID_PROVIDERS, pool_key_store.POOL_VALID_PROVIDERS,
    resolver.PROVIDER_ALIASES, and this file's own EndpointEntry.provider
    Literal. See workspace/schemas/provider_schema.md for the design
    discussion this came out of."""
    id: str
    name: str
    official_docs_link: str
    signup_link: str
    # bearer_key: single Authorization header token (every LLM/search provider
    # today). credentials: a structured payload, not one token (Kaggle's
    # username+api_token pair). oauth reserved for a future provider.
    auth_type: Literal["bearer_key", "oauth", "credentials", "none"]
    # A provider may span more than one -- kept a list rather than the
    # narrower per-endpoint concern of "which models does it serve".
    capabilities: List[Literal["chat", "image", "internet", "kaggle"]]
    # Alternate names that resolve to this id (e.g. "gemini" -> "google").
    aliases: List[str] = []
    # pool: the operator MAY share their own key for this provider as a
    # fallback for keyless users (subject to quota_share's fair division).
    # byok: bring-your-own-key only, no pool sharing exists for it -- this is
    # a mechanism distinction, not a cost one; whether a byok provider is
    # free or paid is the user's own concern, never tracked here.
    type: Literal["byok", "pool"]
    # Short human-readable free-tier description (e.g. "Free tier: 30 RPM /
    # 14.4K RPD") for signup-hint copy on the Providers page -- borrowed from
    # OmniRoute's providers.ts `freeNote` field after a comparison pass.
    # Optional/null: not every provider has a snappy one-line summary.
    free_tier_note: Optional[str] = None
    # Date string (matches EndpointEntry.last_verified's convention) -- docs/
    # signup links and free-tier notes rot; this is the field a
    # registry-refresh-style automation pass would update.
    last_verified: str


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
    # 2026-07-23: was a hardcoded Literal (required a code change + Pydantic
    # edit to add a 12th provider); now a plain str, validated at runtime
    # against the single-source-of-truth data/registry/providers.json
    # instead of a compile-time enum. Same safety (an unknown provider still
    # fails registry load), one step later -- at JSON parse time, not
    # Python-import time.
    provider: str
    provider_model_id: str
    base_url: str
    priority: int
    rpm_limit: Optional[int] = None
    rpd_limit: Optional[int] = None

    @field_validator("provider")
    @classmethod
    def _provider_must_exist(cls, v: str) -> str:
        # Lazy import: registry.providers imports THIS module (ProviderEntry),
        # so importing it back at module load would cycle.
        from app.registry.providers import VALID_PROVIDER_IDS
        if v not in VALID_PROVIDER_IDS:
            raise ValueError(f"Unknown provider '{v}' -- not in data/registry/providers.json")
        return v
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
    #   "either" -- may use either. Precedence is BYOK FIRST, pool fallback
    #               (PAWN 2.0 Phase A.1, 2026-07-23 -- reverses Phase 1b's
    #               pool-first default: the pool is a fallback for keyless
    #               users only, so a user's own key is never displaced by the
    #               shared pot) -- see resolver.Resolver._resolve_key.
    key_source: Literal["byok", "pool", "either"] = "byok"

class ModelResponse(BaseModel):
    model_id: str
    display_name: str
    capability_level: Optional[str]
    capability_tags: List[str]
    context_window: int
    endpoint_count: int
    providers: List[str] = []

