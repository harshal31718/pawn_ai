# Provider Layer
## URL-Routing, LLM Core, Rate Limiter, Resolver, Full Request Flow

---

## Overview

The provider layer has three components that work in sequence:

```
chat_stream(model_id, messages)
      ↓
  Resolver.pick(model_id)        → ordered [(url, model_name, headers), ...]
      ↓
  stream_llm_with_fallback(...)  → emits tokens + provider_switch events
      ↓
  stream_llm(url, model, ...)    → _detect_provider(url) → dispatch → yield tokens
```

The caller (`chat.py` route) only knows `model_id`. The resolver and llm_core handle
everything else: endpoint selection, provider detection, auth headers, failover, rate tracking.

---

## llm_core.py

### _detect_provider(url)

Detects provider from the URL hostname. No explicit provider string — the URL is the authority.

```python
import urllib.parse

def _detect_provider(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower()
    if "anthropic" in host:
        return "anthropic"
    # openrouter, cerebras, huggingface, github, generativelanguage (Google OAI compat) → all openai_compatible
    return "openai_compatible"
```

Google's endpoint (`generativelanguage.googleapis.com/v1beta/openai`) is OpenAI-compatible.
No special Google branch. Adding any future provider that uses the OpenAI wire format requires
zero code change — just a new endpoints.json entry.

### _provider_headers(provider, api_key, base_url)

Auth headers differ by provider. Base URL is used to detect OpenRouter (needs extra headers).

```python
def _provider_headers(provider: str, api_key: str, base_url: str) -> dict:
    if provider == "anthropic":
        return {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
    headers = {"Authorization": f"Bearer {api_key}"}
    if "openrouter.ai" in base_url:
        headers["HTTP-Referer"] = "https://pawn.local"
        headers["X-Title"] = "PAWN"
    return headers
```

### _sanitize_llm_messages(messages)

Clean messages before every provider call. Prevents malformed payloads from reaching providers.

```python
def _sanitize_llm_messages(messages: list[dict]) -> list[dict]:
    # 1. Strip non-standard fields (keep only role, content, tool_call_id, tool_calls, name)
    # 2. Remove orphaned tool messages (tool result without preceding tool_call)
    # 3. Merge consecutive messages from the same role (some providers reject back-to-back same-role)
    ...
```

### _format_upstream_error(status_code, provider, body)

Turn raw HTTP errors into user-readable sentences.

```python
def _format_upstream_error(status_code: int, provider: str, body: str) -> str:
    if status_code == 401:
        return f"API key rejected by {provider} — check your key in settings."
    if status_code == 429:
        return f"Rate limit reached on {provider} — switching to next endpoint."
    if status_code >= 500:
        return f"{provider} returned a server error — retrying on next endpoint."
    return f"{provider} returned an unexpected error ({status_code})."
```

### Shared httpx.AsyncClient

One process-wide client, lazy-initialized. Keeps TCP/TLS connections warm.

```python
_client: httpx.AsyncClient | None = None

def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))
    return _client
```

### stream_llm(url, model, messages, headers)

Single-endpoint streaming call. Raises `ProviderError` on any failure.

```python
async def stream_llm(
    url: str,
    model: str,
    messages: list[dict],
    headers: dict,
) -> AsyncGenerator[str, None]:
    provider = _detect_provider(url)
    clean_messages = _sanitize_llm_messages(messages)
    payload = _build_payload(provider, model, clean_messages)

    try:
        async with _get_client().stream("POST", f"{url}/chat/completions", json=payload, headers=headers) as resp:
            if resp.status_code == 429:
                raise ProviderError(kind="rate_limit", message=_format_upstream_error(429, provider, ""))
            if resp.status_code >= 400:
                body = await resp.aread()
                raise ProviderError(kind="upstream_error", message=_format_upstream_error(resp.status_code, provider, body.decode()))
            async for line in resp.aiter_lines():
                token = _parse_sse_line(line)
                if token:
                    yield token
    except httpx.ConnectError:
        raise ProviderError(kind="connect_error", message=f"Could not reach {url}")
    except httpx.TimeoutException:
        raise ProviderError(kind="timeout", message=f"Request to {url} timed out")
```

### stream_llm_with_fallback(candidates, messages, on_switch)

Tries candidates in order. On rate-limit failure: calls `on_switch`, continues to next.
On connect failure: increments consecutive_failures (handled by caller via rate_limiter).

