# Data Schemas
## All JSON Files, File Layouts, and Pydantic Models

---

## Registry Files

### models.json

Lives at `data/registry/models.json`. One entry per canonical model. Updated by hand —
adding a new model is a file edit, not a deployment.

**2026 model lineup notes:**
- Gemini 2.0 Flash and 2.0 Flash-Lite were shut down June 1, 2026. All Gemini entries use 2.5 series.
- `gemini-2.5-flash-lite` serves as the fast internal model for summaries and auto-titles (no separate internal-only chat model needed — routing by capability level handles it).
- `glm-4.7` is a preview model on Cerebras; marked active but may be deprecated.
- `qwen-3-32b` is Cerebras's free-tier Qwen3 32B offering.
- `gpt-oss-120b` is OpenAI's open-source 120B model hosted on Cerebras.

```json
[
  {
    "id": "gemini-2.5-flash",
    "display_name": "Gemini 2.5 Flash",
    "type": "chat",
    "visibility": "user",
    "tier": "free",
    "capability_level": "balanced",
    "capability_tags": ["general", "summarization", "instruction-following", "coding"],
    "context_window": 1048576,
    "active": true
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
    "active": true
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
    "active": true
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
    "active": true
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
    "active": true
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
    "active": true
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
    "active": true
  },
  {
    "id": "text-embedding-004",
    "display_name": "Text Embedding 004",
    "type": "embedding",
    "visibility": "internal",
    "tier": "free",
    "capability_level": null,
    "capability_tags": [],
    "context_window": 2048,
    "active": true
  }
]
```

### Field Reference — models.json

| Field | Values | Notes |
|---|---|---|
| `id` | string | Canonical identifier. Never changes. Used everywhere internally. |
| `display_name` | string | Shown in UI dropdown. |
| `type` | `chat` / `embedding` / `reasoning` | What the model does. |
| `visibility` | `user` / `internal` | `user` = appears in dropdown. `internal` = agent/system use only. |
| `tier` | `free` / `paid` | Paid = requires billing on that provider. |
| `capability_level` | `fast` / `balanced` / `research` / null | null for embedding models. |
| `capability_tags` | list of strings | Fine-grained routing tags for agent sub-task routing. |
| `context_window` | int | Max tokens. Used by RAG injection budget. |
| `active` | bool | `false` = disabled without deleting. Resolver skips inactive models. |

### Capability Levels

```
fast        Simple tasks: quick answers, short summaries, single-turn Q&A, rewrites,
            auto-titles. Low latency, high quota. Used for agent internal tasks.
            Examples: Gemini 2.5 Flash Lite, GLM 4.7

balanced    Everyday complex tasks: multi-turn reasoning, coding, analysis,
            longer documents, most user conversations.
            Examples: Llama 3.3 70B, GPT-OSS 120B, Qwen3 32B, Gemini 2.5 Flash

research    Deep/hard tasks: multi-step reasoning, long context synthesis,
            agent planning, critique, research summaries.
            Examples: DeepSeek R1
```

### Capability Tags (controlled vocabulary)

```
general  coding  reasoning  writing  research  math  summarization  instruction-following
```

---

### endpoints.json

Lives at `data/registry/endpoints.json`. One entry per provider endpoint per model.
Multiple entries sharing the same `model_id` are what enable multi-provider failover.

**Schema note:** `tpd_limit` is tokens per day (Cerebras uses this instead of RPD).
`rpd_limit` tracks request-per-day limits where known. For Cerebras, use `tpd_limit`,
set `rpd_limit: null`.

```json
[
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
    "tpm_limit": null,
    "tpd_limit": null,
    "active": true,
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
    "rpm_limit": null,
    "rpd_limit": 1000,
    "tpm_limit": null,
    "tpd_limit": null,
    "active": true,
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
    "rpd_limit": null,
    "tpm_limit": null,
    "tpd_limit": 1000000,
    "active": true,
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
    "rpd_limit": null,
    "tpm_limit": null,
    "tpd_limit": null,
    "active": true,
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
    "tpm_limit": null,
    "tpd_limit": null,
    "active": true,
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
    "rpd_limit": null,
    "tpm_limit": null,
    "tpd_limit": null,
    "active": true,
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
    "rpd_limit": null,
    "tpm_limit": null,
    "tpd_limit": null,
    "active": true,
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
    "tpm_limit": null,
    "tpd_limit": null,
    "active": true,
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
    "rpd_limit": null,
    "tpm_limit": null,
    "tpd_limit": null,
    "active": true,
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
    "rpd_limit": null,
    "tpm_limit": null,
    "tpd_limit": 1000000,
    "active": true,
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
    "rpd_limit": null,
    "tpm_limit": null,
    "tpd_limit": 1000000,
    "active": true,
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
    "rpd_limit": null,
    "tpm_limit": null,
    "tpd_limit": 1000000,
    "active": true,
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
    "rpd_limit": null,
    "tpm_limit": null,
    "tpd_limit": null,
    "active": true,
    "last_verified": "2026-06-15"
  }
]
```

### Field Reference — endpoints.json

