# Phase 1.6 — Rate-Limit Resilience
## Steps R1–R4: Registry, Rate Limiter, Resolver, Frontend Wiring

---

## Context

Built on a feature branch (`dev/rate-limit-resilience`) on top of main.
Merges to main after R4 is verified, before Phase 2 starts.

Full design reference for the provider layer: `plan/03-provider-layer.md`
Data schemas for registry files: `plan/02-data-schemas.md`

---

## The Problem

Free-tier rate limits are structural, not temporary. Each provider imposes daily (rpd)
and per-minute (rpm) caps. Two failure modes:

**Hard wall:** provider returns 429 mid-request. Context already sent, tokens consumed
on the provider side, reply incomplete. User sees an error. They must manually switch
and re-send.

**Soft wall:** approaching the daily cap. The next message will 429. Better to reroute
cleanly before sending than recover from a hard wall mid-stream.

Current state at end of Phase 1.5: when a provider returns 429, the request dies with
an error message. The user must manually switch models.

---

## The Core Insight

**The unit of identity is the model (weights), not the provider (host).**

`llama-3.3-70b` on Cerebras and `meta-llama/Llama-3.3-70B-Instruct` on HuggingFace are
the same weights. Quality is identical. The user selected "Llama 3.3 70B". They don't
care which data centre answers, as long as the conversation continues.

One canonical model ID maps to multiple provider endpoints. When one is unavailable,
the next is tried transparently.

---

## Failover Strategy

**Hybrid: proactive at 90% + reactive on live 429.**

```
For each request:
  1. Resolver picks the highest-priority available endpoint
  2. "Available" = not in cooldown AND usage < 90% of known limit
  3. If all endpoints for this model are exhausted → NoEndpointError

On live 429 from provider:
  1. mark_cooldown(endpoint, 60s)
  2. Resolver picks next endpoint
  3. Emit provider_switch SSE event
  4. Retry the full request from scratch on new endpoint
  (no partial-stream resume — splicing mid-token produces inconsistent output)
```

The 90% threshold is chosen because mid-conversation rerouting after the request starts is
expensive: the full history has already been serialized and sent. A clean cutover before
the wall is always cheaper.

---

## What Changes vs Phase 1.5

| Component | Before (Phase 1.5) | After (Phase 1.6) |
|---|---|---|
| `normalize.chat_stream` | `(provider_key, messages, model)` | `(model_id, messages)` |
| `ChatRequest.model_id` | `provider + model` | canonical `model_id` only |
| Model dropdown | hardcoded TS array | fetched from `GET /registry/models` |
| Endpoint selection | explicit in the route | resolver picks it |
| Rate limit tracking | none | `EndpointRateLimiter` |
| Failover | manual (user action) | automatic with `provider_switch` event |
| Agent routing | hardcoded model IDs | `PURPOSE_TO_LEVEL` + `Resolver.pick_by_capability` |

---

## Step R1 — Registry Foundation

**Goal:** models and endpoints become maintainable data (JSON), not hardcoded TS/PY.
A new backend route serves the catalog. Three new provider API keys are wired.
**Demo:** `GET /registry/models` returns the catalog grouped by capability level.

### Files Created

`backend/app/registry/schemas.py` — Pydantic `ModelEntry`, `EndpointEntry` (see `plan/02-data-schemas.md`)

`backend/app/registry/seed.py`:
```python
def seed_registry() -> None:
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    if not MODELS_FILE.exists():
        MODELS_FILE.write_text(json.dumps(INITIAL_MODELS, indent=2))
    if not ENDPOINTS_FILE.exists():
        ENDPOINTS_FILE.write_text(json.dumps(INITIAL_ENDPOINTS, indent=2))
```
Called from `app_initializer.initialize_managers()` before loading.

`backend/app/registry/loader.py`:
```python
class Registry:
    def __init__(self, models: list[ModelEntry], endpoints: list[EndpointEntry]):
        self._models = {m.id: m for m in models}
        self._endpoints = endpoints

    def get_model(self, model_id: str) -> ModelEntry: ...
    def endpoints_for(self, model_id: str) -> list[EndpointEntry]:
        # Returns active endpoints sorted by priority ascending
        ...
    def user_models(self) -> list[ModelEntry]:
        # visibility == "user" AND active == True
        ...
    def internal_models(self, level: str) -> list[ModelEntry]:
        # visibility == "internal" AND capability_level == level AND active == True
        ...

def load_registry() -> Registry:
    seed_registry()
    models = [ModelEntry(**m) for m in json.loads(MODELS_FILE.read_text())]
    endpoints = [EndpointEntry(**e) for e in json.loads(ENDPOINTS_FILE.read_text())]
    return Registry(models, endpoints)
```