```python
async def stream_llm_with_fallback(
    candidates: list[tuple[str, str, dict]],  # (url, model_name, headers)
    messages: list[dict],
    on_switch: Callable[[str, str], None] | None = None,
) -> AsyncGenerator[str, None]:
    last_error = None
    for i, (url, model, headers) in enumerate(candidates):
        try:
            async for token in stream_llm(url, model, messages, headers):
                yield token
            return
        except ProviderError as e:
            last_error = e
            if e.kind in ("rate_limit", "upstream_error", "connect_error", "timeout"):
                if i < len(candidates) - 1:
                    next_url, _, _ = candidates[i + 1]
                    if on_switch:
                        on_switch(url, next_url)
                    continue
    raise last_error or NoEndpointError("All endpoints failed")
```

---

## EndpointRateLimiter

Lives in `app/core/rate_limiter.py`. Tracks outbound quota against upstream providers.
This is different from any future inbound rate limiter (per-IP request throttling on PAWN's
own API) — different concern, different class.

### State Per Endpoint

```python
@dataclass
class _EndpointState:
    rpm_timestamps: deque[float]    # epoch seconds of calls in the last 60s
    rpd_timestamps: deque[float]    # epoch seconds of calls in the last 24h
    tpm_tokens: int                 # token count in current minute window
    tpm_window_start: float         # epoch seconds
    cooldown_until: float | None    # epoch seconds; None = no cooldown
    consecutive_failures: int       # for dead-host detection (>= 2 → 20s cooldown)
```

### Public Interface

```python
class EndpointRateLimiter:

    def can_use(self, endpoint: EndpointEntry) -> bool:
        # Returns False if:
        #   - in cooldown (cooldown_until > now)
        #   - rpm_count >= 0.9 * rpm_limit (proactive; only if rpm_limit is not null)
        #   - rpd_count >= 0.9 * rpd_limit (proactive; only if rpd_limit is not null)
        # Null limits: skip proactive check, allow through (reactive failover only)

    def record_call(self, endpoint_id: str, token_count: int = 0) -> None:
        # Appends now() to rpm_timestamps and rpd_timestamps
        # Adds token_count to tpm_tokens
        # Prunes stale timestamps (> 60s old for rpm, > 24h for rpd)

    def record_429(self, endpoint_id: str, retry_after: int = 60) -> None:
        # Sets cooldown_until = now() + retry_after
        # Resets consecutive_failures to 0 (it reached the provider; not a connectivity issue)

    def record_connect_failure(self, endpoint_id: str) -> None:
        # consecutive_failures += 1
        # If consecutive_failures >= 2: set cooldown_until = now() + 20 (dead-host cooldown)

    def record_success(self, endpoint_id: str) -> None:
        # Resets consecutive_failures to 0

    def usage_pct(self, endpoint: EndpointEntry) -> float:
        # Returns 0.0–1.0 on the binding known limit (max of rpm%, rpd%)
        # Returns 0.0 if all limits are null
```

### Rolling Window Reset

- RPM window: prune timestamps older than 60 seconds on every `record_call` and `can_use`
- RPD window: prune timestamps older than 86400 seconds on every `record_call` and `can_use`
- No cron job or background task needed — lazy pruning on access is sufficient

### 90% Threshold

The threshold exists because mid-conversation rerouting after the request is sent is
costlier than rerouting before. At 90% usage, the next request that hits the wall would
cause a context-expensive partial-stream failure. Cutting over at 90% is always cheaper.

```
can_use returns False when:
  rpm_count / rpm_limit >= 0.9   (if rpm_limit is not null)
  OR
  rpd_count / rpd_limit >= 0.9   (if rpd_limit is not null)
```

---

## Resolver

Lives in `app/resolver/resolver.py`.

```python
class Resolver:

    def __init__(
        self,
        registry: Registry,
        rate_limiter: EndpointRateLimiter,
        secrets: dict[str, str],
    ):
        self._registry = registry
        self._rate_limiter = rate_limiter
        self._secrets = secrets  # endpoint_id → api_key (pre-loaded from /run/secrets/*)

    def pick(self, model_id: str) -> list[tuple[str, str, dict]]:
        """
        Returns ordered list of (base_url, provider_model_id, headers) for the given model_id.
        Filters out:
          - inactive endpoints
          - endpoints where rate_limiter.can_use() is False
        Sorts by priority (ascending).
        Raises NoEndpointError if all endpoints are unavailable.
        """
        endpoints = self._registry.endpoints_for(model_id)  # already sorted by priority
        available = [ep for ep in endpoints if ep.active and self._rate_limiter.can_use(ep)]
        if not available:
            raise NoEndpointError(f"All endpoints for '{model_id}' are rate-limited or inactive")
        result = []
        for ep in available:
            api_key = self._secrets.get(ep.secret, "")
            provider = _detect_provider_from_name(ep.provider)
            headers = _provider_headers(provider, api_key, ep.base_url)
            result.append((ep.base_url, ep.provider_model_id, headers))
        return result

    def pick_by_capability(self, level: str) -> list[tuple[str, str, dict]]:
        """
        For agent sub-task routing. Returns candidates for the first available model
        matching the requested capability_level with visibility 'internal'.
        Falls back to 'user' visibility models if no internal model is available.
        """
        ...
```

