// Fallback to localhost for local dev without a .env file
const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

function getToken(): string | null {
  return localStorage.getItem('pawn-token')
}

function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function healthCheck(): Promise<{ status: string }> {
  const res = await fetch(`${BASE_URL}/health`)
  if (!res.ok) throw new Error(`Health check failed: ${res.status}`)
  return res.json()
}

/**
 * Milestone A.0 — Kaggle round-trip proof. Sends an integer to the backend,
 * which runs the `findCube` kernel on the user's Kaggle account and returns the
 * cube. Proves the deploy→push→poll→output transport before any image model.
 * Throws on failure (caller renders the message verbatim).
 */
export interface CubeResult {
  input: number
  result: number
  via?: string
}

/** Status of the user's Kaggle config — shape only, never the token. */
export interface KaggleConfigStatus {
  has_creds: boolean
  kernels?: Record<string, boolean>
}

function handle401(res: Response): boolean {
  if (res.status === 401) {
    localStorage.removeItem('pawn-token')
    localStorage.removeItem('pawn-user')
    window.location.reload()
    return true
  }
  return false
}

async function errorDetail(res: Response): Promise<string> {
  let detail = `Request failed: ${res.status}`
  try {
    const body = await res.json()
    if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
  } catch {
    /* non-JSON error body — keep the status message */
  }
  return detail
}

/** Read whether the user has Kaggle creds saved (no secret values returned). */
export async function getKaggleConfig(): Promise<KaggleConfigStatus> {
  const res = await fetch(`${BASE_URL}/keys/kaggle`, { headers: { ...authHeaders() } })
  if (handle401(res)) throw new Error('Session expired')
  if (res.status === 404) return { has_creds: false }
  if (!res.ok) throw new Error(await errorDetail(res))
  return res.json()
}

/** Save the user's Kaggle username + API token (token is write-only). */
export async function setKaggleConfig(cfg: { username: string; api_token: string }): Promise<void> {
  const res = await fetch(`${BASE_URL}/keys/kaggle`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(cfg),
  })
  if (handle401(res)) throw new Error('Session expired')
  if (!res.ok) throw new Error(await errorDetail(res))
}

/** Remove the user's Kaggle creds. */
export async function deleteKaggleConfig(): Promise<void> {
  const res = await fetch(`${BASE_URL}/keys/kaggle`, { method: 'DELETE', headers: { ...authHeaders() } })
  if (handle401(res)) throw new Error('Session expired')
  if (!res.ok && res.status !== 404) throw new Error(await errorDetail(res))
}

export interface ImageResult {
  image: string // base64
  mime: string
  via?: string
}

export async function connectKaggle(model = 'sdxl'): Promise<void> {
  const res = await fetch(`${BASE_URL}/generate/connect`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ model }),
  })
  if (handle401(res)) throw new Error('Session expired')
  if (!res.ok) throw new Error(await errorDetail(res))
}