| Field | Notes |
|---|---|
| `id` | Stable endpoint ID. Used as key in rate limiter state. |
| `model_id` | Foreign key → models.json `id`. |
| `provider` | One of: `google`, `cerebras`, `huggingface`, `github`, `openrouter`. |
| `provider_model_id` | Exact string this provider expects in the API call. |
| `base_url` | Full base URL for the provider's API. Passed to `stream_llm`. |
| `secret` | Name of the Docker secret file (without path). |
| `priority` | 1 = try first. Higher = fallback. Resolver sorts ascending. |
| `rpm_limit` | Requests per minute. `null` = unknown → reactive failover only. |
| `rpd_limit` | Requests per day. `null` = unknown → reactive failover only. |
| `tpm_limit` | Tokens per minute. `null` = unknown or not tracked. |
| `tpd_limit` | Tokens per day. Cerebras uses this instead of RPD. `null` if not applicable. |
| `active` | `false` = disabled. Resolver skips inactive endpoints. |
| `last_verified` | Date this endpoint was last confirmed working. Manual maintenance. |

### Provider Base URLs

```
google:       https://generativelanguage.googleapis.com/v1beta/openai  (OpenAI-compat REST)
cerebras:     https://api.cerebras.ai/v1
huggingface:  https://router.huggingface.co/v1
github:       https://models.inference.ai.azure.com
openrouter:   https://openrouter.ai/api/v1
```

All providers use the OpenAI-compatible wire format. `_detect_provider(url)` returns
`"openai_compatible"` for all of them. `_provider_headers` adds OpenRouter-specific
`HTTP-Referer` and `X-Title` headers when it detects `openrouter.ai` in the base URL.

### Null Limit Handling

When a limit field is `null`, the rate limiter skips the proactive 90% check for that
dimension. The endpoint is still used; a live 429 still triggers reactive cooldown.
This is correct — HuggingFace limits vary by model and server load. Cerebras limits are
expressed as `tpd_limit` (tokens/day), not `rpd_limit` (requests/day); the rate limiter
handles both independently.

---

## Conversation Data Layout

```
data/conversations/
  <uuid>/
    meta.json         ← title, created_at, updated_at, model_id, message_count
    messages.jsonl    ← append-only; one JSON per line
    summary.md        ← rolling compressed memory; written by summarization background task
```

### meta.json

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "Debugging FastAPI streaming",
  "created_at": "2026-06-15T10:30:00Z",
  "updated_at": "2026-06-15T11:45:00Z",
  "model_id": "llama-3.3-70b",
  "message_count": 12
}
```

### messages.jsonl (one JSON per line)

```json
{"role": "user", "content": "Hello", "timestamp": "2026-06-15T10:30:00Z"}
{"role": "assistant", "content": "Hi there!", "timestamp": "2026-06-15T10:30:05Z", "via_provider": "cerebras", "via_endpoint_id": "ep-llama-3.3-70b-cerebras"}
```

---

## Memory Index

```
data/memory/
  index.json     ← list of memory chunks from finalized conversation summaries
```

### index.json

```json
[
  {
    "id": "mem-001",
    "conv_id": "550e8400-e29b-41d4-a716-446655440000",
    "text": "User prefers concise answers. Working on a FastAPI project with Docker secrets.",
    "embedding": [0.023, -0.14, "..."],
    "created_at": "2026-06-15T11:45:00Z"
  }
]
```

---

## Rate Limit Debug Snapshot (optional, gitignored)

```
data/rate_limits/
  session.json   ← written on startup (all zeros), updated in-memory; debug only
```

```json
{
  "ep-llama-3.3-70b-cerebras": {
    "rpm_count": 12,
    "tpd_tokens": 42000,
    "cooldown_until": null,
    "consecutive_failures": 0,
    "window_start_rpm": "2026-06-15T11:44:00Z"
  }
}
```

This file is never the source of truth at runtime. It exists only for debugging.

---

## Pydantic Schemas

### Registry Schemas (`app/registry/schemas.py`)

```python
from pydantic import BaseModel
from typing import Literal

class ModelEntry(BaseModel):
    id: str
    display_name: str
    type: Literal["chat", "embedding", "reasoning"]
    visibility: Literal["user", "internal"]
    tier: Literal["free", "paid"]
    capability_level: Literal["fast", "balanced", "research"] | None
    capability_tags: list[str]
    context_window: int
    active: bool

class EndpointEntry(BaseModel):
    id: str
    model_id: str
    provider: Literal["google", "cerebras", "huggingface", "github", "openrouter"]
    provider_model_id: str
    base_url: str
    secret: str
    priority: int
    rpm_limit: int | None
    rpd_limit: int | None
    tpm_limit: int | None
    tpd_limit: int | None
    active: bool
    last_verified: str
```

### API Response Schemas

```python
class ModelResponse(BaseModel):
    model_id: str
    display_name: str
    capability_level: str | None
    capability_tags: list[str]
    context_window: int
    endpoint_count: int

class ChatRequest(BaseModel):
    model_id: str
    conversation_id: str | None = None
    doc_id: str | None = None
```
