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
): Promise<void> {
  const { onToken, onDone, onError, onRateLimit, onStep, onMemoryHit, onModelCall, onProviderSwitch } =
    callbacks

  const res = await fetch(`${BASE_URL}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({
      messages,
      ...(modelId ? { model_id: modelId } : {}),
      ...(docId ? { doc_id: docId } : {}),
      ...(conversationId ? { conversation_id: conversationId } : {}),
    }),
  })

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

export async function createConversation(title?: string, modelId?: string): Promise<ConversationMeta> {
  const res = await fetch(`${BASE_URL}/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({
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
  return res.json()
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
