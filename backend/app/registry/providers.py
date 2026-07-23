"""Provider registry (2026-07-23) -- data, not code.

Single source of truth for "what is a provider", loaded once at import time
(this file is bind-mounted, `backend/data` in docker-compose.yml -- editing
the JSON takes effect on the next backend restart, no rebuild needed).
Replaces what used to be separately hardcoded in:
  - key_store.VALID_PROVIDERS
  - pool_key_store.POOL_VALID_PROVIDERS
  - resolver.PROVIDER_ALIASES
  - registry/schemas.py's EndpointEntry.provider (was a Pydantic Literal)

Loaded via a glob (providers*.json) rather than one hardcoded filename --
kept as a single providers.json while the catalogue is small (~15 entries,
2026-07-23), but re-splitting into one file per capability later (if it
grows toward 200+ providers) needs zero code change here, just moving JSON
objects into more files matching the same glob.

See workspace/schemas/provider_schema.md for the design discussion.
"""
import json

from app.constants import PROVIDERS_DIR, PROVIDERS_GLOB
from app.registry.schemas import ProviderEntry


def _load() -> dict[str, ProviderEntry]:
    entries: list[ProviderEntry] = []
    seen_ids: dict[str, str] = {}  # id -> which file it came from, for a useful collision error
    for path in sorted(PROVIDERS_DIR.glob(PROVIDERS_GLOB)):
        raw = json.loads(path.read_text(encoding="utf-8"))
        for p in raw:
            entry = ProviderEntry(**p)
            if entry.id in seen_ids:
                raise ValueError(
                    f"Duplicate provider id '{entry.id}' in {path.name} "
                    f"(already defined in {seen_ids[entry.id]})"
                )
            seen_ids[entry.id] = path.name
            entries.append(entry)
    return {p.id: p for p in entries}


PROVIDERS: dict[str, ProviderEntry] = _load()

# Every known provider id -- absorbs key_store.VALID_PROVIDERS.
VALID_PROVIDER_IDS: set[str] = set(PROVIDERS.keys())

# Pool-eligible provider ids only -- absorbs pool_key_store.POOL_VALID_PROVIDERS.
POOL_PROVIDER_IDS: set[str] = {p.id for p in PROVIDERS.values() if p.type == "pool"}

# Self + alias -> canonical id, e.g. {"google": "google", "gemini": "google"} --
# absorbs resolver.PROVIDER_ALIASES. A provider's own id always maps to
# itself so "give me any endpoint from this provider" lookups don't need a
# separate self-mapping check.
PROVIDER_ALIASES: dict[str, str] = {
    **{p.id: p.id for p in PROVIDERS.values()},
    **{alias: p.id for p in PROVIDERS.values() for alias in p.aliases},
}


def get_provider(provider_id: str) -> ProviderEntry | None:
    return PROVIDERS.get(provider_id)


def all_providers() -> list[ProviderEntry]:
    return list(PROVIDERS.values())