export async function runKaggleImage(
  prompt: string,
  model = 'sdxl',
  signal?: AbortSignal,
): Promise<ImageResult> {
  const res = await fetch(`${BASE_URL}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ prompt, modality: 'image', model }),
    signal,
  })

  if (res.status === 401) {
    localStorage.removeItem('pawn-token')
    localStorage.removeItem('pawn-user')
    window.location.reload()
    throw new Error('Session expired')
  }

  if (!res.ok) {
    let detail = `Request failed: ${res.status}`
    try {
      const body = await res.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail)
  }

  return res.json()
}

// --- Warm sessions + durable jobs (Phase W) ---------------------------------
// W.0 proves the persistent Kaggle loop via a CPU echo kernel: start a session,
// submit a job, poll the job row for the echoed result, stop.

export interface SessionStatus {
  status: string // none | starting | ready | stopping | ended | error
  alive: boolean
  session_id?: string
  expires_at?: string | null
  images_done?: number
  max_images?: number | null
}

export interface JobResult {
  job_id: string
  status: string // queued | running | done | error
  model?: string
  prompt?: string
  image_b64?: string | null
  mime?: string | null
  via?: string | null
  error?: string | null
  created_at?: string | null
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  })
  if (handle401(res)) throw new Error('Session expired')
  if (!res.ok) throw new Error(await errorDetail(res))
  return res.json()
}

export async function startSession(
  model: string,
  durationMinutes: number,
  maxImages?: number | null,
): Promise<{ session_id: string; expires_at: string; status: string }> {
  return postJson('/generate/session/start', {
    model,
    duration_minutes: durationMinutes,
    max_images: maxImages ?? null,
  })
}

export async function getSessionStatus(model: string): Promise<SessionStatus> {
  const res = await fetch(
    `${BASE_URL}/generate/session/status?model=${encodeURIComponent(model)}`,
    { headers: { ...authHeaders() } },
  )
  if (handle401(res)) throw new Error('Session expired')
  if (!res.ok) throw new Error(await errorDetail(res))
  return res.json()
}

export async function submitSessionJob(
  sessionId: string,
  prompt: string,
): Promise<{ job_id: string; status: string }> {
  return postJson('/generate/session/job', { session_id: sessionId, prompt })
}

export async function stopSession(sessionId: string): Promise<void> {
  await postJson('/generate/session/stop', { session_id: sessionId })
}

export async function getJob(jobId: string): Promise<JobResult> {
  const res = await fetch(`${BASE_URL}/generate/job/${encodeURIComponent(jobId)}`, {
    headers: { ...authHeaders() },
  })
  if (handle401(res)) throw new Error('Session expired')
  if (!res.ok) throw new Error(await errorDetail(res))
  return res.json()
}

export async function runKaggleCube(input: number, signal?: AbortSignal): Promise<CubeResult> {
  const res = await fetch(`${BASE_URL}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ input, modality: 'cube' }),
    signal,
  })

  if (res.status === 401) {
    localStorage.removeItem('pawn-token')
    localStorage.removeItem('pawn-user')
    window.location.reload()
    throw new Error('Session expired')
  }

  if (!res.ok) {
    let detail = `Request failed: ${res.status}`
    try {
      const body = await res.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* non-JSON error body — keep the status message */
    }
    throw new Error(detail)
  }

  return res.json()
}

/**
 * Typed SSE event callbacks.
 */
export interface StreamChatCallbacks {
  onToken: (delta: string) => void
  onDone: (viaProvider: string) => void
  onError: (message: string) => void
  onRateLimit?: (retryAfterSeconds: number) => void
  onStep?: (label: string, detail: string) => void
  onMemoryHit?: (summary: string) => void
  onModelCall?: (model: string, purpose: string) => void
  onProviderSwitch?: (from: string, to: string) => void
}

