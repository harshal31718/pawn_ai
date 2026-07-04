// Fallback to localhost for local dev without a .env file
export const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

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
 * Whether the current user's Google Drive is linked AND usable. The backend
 * makes a real (cheap) Drive call, so this returns false for a login that never
 * granted the drive.file scope — not just when no token exists.
 */
export async function getDriveStatus(): Promise<{ connected: boolean }> {
  const res = await fetch(`${BASE_URL}/auth/drive/status`, { headers: { ...authHeaders() } })
  if (handle401(res)) throw new Error('unauthorized')
  if (!res.ok) throw new Error(`Drive status failed: ${res.status}`)
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

export interface ImageParams {
  width?: number
  height?: number
  num_inference_steps?: number
  guidance_scale?: number
  negative_prompt?: string
  style_preset?: string
  strength?: number
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

export const IMAGE_JOB_POLL_INTERVAL_MS = 3000

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const t = setTimeout(resolve, ms)
    signal?.addEventListener(
      'abort',
      () => {
        clearTimeout(t)
        reject(new DOMException('Aborted', 'AbortError'))
      },
      { once: true },
    )
  })
}

/** Submit an image generation. Non-blocking: returns the durable job id; the
 *  slow Kaggle round-trip runs as a backend worker. (W.1 contract change.) */
export async function runGenerate(
  model: string,
  prompt: string,
  params?: ImageParams,
  initImageB64?: string,
  initJobId?: string,
): Promise<{ job_id: string; status: string }> {
  return postJson('/generate', {
    modality: 'image',
    prompt,
    model,
    ...(params && Object.keys(params).length > 0 ? { params } : {}),
    ...(initJobId ? { init_job_id: initJobId } : initImageB64 ? { init_image_b64: initImageB64 } : {}),
  })
}

/** Cold Generate: submit a job, then poll it to completion. Preserves the Lab's
 *  existing Generate flow on top of the new durable-job backend. Throws
 *  AbortError if `signal` aborts (the full re-attach/monitor UI lands in W.2). */
export async function runKaggleImage(
  prompt: string,
  model = 'sdxl',
  signal?: AbortSignal,
): Promise<ImageResult> {
  const { job_id } = await runGenerate(model, prompt)
  for (;;) {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    const job = await getJob(job_id)
    if (job.status === 'done') {
      return { image: job.image_b64 ?? '', mime: job.mime ?? 'image/png', via: job.via ?? undefined }
    }
    if (job.status === 'error') throw new Error(job.error || 'Generation failed')
    await sleep(IMAGE_JOB_POLL_INTERVAL_MS, signal)
  }
}

// --- Warm sessions + durable jobs (Phase W) ---------------------------------
// W.0 proves the persistent Kaggle loop via a CPU echo kernel: start a session,
// submit a job, poll the job row for the echoed result, stop.

export interface SessionStatus {
  status: string // none | starting | installing | loading_model | ready | stopping | ended | error
  alive: boolean
  session_id?: string
  expires_at?: string | null
  images_done?: number
  max_images?: number | null
}

export interface JobResult {
  job_id: string
  status: string // queued | running | done | error
  session_id?: string | null
  model?: string
  prompt?: string
  image_b64?: string | null
  mime?: string | null
  via?: string | null
  error?: string | null
  params?: Record<string, unknown> | null
  created_at?: string | null
  started_at?: string | null
  done_at?: string | null
  has_image?: boolean // present in list_jobs summaries (image bytes fetched via getJob)
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
  params?: ImageParams,
  initImageB64?: string,
  initJobId?: string,
): Promise<{ job_id: string; status: string }> {
  return postJson('/generate/session/job', {
    session_id: sessionId,
    prompt,
    ...(params && Object.keys(params).length > 0 ? { params } : {}),
    ...(initJobId ? { init_job_id: initJobId } : initImageB64 ? { init_image_b64: initImageB64 } : {}),
  })
}

export async function stopSession(sessionId: string): Promise<void> {
  await postJson('/generate/session/stop', { session_id: sessionId })
}

export async function extendSession(
  sessionId: string,
  addMinutes = 30,
): Promise<{ session_id: string; expires_at: string }> {
  return postJson('/generate/session/extend', { session_id: sessionId, add_minutes: addMinutes })
}

/** Job summaries for the monitor panel (newest first, no image bytes). */
export async function listJobs(model?: string, limit = 20): Promise<JobResult[]> {
  const params = new URLSearchParams()
  if (model) params.set('model', model)
  params.set('limit', String(limit))
  const res = await fetch(`${BASE_URL}/generate/jobs?${params.toString()}`, {
    headers: { ...authHeaders() },
  })
  if (handle401(res)) throw new Error('Session expired')
  if (!res.ok) throw new Error(await errorDetail(res))
  return res.json()
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

  if (handle401(res)) throw new Error('Session expired')
  if (!res.ok) throw new Error(await errorDetail(res))
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

  if (handle401(res)) return

  if (!res.ok) {
    onError(await errorDetail(res))
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
  if (handle401(res)) throw new Error('Session expired')
  if (!res.ok) throw new Error(await errorDetail(res))
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
  if (handle401(res)) throw new Error('Session expired')
  if (!res.ok) throw new Error(await errorDetail(res))
  return res.json()
}

export async function fetchConversation(convId: string): Promise<ConversationDetail> {
  const res = await fetch(`${BASE_URL}/conversations/${convId}`, { headers: authHeaders() })
  if (handle401(res)) throw new Error('Session expired')
  if (!res.ok) throw new Error(await errorDetail(res))
  return res.json()
}

export async function deleteConversation(convId: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/conversations/${convId}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  if (handle401(res)) throw new Error('Session expired')
  // DELETE is idempotent: a 404 means it's already gone — treat as success.
  if (res.status === 404) return
  if (!res.ok) throw new Error(await errorDetail(res))
}

export async function updateConversationTitle(convId: string, title: string): Promise<ConversationMeta> {
  const res = await fetch(`${BASE_URL}/conversations/${convId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ title }),
  })
  if (handle401(res)) throw new Error('Session expired')
  if (!res.ok) throw new Error(await errorDetail(res))
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
  if (handle401(res)) throw new Error('Session expired')
  if (!res.ok) throw new Error(await errorDetail(res))
  return res.json()
}

// BYOK key management
export async function getKeys(): Promise<string[]> {
  const res = await fetch(`${BASE_URL}/keys`, { headers: authHeaders() })
  if (handle401(res)) throw new Error('Session expired')
  if (!res.ok) throw new Error(await errorDetail(res))
  const data = await res.json()
  return data.providers ?? []
}

export async function setKey(provider: string, apiKey: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/keys/${provider}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ api_key: apiKey }),
  })
  if (handle401(res)) throw new Error('Session expired')
  if (!res.ok) throw new Error(await errorDetail(res))
}

export async function deleteKey(provider: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/keys/${provider}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  if (handle401(res)) throw new Error('Session expired')
  if (!res.ok) throw new Error(await errorDetail(res))
}

// --- Encryption salt --------------------------------------------------------
// The (non-secret) PBKDF2 salt used to derive the browser-side encryption key.
// Created server-side on first request; stable per user thereafter.
export async function fetchSalt(): Promise<Uint8Array> {
  const res = await fetch(`${BASE_URL}/crypto/salt`, { headers: authHeaders() })
  if (handle401(res)) throw new Error('Session expired')
  if (!res.ok) throw new Error(await errorDetail(res))
  const { salt } = (await res.json()) as { salt: string }
  const binary = atob(salt)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
  return bytes
}