---

## normalize.py — Public Chat API

`chat_stream` is the only entry point for all LLM calls. Routes and agent nodes call
only this — never `stream_llm` directly.

```python
# app/core/normalize.py

async def chat_stream(
    model_id: str,
    messages: list[dict],
    resolver: Resolver,
    rate_limiter: EndpointRateLimiter,
    on_provider_switch: Callable[[str, str], None] | None = None,
) -> AsyncGenerator[str, None]:
    candidates = resolver.pick(model_id)
    endpoint_ids = [_url_to_endpoint_id(url, resolver) for url, _, _ in candidates]

    def handle_switch(from_url: str, to_url: str):
        from_id = _url_to_endpoint_id(from_url, resolver)
        rate_limiter.record_429(from_id)
        if on_provider_switch:
            on_provider_switch(from_url, to_url)

    async for token in stream_llm_with_fallback(candidates, messages, on_switch=handle_switch):
        # record_call on the active endpoint
        yield token
```

---

## Full Request Flow (after Phase 1.6)

```
1. Frontend fetches GET /registry/models on load
   → ModelSwitcher renders: Fast / Balanced / Research groups
   → only visibility:"user" + active:true shown

2. User selects "Llama 3.3 70B", sends a message

3. POST /chat { "model_id": "llama-3.3-70b", "conversation_id": "...", "messages": [...] }

4. chat.py
   → load conversation history from data/conversations/<id>/messages.jsonl
   → retrieve memory hits (RAG, Phase 1.5+)
   → emit memory_hit SSE events
   → call normalize.chat_stream("llama-3.3-70b", full_messages, resolver, rate_limiter, on_switch=emit_provider_switch)

5. Resolver.pick("llama-3.3-70b")
   Endpoints sorted by priority:
     ep-llama-3.3-70b-cerebras    priority:1   rpd: 13100/14400 = 91% → SKIP (≥90%)
     ep-llama-3.3-70b-huggingface priority:2   rpd: null        → OK  ← selected first
     ep-llama-3.3-70b-github      priority:3   rpd: 80/150      → OK  ← fallback 1
     ep-llama-3.3-70b-openrouter  priority:4   rpm: null        → OK  ← fallback 2
   Returns [(hf_url, hf_model, hf_headers), (gh_url, gh_model, gh_headers), (or_url, or_model, or_headers)]

6. stream_llm_with_fallback tries ep-huggingface first
   rate_limiter.record_call("ep-llama-3.3-70b-huggingface")
   stream_llm(hf_url, hf_model, messages, hf_headers) → yields tokens

7a. Happy path
    Tokens stream → frontend appends to message bubble
    SSE event: { "type": "token", "delta": "..." }
    SSE event: { "type": "done", "via_provider": "huggingface", "via_endpoint_id": "ep-llama-3.3-70b-huggingface" }
    Message bubble shows badge: "via HuggingFace"

7b. Live 429 from HuggingFace mid-stream
    rate_limiter.record_429("ep-llama-3.3-70b-huggingface", retry_after=60)
    handle_switch fires → emits: { "type": "provider_switch", "from": "huggingface", "to": "github" }
    stream_llm_with_fallback retries with ep-github
    rate_limiter.record_call("ep-llama-3.3-70b-github")
    Frontend shows inline notice: "Switched to GitHub Models (HuggingFace rate limit reached)"

8. All endpoints exhausted
   raise NoEndpointError
   → HTTP 503 with SSE: { "type": "error", "message": "All endpoints for Llama 3.3 70B are rate-limited. Try again in a few minutes or switch to a different model." }
```

---

## Invariants

- The provider layer is completely isolated. Routes and agent nodes call `normalize.chat_stream` only. They never import from `core/llm_core.py` directly.
- `ProviderError` is the cross-layer error contract. Every failure inside the provider layer raises `ProviderError(kind, message)`. The route layer catches it and emits an SSE error event.
- The user's selected brain always writes the final answer. The resolver picks the host; it never changes the model identity visible to the user.
- Partial-stream resume is not implemented. On failover, the full request is retried on the next endpoint from scratch. This is intentional — splicing partial tokens produces inconsistent answers.