`backend/app/routes/registry.py`:
```python
def setup_registry_routes(registry: Registry) -> APIRouter:
    router = APIRouter(prefix="/registry")

    @router.get("/models")
    async def get_models() -> list[ModelResponse]:
        models = registry.user_models()
        return [
            ModelResponse(
                model_id=m.id,
                display_name=m.display_name,
                capability_level=m.capability_level,
                capability_tags=m.capability_tags,
                context_window=m.context_window,
                endpoint_count=len(registry.endpoints_for(m.id)),
            )
            for m in models
        ]
    return router
```

`backend/app/app_initializer.py` (introduced here):
```python
def initialize_managers() -> dict:
    registry = load_registry()
    # rate_limiter and resolver added in R2/R3
    return {"registry": registry}
```

`backend/app/main.py` updated:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    deps = initialize_managers()
    app.state.registry = deps["registry"]
    yield

app = FastAPI(lifespan=lifespan)
```

### New Secrets

Three new provider keys, same pattern as existing ones:
```
secrets/huggingface_api_key         (gitignored)
secrets/huggingface_api_key.example
secrets/github_api_key              (gitignored)
secrets/github_api_key.example
secrets/openrouter_api_key          (gitignored)
secrets/openrouter_api_key.example
```

Add all three to `docker-compose.yml` secrets block and `config.py`.

Tests: registry loader roundtrip, `endpoints_for` priority sort, `GET /registry/models` happy path.

Commit: `feat: model registry — data files + loader + GET /registry/models + new provider secrets`

---

## Step R2 — Rate Limiter

**Goal:** in-memory usage tracking per endpoint, rolling windows, 90% threshold, cooldowns.
**Demo:** unit tests show an endpoint flips unavailable at ≥90% usage and recovers after
window reset or cooldown expiry.

### Implementation

`backend/app/core/rate_limiter.py`:

```python
from collections import deque
from dataclasses import dataclass, field
import time

@dataclass
class _EndpointState:
    rpm_timestamps: deque = field(default_factory=deque)
    rpd_timestamps: deque = field(default_factory=deque)
    tpm_tokens: int = 0
    tpm_window_start: float = field(default_factory=time.time)
    cooldown_until: float | None = None
    consecutive_failures: int = 0

class EndpointRateLimiter:
    def __init__(self):
        self._state: dict[str, _EndpointState] = {}

    def _get(self, endpoint_id: str) -> _EndpointState:
        if endpoint_id not in self._state:
            self._state[endpoint_id] = _EndpointState()
        return self._state[endpoint_id]

    def _prune(self, state: _EndpointState) -> None:
        now = time.time()
        cutoff_rpm = now - 60
        cutoff_rpd = now - 86400
        while state.rpm_timestamps and state.rpm_timestamps[0] < cutoff_rpm:
            state.rpm_timestamps.popleft()
        while state.rpd_timestamps and state.rpd_timestamps[0] < cutoff_rpd:
            state.rpd_timestamps.popleft()

    def can_use(self, endpoint: EndpointEntry) -> bool:
        state = self._get(endpoint.id)
        self._prune(state)
        now = time.time()
        if state.cooldown_until and now < state.cooldown_until:
            return False
        if endpoint.rpm_limit and len(state.rpm_timestamps) >= 0.9 * endpoint.rpm_limit:
            return False
        if endpoint.rpd_limit and len(state.rpd_timestamps) >= 0.9 * endpoint.rpd_limit:
            return False
        return True

    def record_call(self, endpoint_id: str, token_count: int = 0) -> None:
        state = self._get(endpoint_id)
        self._prune(state)
        now = time.time()
        state.rpm_timestamps.append(now)
        state.rpd_timestamps.append(now)

    def record_429(self, endpoint_id: str, retry_after: int = 60) -> None:
        state = self._get(endpoint_id)
        state.cooldown_until = time.time() + retry_after
        state.consecutive_failures = 0

    def record_connect_failure(self, endpoint_id: str) -> None:
        state = self._get(endpoint_id)
        state.consecutive_failures += 1
        if state.consecutive_failures >= 2:
            state.cooldown_until = time.time() + 20  # dead-host cooldown

    def record_success(self, endpoint_id: str) -> None:
        self._get(endpoint_id).consecutive_failures = 0

    def usage_pct(self, endpoint: EndpointEntry) -> float:
        state = self._get(endpoint.id)
        self._prune(state)
        pcts = []
        if endpoint.rpm_limit:
            pcts.append(len(state.rpm_timestamps) / endpoint.rpm_limit)
        if endpoint.rpd_limit:
            pcts.append(len(state.rpd_timestamps) / endpoint.rpd_limit)
        return max(pcts) if pcts else 0.0
