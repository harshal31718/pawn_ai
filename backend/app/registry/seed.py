import json
from app.constants import REGISTRY_DIR, MODELS_FILE, ENDPOINTS_FILE

INITIAL_MODELS = [
  {
    "id": "gemini-2.5-flash",
    "display_name": "Gemini 2.5 Flash",
    "type": "chat",
    "visibility": "user",
    "tier": "free",
    "capability_level": "balanced",
    "capability_tags": ["general", "summarization", "instruction-following", "coding"],
    "context_window": 1048576,
    "active": True
  },
  {
    "id": "gemini-2.5-flash-lite",
    "display_name": "Gemini 2.5 Flash Lite",
    "type": "chat",
    "visibility": "user",
    "tier": "free",
    "capability_level": "fast",
    "capability_tags": ["general", "summarization"],
    "context_window": 1048576,
    "active": True
  },
  {
    "id": "llama-3.3-70b",
    "display_name": "Llama 3.3 70B",
    "type": "chat",
    "visibility": "user",
    "tier": "free",
    "capability_level": "balanced",
    "capability_tags": ["coding", "reasoning", "general"],
    "context_window": 128000,
    "active": True
  },
  {
    "id": "deepseek-r1",
    "display_name": "DeepSeek R1",
    "type": "reasoning",
    "visibility": "user",
    "tier": "free",
    "capability_level": "research",
    "capability_tags": ["reasoning", "math", "research", "coding"],
    "context_window": 65536,
    "active": True
  },
  {
    "id": "gpt-oss-120b",
    "display_name": "GPT-OSS 120B",
    "type": "chat",
    "visibility": "user",
    "tier": "free",
    "capability_level": "balanced",
    "capability_tags": ["general", "coding", "instruction-following"],
    "context_window": 8192,
    "active": True
  },
  {
    "id": "qwen-3-32b",
    "display_name": "Qwen3 32B",
    "type": "chat",
    "visibility": "user",
    "tier": "free",
    "capability_level": "balanced",
    "capability_tags": ["general", "coding", "reasoning"],
    "context_window": 32768,
    "active": True
  },
  {
    "id": "glm-4.7",
    "display_name": "GLM 4.7",
    "type": "chat",
    "visibility": "user",
    "tier": "free",
    "capability_level": "fast",
    "capability_tags": ["general", "instruction-following"],
    "context_window": 8192,
    "active": True
  },
  {
    "id": "text-embedding-004",
    "display_name": "Text Embedding 004",
    "type": "embedding",
    "visibility": "internal",
    "tier": "free",
    "capability_level": None,
    "capability_tags": [],
    "context_window": 2048,
    "active": True
  }
]

