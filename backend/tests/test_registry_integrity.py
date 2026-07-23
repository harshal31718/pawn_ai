"""Integrity checks for the SHIPPED registry data files.

Distinct from test_registry.py, which exercises the loader against the isolated
per-worker test DATA_DIR seeded from `app/registry/seed.py`'s INITIAL_MODELS /
INITIAL_ENDPOINTS. Those fixtures have known, long-standing drift from the real
`backend/data/registry/*.json` files that actually ship, so they cannot catch
mistakes in the shipped data itself.

These tests therefore read `data/registry/*.json` directly from the source tree
(the same pattern `constants.KAGGLE_TEMPLATES_DIR` and `image_presets.json` use
for static bundled data), NOT via DATA_DIR.

Motivating bug (R1, 2026-07-21): `EndpointEntry.provider` is a Literal. Adding
providers to endpoints.json without extending that Literal fails registry load
with a ValidationError at startup -- i.e. it takes the backend down, and no
existing test noticed because the seed fixtures don't contain the new rows.
"""
import json
from pathlib import Path

import pytest

from app.core import key_store
from app.registry.schemas import EndpointEntry, ModelEntry, ProviderEntry

REGISTRY_SRC = Path(__file__).resolve().parent.parent / "data" / "registry"


def _load(name: str):
    return json.loads((REGISTRY_SRC / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def raw_models():
    return _load("models.json")


@pytest.fixture(scope="module")
def raw_endpoints():
    return _load("endpoints.json")


@pytest.fixture(scope="module")
def raw_providers():
    """Every providers*.json file, flattened -- mirrors registry/providers.py's
    own glob-and-merge, but reads the shipped files directly rather than
    going through the loader (same reasoning as raw_models/raw_endpoints
    above). Currently one file (providers.json, 2026-07-23 -- merged back
    from a per-capability split once the catalogue proved small enough that
    the split wasn't earning its complexity); the glob still supports
    re-splitting later with zero code change."""
    entries = []
    for path in sorted(REGISTRY_SRC.glob("providers*.json")):
        entries.extend(json.loads(path.read_text(encoding="utf-8")))
    return entries


def test_every_shipped_model_validates(raw_models):
    """Each models.json row parses as a ModelEntry."""
    for row in raw_models:
        ModelEntry(**row)


def test_every_shipped_endpoint_validates(raw_endpoints):
    """Each endpoints.json row parses as an EndpointEntry.

    This is the check that fails when a new provider is added to the data files
    but not to EndpointEntry.provider's Literal.
    """
    for row in raw_endpoints:
        EndpointEntry(**row)


def test_no_orphan_endpoints(raw_models, raw_endpoints):
    """Every endpoint references a model that actually exists."""
    model_ids = {m["id"] for m in raw_models}
    orphans = sorted(
        {e["id"] for e in raw_endpoints if e["model_id"] not in model_ids}
    )
    assert orphans == [], f"endpoints reference unknown model_id(s): {orphans}"


def test_ids_are_unique(raw_models, raw_endpoints):
    model_ids = [m["id"] for m in raw_models]
    endpoint_ids = [e["id"] for e in raw_endpoints]
    assert len(model_ids) == len(set(model_ids)), "duplicate model id"
    assert len(endpoint_ids) == len(set(endpoint_ids)), "duplicate endpoint id"


def test_every_active_model_has_an_active_endpoint(raw_models, raw_endpoints):
    """An active, user-visible model with no active endpoint can never be served
    -- it would show up in the model picker and then always fail to resolve."""
    active_eps = {e["model_id"] for e in raw_endpoints if e["active"]}
    stranded = sorted(
        m["id"]
        for m in raw_models
        if m["active"] and m["visibility"] == "user" and m["id"] not in active_eps
    )
    assert stranded == [], f"active models with no active endpoint: {stranded}"


def test_endpoint_providers_are_registered_for_byok(raw_endpoints):
    """Three-way sync check: every provider used in endpoints.json must also be
    (a) accepted by EndpointEntry's Literal -- covered by the validation test
    above -- and (b) present in key_store.VALID_PROVIDERS, or the user can never
    save a key for it and the endpoint is permanently unreachable.
    """
    used = {e["provider"] for e in raw_endpoints}
    missing = sorted(used - key_store.VALID_PROVIDERS)
    assert missing == [], (
        f"providers in endpoints.json missing from key_store.VALID_PROVIDERS: {missing}"
    )


def test_endpoint_providers_resolvable_by_bare_name(raw_endpoints):
    """resolver.pick() supports passing a bare provider name as model_id. Every
    provider present in the registry should be reachable that way, otherwise the
    provider-name path silently falls through to endpoints_for() and returns
    nothing."""
    from app.resolver.resolver import PROVIDER_ALIASES

    used = {e["provider"] for e in raw_endpoints}
    missing = sorted(used - set(PROVIDER_ALIASES.values()))
    assert missing == [], (
        f"providers in endpoints.json not resolvable via provider_map: {missing}"
    )


def test_every_selectable_model_has_a_curated_quality_rank(raw_models):
    """C1: quality_rank defaults to 999 (worst) so an uncurated model can never
    silently outrank a curated one -- but that default must never actually ship.
    Any user-facing model still sitting at 999 was added without being ranked,
    and would sort last forever without anyone noticing.

    Models with capability_level None (embeddings) are exempt: they are never
    selected through capability routing.
    """
    unranked = sorted(
        m["id"]
        for m in raw_models
        if m["capability_level"] is not None
        and m["visibility"] == "user"
        and m.get("quality_rank", 999) == 999
    )
    assert unranked == [], (
        f"models missing a curated quality_rank (see 02_quality_ranks.md): {unranked}"
    )


def test_quality_ranks_are_positive(raw_models):
    bad = [m["id"] for m in raw_models if m.get("quality_rank", 999) <= 0]
    assert bad == [], f"quality_rank must be positive: {bad}"


def test_vision_capability_is_consistent(raw_models):
    """C2 made capability_tags first-class in routing, which means a model with
    supports_vision=True but no 'vision' tag would be *deprioritised* for vision
    tasks despite being capable. Found live during C3 bring-up: all three Gemini
    models had exactly that mismatch.
    """
    missing_tag = sorted(
        m["id"] for m in raw_models
        if m["supports_vision"] and "vision" not in m["capability_tags"]
    )
    assert missing_tag == [], (
        f"supports_vision=True but no 'vision' capability tag: {missing_tag}"
    )

    lying_tag = sorted(
        m["id"] for m in raw_models
        if "vision" in m["capability_tags"] and not m["supports_vision"]
    )
    assert lying_tag == [], (
        f"'vision' tag but supports_vision=False: {lying_tag}"
    )


def test_limits_are_positive_when_set(raw_endpoints):
    """A zero/negative limit would make can_use() reject the endpoint forever."""
    bad = []
    for e in raw_endpoints:
        for field in ("rpm_limit", "rpd_limit", "tpm_limit", "tpd_limit"):
            v = e.get(field)
            if v is not None and v <= 0:
                bad.append(f"{e['id']}.{field}={v}")
    assert bad == [], f"non-positive limits: {bad}"


def test_key_source_is_a_valid_literal(raw_endpoints):
    """Phase 1b: every endpoint must declare a key_source EndpointEntry actually
    accepts. Redundant with test_every_shipped_endpoint_validates (Pydantic
    would already reject an invalid value), but a direct field check here gives
    a much clearer failure message than a validation traceback would.
    """
    valid = {"byok", "pool", "either"}
    bad = sorted(
        f"{e['id']}={e.get('key_source')!r}"
        for e in raw_endpoints
        if e.get("key_source", "byok") not in valid
    )
    assert bad == [], f"invalid key_source: {bad}"


def test_every_shipped_endpoint_declares_key_source_explicitly(raw_endpoints):
    """Not a correctness requirement (EndpointEntry defaults to \"byok\"), but
    the shipped data file is meant to be self-documenting about which endpoints
    are pool-eligible -- a row silently relying on the default is easy to lose
    track of at 47+ rows. All current rows were deliberately set to "either"
    when Phase 1b shipped (2026-07-21); this test would need updating, not the
    data, if a future row is intentionally added without the field.
    """
    missing = sorted(e["id"] for e in raw_endpoints if "key_source" not in e)
    assert missing == [], f"endpoints missing an explicit key_source: {missing}"


# ── Provider registry (2026-07-23) ──────────────────────────────────────────


def test_every_shipped_provider_validates(raw_providers):
    """Each providers_*.json row parses as a ProviderEntry."""
    for row in raw_providers:
        ProviderEntry(**row)


def test_no_duplicate_provider_ids_across_files(raw_providers):
    """The loader (registry/providers.py) raises on this at import time --
    this test gives the same failure a clear, direct message instead of a
    startup crash traceback."""
    ids = [p["id"] for p in raw_providers]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert dupes == [], f"duplicate provider ids across providers_*.json files: {dupes}"


def test_no_alias_collides_with_another_providers_id_or_alias(raw_providers):
    """An alias must resolve unambiguously -- it can't equal another
    provider's own id (which one would "gemini" mean?), and two providers
    can't both claim the same alias string."""
    ids = {p["id"] for p in raw_providers}
    alias_owners: dict[str, str] = {}
    problems = []
    for p in raw_providers:
        for alias in p.get("aliases", []):
            if alias in ids:
                problems.append(f"{p['id']}'s alias {alias!r} collides with a real provider id")
            elif alias in alias_owners and alias_owners[alias] != p["id"]:
                problems.append(
                    f"alias {alias!r} claimed by both {alias_owners[alias]!r} and {p['id']!r}"
                )
            else:
                alias_owners[alias] = p["id"]
    assert problems == [], problems


def test_every_endpoint_provider_exists_in_the_provider_registry(raw_endpoints, raw_providers):
    """Referential integrity: endpoints.json's `provider` field must reference
    a real provider id -- this is what EndpointEntry's field_validator
    enforces at load time (test_every_shipped_endpoint_validates already
    exercises that indirectly); this test gives a direct, readable failure
    listing exactly which ids are missing instead of a validation traceback."""
    provider_ids = {p["id"] for p in raw_providers}
    used = {e["provider"] for e in raw_endpoints}
    missing = sorted(used - provider_ids)
    assert missing == [], f"endpoints.json references unknown provider ids: {missing}"


def test_pool_type_providers_match_pool_key_store(raw_providers):
    """pool_key_store.POOL_VALID_PROVIDERS is derived from providers.py's
    POOL_PROVIDER_IDS -- this asserts the shipped data's own `type: "pool"`
    rows are exactly that set, catching a drift if providers.py's derivation
    logic ever changes without the data being reviewed."""
    from app.core import pool_key_store

    pool_ids = {p["id"] for p in raw_providers if p["type"] == "pool"}
    assert pool_ids == pool_key_store.POOL_VALID_PROVIDERS
