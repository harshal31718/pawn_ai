# SSE Protocol
## Typed Event Reference

---

## Wire Format

Every SSE event is a single line:
```
data: <JSON object>\n\n
```

The JSON object always has a `type` field. Additional fields depend on the type.
Events are emitted in sequence over a single `text/event-stream` response.

---

## Event Types

### token
Emitted for each text token as it streams from the provider.

```json
{ "type": "token", "delta": "Hello" }
```

| Field | Type | Notes |
|---|---|---|
| `delta` | string | One or more tokens of text to append to the current message bubble |

---

### done
Emitted once when the stream completes successfully.

```json
{ "type": "done", "via_provider": "cerebras", "via_endpoint_id": "ep-llama-3.3-70b-cerebras" }
```

| Field | Type | Notes |
|---|---|---|
| `via_provider` | string | Provider that served this response. Displayed as a badge on the message bubble. |
| `via_endpoint_id` | string | Specific endpoint ID. Used for debugging and rate-limit tracking. |

---

### error
Emitted when the stream fails unrecoverably (all endpoints exhausted, auth error, etc.).

```json
{ "type": "error", "message": "All endpoints for Llama 3.3 70B are rate-limited. Try again in a few minutes or switch to a different model." }
```

| Field | Type | Notes |
|---|---|---|
| `message` | string | User-readable error message. Should be actionable. |

---

### provider_switch
Emitted when a failover occurs mid-conversation (one endpoint failed, next is being tried).
Introduced in Phase 1.6.

```json
{ "type": "provider_switch", "from": "huggingface", "to": "github", "reason": "rate_limit" }
```

| Field | Type | Notes |
|---|---|---|
| `from` | string | Provider name that was tried and failed |
| `to` | string | Provider name being tried next |
| `reason` | string | `"rate_limit"` \| `"connect_error"` \| `"timeout"` \| `"upstream_error"` |

**Frontend behaviour:** insert a dismissable inline notice between messages:
`"Switched to GitHub Models (HuggingFace rate limit reached)"`

---

### step
Emitted by agent nodes as they execute. Used to populate the trace panel.
Introduced in Phase 1.5 (Step 13).

```json
{ "type": "step", "label": "Searching memory", "detail": "query: project preferences" }
```

| Field | Type | Notes |
|---|---|---|
| `label` | string | Short description of the step. Shown as the primary text in the trace row. |
| `detail` | string | Optional additional context. Shown smaller below the label. |

Common labels:
- `"Thinking"` — agent_node deciding next action
- `"Searching memory"` — search_memory_node
- `"Drafting"` — ask_model_node with purpose=draft
- `"Critiquing"` — ask_model_node with purpose=critique
- `"Composing final answer"` — final_node before streaming

---

### memory_hit
Emitted for each memory chunk retrieved from the index that is injected as context.
Introduced in Phase 1.5 (Step 15).

```json
{ "type": "memory_hit", "summary": "From chat '2026-06-07': user prefers concise, bullet-point answers" }
```

| Field | Type | Notes |
|---|---|---|
| `summary` | string | The retrieved memory chunk text (or a truncated preview) |

**Frontend behaviour:** render as a faded row in the trace panel:
`"↩ From 2026-06-07: user prefers concise, bullet-point answers"`

---

### model_call
Emitted when a sub-task model is invoked inside the agent (draft, critique, research).
Introduced in Phase 1.5 (Step 16).

```json
{ "type": "model_call", "model": "gemini-flash-live", "purpose": "draft" }
```

| Field | Type | Notes |
|---|---|---|
| `model` | string | Canonical model ID or capability level being used |
| `purpose` | string | `"draft"` \| `"critique"` \| `"research"` \| `"plan"` |

**Frontend behaviour:** render as a row in the trace panel with a badge:
`"⚡ Drafting [balanced]"`

---

## Emit Order for a Typical Agentic Request

```
step         { label: "Thinking", detail: "step 1" }
memory_hit   { summary: "user prefers concise answers" }
step         { label: "Drafting", detail: "draft" }
model_call   { model: "gemini-flash-live", purpose: "draft" }
token        { delta: "Here is " }
token        { delta: "a draft..." }
...
step         { label: "Critiquing", detail: "critique" }
model_call   { model: "llama-3.3-70b", purpose: "critique" }
token        { delta: "The draft is " }
...
step         { label: "Composing final answer", detail: "" }
token        { delta: "Based on the research " }
token        { delta: "..." }
...
done         { via_provider: "cerebras", via_endpoint_id: "ep-llama-3.3-70b-cerebras" }
```

