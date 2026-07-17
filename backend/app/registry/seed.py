import json
import os
import threading
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
    "active": True,
    "supports_tools": True
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
    "active": True,
    "supports_tools": True
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
    "active": True,
    "supports_tools": True
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
    "active": True,
    # F-11: its active endpoint (HuggingFace's router passthrough for the raw
    # model) doesn't reliably turn DeepSeek-R1's own tool-call tokens into a
    # real structured tool_calls field -- found live leaking as visible text
    # instead of triggering a tool. False until a working tool-calling
    # endpoint for this model is verified (e.g. OpenRouter's, if reactivated).
    "supports_tools": False
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
    "active": True,
    "supports_tools": True
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
    "active": False,
    "supports_tools": True
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
    "active": True,
    "supports_tools": True
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
    "active": False,
    "supports_tools": True
  },
  {
    "id": "gemini-embedding-2",
    "display_name": "Gemini Embedding 2",
    "type": "embedding",
    "visibility": "internal",
    "tier": "free",
    "capability_level": None,
    "capability_tags": [],
    "context_window": 8192,
    "active": True,
    "supports_tools": True
  }
]

INITIAL_ENDPOINTS = [
  {
    "id": "ep-gemini-2.5-flash-google",
    "model_id": "gemini-2.5-flash",
    "provider": "google",
    "provider_model_id": "gemini-2.5-flash",
    "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
    "priority": 1,
    "rpm_limit": 10,
    "rpd_limit": 500,
    "tpm_limit": None,
    "tpd_limit": None,
    "active": True,
    "last_verified": "2026-07-13"
  },
  {
    "id": "ep-gemini-2.5-flash-lite-google",
    "model_id": "gemini-2.5-flash-lite",
    "provider": "google",
    "provider_model_id": "gemini-2.5-flash-lite",
    "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
    "priority": 1,
    "rpm_limit": None,
    "rpd_limit": 1000,
    "tpm_limit": None,
    "tpd_limit": None,
    "active": True,
    "last_verified": "2026-07-13"
  },
  {
    "id": "ep-llama-3.3-70b-groq",
    "model_id": "llama-3.3-70b",
    "provider": "groq",
    "provider_model_id": "llama-3.3-70b-versatile",
    "base_url": "https://api.groq.com/openai/v1",
    "priority": 1,
    "rpm_limit": 30,
    "rpd_limit": 1000,
    "tpm_limit": 12000,
    "tpd_limit": None,
    "active": True,
    "last_verified": "2026-07-13"
  },
  {
    "id": "ep-llama-3.3-70b-cerebras",
    "model_id": "llama-3.3-70b",
    "provider": "cerebras",
    "provider_model_id": "llama-3.3-70b",
    "base_url": "https://api.cerebras.ai/v1",
    "priority": 2,
    "rpm_limit": 30,
    "rpd_limit": None,
    "tpm_limit": None,
    "tpd_limit": 1000000,
    "active": False,
    "last_verified": "2026-06-15"
  },
  {
    "id": "ep-llama-3.3-70b-huggingface",
    "model_id": "llama-3.3-70b",
    "provider": "huggingface",
    "provider_model_id": "meta-llama/Llama-3.3-70B-Instruct",
    "base_url": "https://router.huggingface.co/v1",
    "priority": 3,
    "rpm_limit": 60,
    "rpd_limit": None,
    "tpm_limit": None,
    "tpd_limit": None,
    "active": True,
    "last_verified": "2026-07-13"
  },
  {
    "id": "ep-llama-3.3-70b-github",
    "model_id": "llama-3.3-70b",
    "provider": "github",
    "provider_model_id": "meta-llama-3.3-70b-instruct",
    "base_url": "https://models.inference.ai.azure.com",
    "priority": 4,
    "rpm_limit": 15,
    "rpd_limit": 150,
    "tpm_limit": None,
    "tpd_limit": None,
    "active": False,
    "last_verified": "2026-06-15"
  },
  {
    "id": "ep-llama-3.3-70b-openrouter",
    "model_id": "llama-3.3-70b",
    "provider": "openrouter",
    "provider_model_id": "meta-llama/llama-3.3-70b-instruct:free",
    "base_url": "https://openrouter.ai/api/v1",
    "priority": 5,
    "rpm_limit": 200,
    "rpd_limit": None,
    "tpm_limit": None,
    "tpd_limit": None,
    "active": False,
    "last_verified": "2026-06-15"
  },
  {
    "id": "ep-deepseek-r1-huggingface",
    "model_id": "deepseek-r1",
    "provider": "huggingface",
    "provider_model_id": "deepseek-ai/DeepSeek-R1",
    "base_url": "https://router.huggingface.co/v1",
    "priority": 1,
    "rpm_limit": 60,
    "rpd_limit": None,
    "tpm_limit": None,
    "tpd_limit": None,
    "active": True,
    "last_verified": "2026-07-13"
  },
  {
    "id": "ep-deepseek-r1-github",
    "model_id": "deepseek-r1",
    "provider": "github",
    "provider_model_id": "DeepSeek-R1",
    "base_url": "https://models.inference.ai.azure.com",
    "priority": 2,
    "rpm_limit": 15,
    "rpd_limit": 150,
    "tpm_limit": None,
    "tpd_limit": None,
    "active": False,
    "last_verified": "2026-06-15"
  },
  {
    "id": "ep-deepseek-r1-openrouter",
    "model_id": "deepseek-r1",
    "provider": "openrouter",
    "provider_model_id": "deepseek/deepseek-r1:free",
    "base_url": "https://openrouter.ai/api/v1",
    "priority": 3,
    "rpm_limit": 200,
    "rpd_limit": None,
    "tpm_limit": None,
    "tpd_limit": None,
    "active": False,
    "last_verified": "2026-06-15"
  },
  {
    "id": "ep-gpt-oss-120b-cerebras",
    "model_id": "gpt-oss-120b",
    "provider": "cerebras",
    "provider_model_id": "gpt-oss-120b",
    "base_url": "https://api.cerebras.ai/v1",
    "priority": 1,
    "rpm_limit": 30,
    "rpd_limit": None,
    "tpm_limit": None,
    "tpd_limit": 1000000,
    "active": True,
    "last_verified": "2026-07-13"
  },
  {
    "id": "ep-qwen-3-32b-cerebras",
    "model_id": "qwen-3-32b",
    "provider": "cerebras",
    "provider_model_id": "qwen-3-32b",
    "base_url": "https://api.cerebras.ai/v1",
    "priority": 1,
    "rpm_limit": 30,
    "rpd_limit": None,
    "tpm_limit": None,
    "tpd_limit": 1000000,
    "active": False,
    "last_verified": "2026-06-15"
  },
  {
    "id": "ep-glm-4.7-cerebras",
    "model_id": "glm-4.7",
    "provider": "cerebras",
    "provider_model_id": "zai-glm-4.7",
    "base_url": "https://api.cerebras.ai/v1",
    "priority": 1,
    "rpm_limit": 30,
    "rpd_limit": None,
    "tpm_limit": None,
    "tpd_limit": 1000000,
    "active": True,
    "last_verified": "2026-07-13"
  },
  {
    "id": "ep-text-embedding-004-google",
    "model_id": "text-embedding-004",
    "provider": "google",
    "provider_model_id": "text-embedding-004",
    "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
    "priority": 1,
    "rpm_limit": 1500,
    "rpd_limit": None,
    "tpm_limit": None,
    "tpd_limit": None,
    "active": False,
    "last_verified": "2026-06-15"
  },
  {
    "id": "ep-gemini-embedding-2-google",
    "model_id": "gemini-embedding-2",
    "provider": "google",
    "provider_model_id": "gemini-embedding-2",
    "base_url": "https://generativelanguage.googleapis.com/v1beta",
    "priority": 1,
    "rpm_limit": 1500,
    "rpd_limit": None,
    "tpm_limit": None,
    "tpd_limit": None,
    "active": True,
    "last_verified": "2026-07-13"
  }
]