export async function streamChat(
  messages: Array<{ role: string; content: string }>,
  callbacks: StreamChatCallbacks,
  modelId?: string,
  docId?: string,
  conversationId?: string,
  signal?: AbortSignal,
): Promise<void> {
  const { onToken, onDone, onError, onRateLimit, onStep, onMemoryHit, onModelCall, onProviderSwitch } =
    callbacks

  let res: Response
  try {
    res = await fetch(`${BASE_URL}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({
        messages,
        ...(modelId ? { model_id: modelId } : {}),
        ...(docId ? { doc_id: docId } : {}),
        ...(conversationId ? { conversation_id: conversationId } : {}),
      }),
      signal,
    })
  } catch (err) {
    // User aborted before/while connecting — stop silently.
    if (err instanceof DOMException && err.name === 'AbortError') return
    onError(err instanceof Error ? err.message : 'Request failed')
    return
  }

  if (res.status === 401) {
    // Token expired or missing — trigger re-login
    localStorage.removeItem('pawn-token')
    localStorage.removeItem('pawn-user')
    window.location.reload()
    return
  }

  if (!res.ok) {
    onError(`Request failed: ${res.status}`)
    return
  }

  const reader = res.body?.getReader()
  if (!reader) {
    onError('No response body')
    return
  }

  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      if (signal?.aborted) return

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const raw = line.slice(6).trim()
        if (!raw) continue

        let event: Record<string, string | number>
        try {
          event = JSON.parse(raw)
        } catch {
          continue
        }

        switch (event.type) {
          case 'token':
            onToken(String(event.delta ?? ''))
            break
          case 'done':
            onDone(String(event.via_provider ?? ''))
            return
          case 'error':
            if (event.code === 'rate_limit' && onRateLimit) {
              onRateLimit(Number(event.retry_after ?? 60))
              return
            }
            onError(String(event.message ?? 'Unknown error'))
            return
          case 'step':
            onStep?.(String(event.label ?? ''), String(event.detail ?? ''))
            break
          case 'memory_hit':
            onMemoryHit?.(String(event.summary ?? ''))
            break
          case 'model_call':
            onModelCall?.(String(event.model ?? ''), String(event.purpose ?? ''))
            break
          case 'provider_switch':
            onProviderSwitch?.(String(event.from ?? ''), String(event.to ?? ''))
            break
          default:
            break
        }
      }
    }
  } catch (err) {
    // Aborted mid-stream — stop silently without surfacing an error.
    if (err instanceof DOMException && err.name === 'AbortError') return
    onError(err instanceof Error ? err.message : 'Stream interrupted')
    return
  } finally {
    reader.releaseLock()
  }

  onDone('')
}

export async function uploadDoc(file: File): Promise<string> {
  const formData = new FormData()
  formData.append('file', file)

  const res = await fetch(`${BASE_URL}/upload`, {
    method: 'POST',
    headers: { ...authHeaders() },
    body: formData,
  })

  if (!res.ok) {
    let errorDetail = 'Upload failed'
    try {
      const data = await res.json()
      if (data.detail) errorDetail = data.detail
    } catch { /* ignore */ }
    throw new Error(errorDetail)
  }

  const data = await res.json()
  return data.doc_id
}

export interface ConversationMeta {
  id: string
  title: string
  created_at: string
  updated_at: string
  model_id: string
  message_count: number
}

export interface ConversationDetail {
  meta: ConversationMeta
  messages: Array<{ role: string; content: string }>
}

export async function fetchConversations(): Promise<ConversationMeta[]> {
  const res = await fetch(`${BASE_URL}/conversations`, { headers: authHeaders() })
  if (!res.ok) throw new Error('Failed to fetch conversations')
  return res.json()
}

export async function createConversation(title?: string, modelId?: string, id?: string): Promise<ConversationMeta> {
  const res = await fetch(`${BASE_URL}/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({
      ...(id ? { id } : {}),
      ...(title ? { title } : {}),
      ...(modelId ? { model_id: modelId } : {}),
    }),
  })
  if (!res.ok) throw new Error('Failed to create conversation')
  return res.json()
}

export async function fetchConversation(convId: string): Promise<ConversationDetail> {
  const res = await fetch(`${BASE_URL}/conversations/${convId}`, { headers: authHeaders() })
  if (!res.ok) throw new Error(`Failed to fetch conversation: ${convId}`)
  return res.json()
}

export async function deleteConversation(convId: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/conversations/${convId}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  // DELETE is idempotent: a 404 means it's already gone — treat as success.
  if (res.status === 404) return
  if (!res.ok) throw new Error(`Failed to delete conversation: ${convId}`)
}

export async function updateConversationTitle(convId: string, title: string): Promise<ConversationMeta> {
  const res = await fetch(`${BASE_URL}/conversations/${convId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ title }),
  })
  if (!res.ok) throw new Error(`Failed to update conversation title: ${convId}`)
  return res.json()
}

export interface RegistryModel {
  model_id: string
  display_name: string
  capability_level?: 'fast' | 'balanced' | 'research' | string
  capability_tags: string[]
  context_window: number
  endpoint_count: number
  providers: string[]
}

export async function fetchRegistryModels(): Promise<RegistryModel[]> {
  const res = await fetch(`${BASE_URL}/registry/models`, { headers: authHeaders() })
  if (!res.ok) throw new Error('Failed to fetch registry models')
  return res.json()
}

// BYOK key management
export async function getKeys(): Promise<string[]> {
  const res = await fetch(`${BASE_URL}/keys`, { headers: authHeaders() })
  if (!res.ok) throw new Error('Failed to fetch keys')
  const data = await res.json()
  return data.providers ?? []
}

export async function setKey(provider: string, apiKey: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/keys/${provider}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ api_key: apiKey }),
  })
  if (!res.ok) throw new Error(`Failed to set key for ${provider}`)
}

export async function deleteKey(provider: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/keys/${provider}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  if (!res.ok) throw new Error(`Failed to delete key for ${provider}`)
}