```

Update `initialize_managers()`:
```python
def initialize_managers() -> dict:
    registry = load_registry()
    rate_limiter = EndpointRateLimiter()
    return {"registry": registry, "rate_limiter": rate_limiter}
```

Tests:
- 90% threshold on rpm (exact boundary: 27/30 → ok, 27+1 = 28 = 93% → blocked)
- 90% threshold on rpd independently
- Cooldown expiry (monkeypatched time)
- Rolling window reset (timestamps pruned after 60s)
- Null limit passthrough (no rpm_limit → can_use True regardless of call count)
- Dead-host cooldown after 2 consecutive connect failures

Commit: `feat: in-memory rate limiter — rolling windows, 90% threshold, cooldowns, dead-host`

---

## Step R3 — Resolver + normalize Contract Change

**Goal:** `normalize.chat_stream` takes canonical `model_id`; resolver handles endpoint
selection and failover; route stops passing provider strings.
**Demo:** force priority-1 endpoint past 90% → reply served by next endpoint;
`provider_switch` event emitted; context intact.

### Resolver

`backend/app/resolver/resolver.py`:
```python
class Resolver:
    def __init__(self, registry: Registry, rate_limiter: EndpointRateLimiter, secrets: dict[str, str]):
        self._registry = registry
        self._rate_limiter = rate_limiter
        self._secrets = secrets

    def pick(self, model_id: str) -> list[tuple[str, str, dict]]:
        endpoints = self._registry.endpoints_for(model_id)
        available = [ep for ep in endpoints if ep.active and self._rate_limiter.can_use(ep)]
        if not available:
            raise NoEndpointError(f"All endpoints for '{model_id}' are rate-limited or inactive.")
        result = []
        for ep in available:
            api_key = self._secrets.get(ep.secret, "")
            provider = _detect_provider(ep.base_url)
            headers = _provider_headers(provider, api_key, ep.base_url)
            result.append((ep.base_url, ep.provider_model_id, headers, ep.id))
        return result

    def pick_by_capability(self, level: str, visibility: str = "internal") -> list[tuple[str, str, dict, str]]:
        matching = self._registry.internal_models(level) if visibility == "internal" else \
                   [m for m in self._registry.user_models() if m.capability_level == level]
        for model in matching:
            try:
                return self.pick(model.id)
            except NoEndpointError:
                continue
        raise NoEndpointError(f"No available endpoint at capability level '{level}'")
```

### normalize.py Contract Change

```python
# Before (Phase 1.5):
async def chat_stream(provider_key: str, messages: list, model: str | None = None): ...

# After (Phase 1.6):
async def chat_stream(
    model_id: str,
    messages: list,
    resolver: Resolver,
    rate_limiter: EndpointRateLimiter,
    on_provider_switch: Callable | None = None,
) -> AsyncGenerator[str, None]: ...
```

Internal flow:
1. `candidates = resolver.pick(model_id)` → `[(url, model_name, headers, endpoint_id), ...]`
2. `stream_llm_with_fallback(candidates, messages, on_switch)` → yields tokens
3. `rate_limiter.record_call(endpoint_id)` on each successful token
4. On `ProviderError(kind="rate_limit")`: `rate_limiter.record_429(endpoint_id)` + `on_switch` fires + retry next
5. On `ProviderError(kind="connect_error")`: `rate_limiter.record_connect_failure(endpoint_id)` + retry next

### Chat Route Update

`ChatRequest` loses `provider` and `model` fields. Gains `model_id: str` only.

```python
class ChatRequest(BaseModel):
    model_id: str
    conversation_id: str | None = None
    doc_id: str | None = None
