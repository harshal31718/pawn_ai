"""Provider registry (2026-07-23): registry/providers.py's loader.

Covers the loader mechanics (glob-and-merge, duplicate-id detection, alias
map construction) in isolation -- test_registry_integrity.py covers the
SHIPPED data files' own correctness.
"""
import importlib
import json

import pytest

from app.registry import providers as providers_module
from app.registry.providers import PROVIDERS, VALID_PROVIDER_IDS, POOL_PROVIDER_IDS, PROVIDER_ALIASES, get_provider, all_providers


def test_providers_loaded_from_shipped_files():
    assert len(PROVIDERS) >= 11
    assert "google" in PROVIDERS
    assert "tavily" in PROVIDERS
    assert "kaggle" in PROVIDERS


def test_valid_provider_ids_matches_loaded_providers():
    assert VALID_PROVIDER_IDS == set(PROVIDERS.keys())


def test_pool_provider_ids_excludes_byok_only_providers():
    assert "tavily" not in POOL_PROVIDER_IDS
    assert "kaggle" not in POOL_PROVIDER_IDS
    assert "google" in POOL_PROVIDER_IDS


def test_provider_aliases_includes_self_mapping():
    assert PROVIDER_ALIASES["google"] == "google"


def test_provider_aliases_includes_known_aliases():
    assert PROVIDER_ALIASES["gemini"] == "google"
    assert PROVIDER_ALIASES["nim"] == "nvidia"
    assert PROVIDER_ALIASES["glm"] == "zhipu"


def test_get_provider_returns_entry():
    entry = get_provider("google")
    assert entry is not None
    assert entry.id == "google"


def test_get_provider_none_for_unknown_id():
    assert get_provider("not-a-real-provider") is None


def test_all_providers_returns_every_entry():
    assert len(all_providers()) == len(PROVIDERS)


def test_duplicate_id_across_files_raises(tmp_path, monkeypatch):
    """Loader-level duplicate detection -- test_registry_integrity.py checks
    the real shipped files never hit this; this test proves the mechanism
    itself actually works, using a throwaway fixture directory."""
    entry = {
        "id": "dupe",
        "name": "Dupe",
        "official_docs_link": "https://example.com",
        "signup_link": "https://example.com",
        "auth_type": "bearer_key",
        "capabilities": ["chat"],
        "aliases": [],
        "type": "byok",
        "last_verified": "2026-07-23",
    }
    (tmp_path / "providers_a.json").write_text(json.dumps([entry]), encoding="utf-8")
    (tmp_path / "providers_b.json").write_text(json.dumps([entry]), encoding="utf-8")

    monkeypatch.setattr(providers_module, "PROVIDERS_DIR", tmp_path)
    with pytest.raises(ValueError, match="Duplicate provider id 'dupe'"):
        providers_module._load()