---

## Emit Order for a Simple (Non-Agentic) Request

```
token        { delta: "Hello" }
token        { delta: ", how can" }
token        { delta: " I help?" }
done         { via_provider: "huggingface", via_endpoint_id: "ep-llama-3.3-70b-huggingface" }
```

---

## Emit Order When Failover Occurs

```
token            { delta: "Let me" }
provider_switch  { from: "huggingface", to: "github", reason: "rate_limit" }
token            { delta: "Let me" }        ← stream restarts from scratch on new endpoint
token            { delta: " explain..." }
done             { via_provider: "github", via_endpoint_id: "ep-llama-3.3-70b-github" }
```

Note: the stream restarts from the beginning on the new endpoint. There is no partial-stream
splicing. The notice `"Switched to GitHub Models"` appears as a UI element, not as a message
in the conversation history.

---

## Backend Builder Functions

`backend/app/events.py`:
```python
import json

def token_event(delta: str) -> str:
    return f"data: {json.dumps({'type': 'token', 'delta': delta})}\n\n"

def done_event(via_provider: str = "", via_endpoint_id: str = "") -> str:
    return f"data: {json.dumps({'type': 'done', 'via_provider': via_provider, 'via_endpoint_id': via_endpoint_id})}\n\n"

def error_event(message: str) -> str:
    return f"data: {json.dumps({'type': 'error', 'message': message})}\n\n"

def provider_switch_event(from_provider: str, to_provider: str, reason: str = "rate_limit") -> str:
    return f"data: {json.dumps({'type': 'provider_switch', 'from': from_provider, 'to': to_provider, 'reason': reason})}\n\n"

def step_event(label: str, detail: str = "") -> str:
    return f"data: {json.dumps({'type': 'step', 'label': label, 'detail': detail})}\n\n"

def memory_hit_event(summary: str) -> str:
    return f"data: {json.dumps({'type': 'memory_hit', 'summary': summary})}\n\n"

def model_call_event(model: str, purpose: str) -> str:
    return f"data: {json.dumps({'type': 'model_call', 'model': model, 'purpose': purpose})}\n\n"
```

---

## Frontend Dispatch

`frontend/src/api/client.ts`:
```typescript
export interface StreamCallbacks {
  onToken: (delta: string) => void;
  onDone: (viaProvider: string, viaEndpointId: string) => void;
  onError: (message: string) => void;
  onProviderSwitch: (from: string, to: string, reason: string) => void;
  onStep: (label: string, detail: string) => void;
  onMemoryHit: (summary: string) => void;
  onModelCall: (model: string, purpose: string) => void;
}

export async function streamChat(
  payload: ChatRequest,
  callbacks: StreamCallbacks,
): Promise<void> {
  const res = await fetch(`${BASE_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const lines = decoder.decode(value).split("\n");
    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const raw = line.slice(6).trim();
      if (!raw || raw === "[DONE]") continue;
      const event = JSON.parse(raw);
      switch (event.type) {
        case "token":          callbacks.onToken(event.delta); break;
        case "done":           callbacks.onDone(event.via_provider, event.via_endpoint_id); break;
        case "error":          callbacks.onError(event.message); break;
        case "provider_switch": callbacks.onProviderSwitch(event.from, event.to, event.reason); break;
        case "step":           callbacks.onStep(event.label, event.detail); break;
        case "memory_hit":     callbacks.onMemoryHit(event.summary); break;
        case "model_call":     callbacks.onModelCall(event.model, event.purpose); break;
      }
    }
  }
}
```

---

## Invariants

- Every stream ends with either `done` or `error`. Never both. Never neither.
- `token` events only appear between the first event and `done`/`error`.
- `provider_switch` can appear anywhere before `done`. The stream restarts after it.
- `step`, `memory_hit`, and `model_call` appear only in agentic requests. Simple chat requests
  emit `token` + `done` only.
- The frontend must handle events arriving out of order or in partial chunks (TCP fragmentation).
  The dispatch loop buffers incomplete lines across `read()` calls.