def _atomic_write_json(path, data) -> None:
    """Writes JSON atomically: readers of `path` never observe a truncated or
    empty file mid-write. `Path.write_text()` opens in 'w' mode, which
    truncates the target to zero bytes before writing any content -- any
    concurrent reader landing in that window sees an empty file and raises
    JSONDecodeError. Found 2026-07-14: once tests started giving each
    pytest-xdist worker its own fresh, empty DATA_DIR (see tests/conftest.py),
    this write path -- previously only ever exercised on a genuinely first-ever
    boot, essentially never under concurrency -- started racing for real,
    surfacing as intermittent JSONDecodeError across several unrelated test
    files. Writing to a temp file in the same directory and `os.replace()`-ing
    it into place is atomic on POSIX: a reader either sees the old inode (still
    fully valid, pre-seed, which won't happen here since we only call this when
    the file doesn't exist yet) or the new one, complete, never a partial one.
    """
    tmp_path = path.with_suffix(path.suffix + f".tmp-{os.getpid()}-{threading.get_ident()}")
    tmp_path.write_text(json.dumps(data, indent=2))
    os.replace(tmp_path, path)


def seed_registry() -> None:
    """Creates the registry directory and writes models.json and endpoints.json if missing."""
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)

    if not MODELS_FILE.exists():
        _atomic_write_json(MODELS_FILE, INITIAL_MODELS)

    if not ENDPOINTS_FILE.exists():
        _atomic_write_json(ENDPOINTS_FILE, INITIAL_ENDPOINTS)