INITIAL_ENDPOINTS = [
  {
    "id": "ep-gemini-2.5-flash-google",
    "model_id": "gemini-2.5-flash",
    "provider": "google",
    "provider_model_id": "gemini-2.5-flash",
    "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
    "secret": "gemini_api_key",
    "priority": 1,
    "rpm_limit": 10,
    "rpd_limit": 500,
    "tpm_limit": None,
    "tpd_limit": None,
    "active": True,
    "last_verified": "2026-06-15"
  },
  {
    "id": "ep-gemini-2.5-flash-lite-google",
    "model_id": "gemini-2.5-flash-lite",
    "provider": "google",
    "provider_model_id": "gemini-2.5-flash-lite",
    "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
    "secret": "gemini_api_key",
    "priority": 1,
    "rpm_limit": None,
    "rpd_limit": 1000,
    "tpm_limit": None,
    "tpd_limit": None,
    "active": True,
    "last_verified": "2026-06-15"
  },
  {
    "id": "ep-llama-3.3-70b-cerebras",
    "model_id": "llama-3.3-70b",
    "provider": "cerebras",
    "provider_model_id": "llama-3.3-70b",
    "base_url": "https://api.cerebras.ai/v1",
    "secret": "cerebras_api_key",
    "priority": 1,
    "rpm_limit": 30,
    "rpd_limit": None,
    "tpm_limit": None,
    "tpd_limit": 1000000,
    "active": True,
    "last_verified": "2026-06-15"
  },
  {
    "id": "ep-llama-3.3-70b-huggingface",
    "model_id": "llama-3.3-70b",
    "provider": "huggingface",
    "provider_model_id": "meta-llama/Llama-3.3-70B-Instruct",
    "base_url": "https://router.huggingface.co/v1",
    "secret": "huggingface_api_key",
    "priority": 2,
    "rpm_limit": 60,
    "rpd_limit": None,
    "tpm_limit": None,
    "tpd_limit": None,
    "active": True,
    "last_verified": "2026-06-15"
  },
  {
    "id": "ep-llama-3.3-70b-github",
    "model_id": "llama-3.3-70b",
    "provider": "github",
    "provider_model_id": "meta-llama-3.3-70b-instruct",
    "base_url": "https://models.inference.ai.azure.com",
    "secret": "github_api_key",
    "priority": 3,
    "rpm_limit": 15,
    "rpd_limit": 150,
    "tpm_limit": None,
    "tpd_limit": None,
    "active": True,
    "last_verified": "2026-06-15"
  },
  {
    "id": "ep-llama-3.3-70b-openrouter",
    "model_id": "llama-3.3-70b",
    "provider": "openrouter",
    "provider_model_id": "meta-llama/llama-3.3-70b-instruct:free",
    "base_url": "https://openrouter.ai/api/v1",
    "secret": "openrouter_api_key",
    "priority": 4,
    "rpm_limit": 200,
    "rpd_limit": None,
    "tpm_limit": None,
    "tpd_limit": None,
    "active": True,
    "last_verified": "2026-06-15"
  },
  {
    "id": "ep-deepseek-r1-huggingface",
    "model_id": "deepseek-r1",
    "provider": "huggingface",
    "provider_model_id": "deepseek-ai/DeepSeek-R1",
    "base_url": "https://router.huggingface.co/v1",
    "secret": "huggingface_api_key",
    "priority": 1,
    "rpm_limit": 60,
    "rpd_limit": None,
    "tpm_limit": None,
    "tpd_limit": None,
    "active": True,
    "last_verified": "2026-06-15"
  },
  {
    "id": "ep-deepseek-r1-github",
    "model_id": "deepseek-r1",
    "provider": "github",
    "provider_model_id": "DeepSeek-R1",
    "base_url": "https://models.inference.ai.azure.com",
    "secret": "github_api_key",
    "priority": 2,
    "rpm_limit": 15,
    "rpd_limit": 150,
    "tpm_limit": None,
    "tpd_limit": None,
    "active": True,
    "last_verified": "2026-06-15"
  },
  {
    "id": "ep-deepseek-r1-openrouter",
    "model_id": "deepseek-r1",
    "provider": "openrouter",
    "provider_model_id": "deepseek/deepseek-r1:free",
    "base_url": "https://openrouter.ai/api/v1",
    "secret": "openrouter_api_key",
    "priority": 3,
    "rpm_limit": 200,
    "rpd_limit": None,
    "tpm_limit": None,
    "tpd_limit": None,
    "active": True,
    "last_verified": "2026-06-15"
  },
  {
    "id": "ep-gpt-oss-120b-cerebras",
    "model_id": "gpt-oss-120b",
    "provider": "cerebras",
    "provider_model_id": "gpt-oss-120b",
    "base_url": "https://api.cerebras.ai/v1",
    "secret": "cerebras_api_key",
    "priority": 1,
    "rpm_limit": 30,
    "rpd_limit": None,
    "tpm_limit": None,
    "tpd_limit": 1000000,
    "active": True,
    "last_verified": "2026-06-15"
  },
  {
    "id": "ep-qwen-3-32b-cerebras",
    "model_id": "qwen-3-32b",
    "provider": "cerebras",
    "provider_model_id": "qwen-3-32b",
    "base_url": "https://api.cerebras.ai/v1",
    "secret": "cerebras_api_key",
    "priority": 1,
    "rpm_limit": 30,
    "rpd_limit": None,
    "tpm_limit": None,
    "tpd_limit": 1000000,
    "active": True,
    "last_verified": "2026-06-15"
  },
  {
    "id": "ep-glm-4.7-cerebras",
    "model_id": "glm-4.7",
    "provider": "cerebras",
    "provider_model_id": "zai-glm-4.7",
    "base_url": "https://api.cerebras.ai/v1",
    "secret": "cerebras_api_key",
    "priority": 1,
    "rpm_limit": 30,
    "rpd_limit": None,
    "tpm_limit": None,
    "tpd_limit": 1000000,
    "active": True,
    "last_verified": "2026-06-15"
  },
  {
    "id": "ep-text-embedding-004-google",
    "model_id": "text-embedding-004",
    "provider": "google",
    "provider_model_id": "text-embedding-004",
    "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
    "secret": "gemini_api_key",
    "priority": 1,
    "rpm_limit": 1500,
    "rpd_limit": None,
    "tpm_limit": None,
    "tpd_limit": None,
    "active": True,
    "last_verified": "2026-06-15"
  }
]

def seed_registry() -> None:
    """Creates the registry directory and writes models.json and endpoints.json if missing."""
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    
    if not MODELS_FILE.exists():
        MODELS_FILE.write_text(json.dumps(INITIAL_MODELS, indent=2))
        
    if not ENDPOINTS_FILE.exists():
        ENDPOINTS_FILE.write_text(json.dumps(INITIAL_ENDPOINTS, indent=2))
