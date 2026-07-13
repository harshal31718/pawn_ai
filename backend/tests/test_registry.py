import pytest
from starlette.testclient import TestClient

from app.main import app
from app.registry.loader import load_registry
from app.registry.seed import seed_registry
from app.constants import MODELS_FILE, ENDPOINTS_FILE, REGISTRY_DIR

@pytest.fixture()
def client():
    # Load client which triggers lifespan initialize_managers
    with TestClient(app) as c:
        yield c

def test_registry_seeding_and_loading():
    # 1. Trigger seeding
    seed_registry()
    assert REGISTRY_DIR.exists()
    assert MODELS_FILE.exists()
    assert ENDPOINTS_FILE.exists()
    
    # 2. Loader tests
    registry = load_registry()
    
    # Get model check
    gemini_model = registry.get_model("gemini-2.5-flash")
    assert gemini_model is not None
    assert gemini_model.display_name == "Gemini 2.5 Flash"
    assert gemini_model.visibility == "user"
    
    # Nonexistent model check
    assert registry.get_model("nonexistent") is None
    
    # User models check
    user_models = registry.user_models()
    assert len(user_models) > 0
    assert all(m.visibility == "user" and m.active for m in user_models)
    
    # Internal models check
    internal_fast = registry.internal_models("fast")
    # glm-4.7 and gemini-2.5-flash-lite are visible to user but wait, are they visibility=user or internal?
    # Let's check: text-embedding-004 is internal.
    internal_embed = [m for m in registry._models.values() if m.visibility == "internal"]
    assert len(internal_embed) == 1
    assert internal_embed[0].id == "text-embedding-004"
    
    # Endpoints priority sort check. Registry refresh 2026-07-13 deactivated
    # llama-3.3-70b's cerebras (deprecated), github (platform retiring), and
    # openrouter (:free variant ending) endpoints — only groq + huggingface
    # remain active. endpoints_for() returns active endpoints only.
    endpoints = registry.endpoints_for("llama-3.3-70b")
    assert len(endpoints) >= 2
    # Check priority is sorted ascending: 1, 3 (2/4/5 now inactive)
    priorities = [e.priority for e in endpoints]
    assert priorities == sorted(priorities)
    assert endpoints[0].provider == "groq"         # Priority 1
    assert endpoints[1].provider == "huggingface"  # Priority 3

def test_registry_api_endpoint(client):
    response = client.get("/registry/models")
    assert response.status_code == 200
    data = response.json()
    
    # Check structure
    assert len(data) > 0
    first_model = data[0]
    assert "model_id" in first_model
    assert "display_name" in first_model
    assert "capability_level" in first_model
    assert "capability_tags" in first_model
    assert "context_window" in first_model
    assert "endpoint_count" in first_model
    
    # Check that text-embedding-004 is not returned (visibility is internal)
    model_ids = [m["model_id"] for m in data]
    assert "text-embedding-004" not in model_ids
    
    # Check endpoint count for llama-3.3-70b (registry refresh 2026-07-13:
    # only groq + huggingface remain active, see test_registry_seeding_and_loading)
    llama_entry = next(m for m in data if m["model_id"] == "llama-3.3-70b")
    assert llama_entry["endpoint_count"] >= 2