```

Route calls `normalize.chat_stream(req.model_id, full_messages, resolver, rate_limiter, on_switch=emit_switch)`.

On `provider_switch`, the route yields a `provider_switch` SSE event mid-stream.

### Agent Routing Update

`app/agent/routing.py` — swap `INTERNAL_PURPOSES` for `PURPOSE_TO_LEVEL`:

```python
PURPOSE_TO_LEVEL = {
    "plan":     "fast",
    "draft":    "balanced",
    "critique": "balanced",
    "research": "research",
}
```

Agent nodes call `resolver.pick_by_capability(PURPOSE_TO_LEVEL[purpose])` instead of hardcoded model IDs.

### Update initialize_managers()

```python
def initialize_managers() -> dict:
    registry = load_registry()
    rate_limiter = EndpointRateLimiter()
    secrets = {
        "gemini_api_key":      config.GEMINI_API_KEY,
        "cerebras_api_key":    config.CEREBRAS_API_KEY,
        "huggingface_api_key": config.HUGGINGFACE_API_KEY,
        "github_api_key":      config.GITHUB_API_KEY,
        "openrouter_api_key":  config.OPENROUTER_API_KEY,
    }
    resolver = Resolver(registry, rate_limiter, secrets)
    return {"registry": registry, "rate_limiter": rate_limiter, "resolver": resolver}
```

Tests: resolver priority ordering, 90% skip, 429 → retry chain, all-exhausted error,
`provider_switch` event emission, capability-level routing.

Commit: `feat: resolver + normalize(model_id) — transparent endpoint failover`

---

## Step R4 — Frontend Wiring

**Goal:** model dropdown driven by the registry; failover visible to the user.
**Demo:** dropdown shows Fast / Balanced / Research groups from API; on failover an inline
"Switched to GitHub Models" notice appears; each reply carries a provider badge.

### ModelSwitcher (replace hardcoded list)

```typescript
// src/components/ModelSwitcher.tsx

useEffect(() => {
  fetch(`${BASE_URL}/registry/models`)
    .then(r => r.json())
    .then((models: ModelResponse[]) => setModels(models));
}, []);

// Group by capability_level: Fast / Balanced / Research
// Filter: only models with capability_level non-null
// Label: `${model.display_name} (${model.context_window / 1000}K ctx)`
```

`models.ts` (the hardcoded array from Phase 1) is deleted in this step.

### Provider Switch Notice

In `streamChat` `onProviderSwitch` callback:
```typescript
onProviderSwitch(from: string, to: string) {
  insertNotice(`Switched to ${formatProvider(to)} (${formatProvider(from)} rate limit reached)`);
}
```

Notice is inserted as a non-message UI element between conversation turns. Dismissable.

### Provider Badge on Message Bubbles

- `done` event carries `via_provider` field
- `Message` component receives `viaProvider?: string`
- Small faded badge below the bubble: `via Cerebras`

Tests: ModelSwitcher renders from mocked API response, grouped by level;
`provider_switch` notice renders; provider badge renders on assistant messages.

Commit: `feat: registry-driven model dropdown + provider badge + failover notice`

---

## Merge Gate

After R4 passes all tests:
1. Merge `dev/rate-limit-resilience` → `main`
2. Tag the release
3. Start Phase 2

---

## Phase 1.6 Completion Checklist

- [ ] `GET /registry/models` returns all active user-visible models grouped by capability
- [ ] New provider secrets mount correctly in Docker
- [ ] `can_use` returns False at ≥90% rpm or rpd (individually)
- [ ] Cooldown expires correctly after retry_after seconds
- [ ] Rolling window resets correctly after 60s / 24h
- [ ] Null limits allow pass-through (reactive only)
- [ ] Dead-host cooldown after 2 consecutive connect failures
- [ ] Resolver skips exhausted endpoints and returns ordered candidates
- [ ] `NoEndpointError` raised when all endpoints are unavailable
- [ ] `provider_switch` event emitted on failover
- [ ] Chat route accepts `model_id` only (no `provider` + `model`)
- [ ] Agent capability routing uses `PURPOSE_TO_LEVEL` (no hardcoded provider names)
- [ ] ModelSwitcher fetches from API (no hardcoded list)
- [ ] Provider badge appears on assistant message bubbles
- [ ] Failover notice appears inline in conversation
- [ ] All backend tests pass
- [ ] Feature branch merged to main
