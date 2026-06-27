// Fallback to localhost for local dev without a .env file
const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export async function healthCheck(): Promise<{ status: string }> {
  const res = await fetch(`${BASE_URL}/health`)
  if (!res.ok) throw new Error(`Health check failed: ${res.status}`)
  return res.json()
}

/**
 * Typed SSE event callbacks.
 * All are optional — wired progressively as each step lands.
 */
export interface StreamChatCallbacks {
  onToken: (delta: string) => void
  onDone: (viaProvider: string) => void
  onError: (message: string) => void
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
  const { onToken, onDone, onError, onStep, onMemoryHit, onModelCall, onProviderSwitch } =
    callbacks

  const res = await fetch(`${BASE_URL}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      messages,
      ...(modelId ? { model_id: modelId } : {}),
      ...(docId ? { doc_id: docId } : {}),
      ...(conversationId ? { conversation_id: conversationId } : {}),
    }),
  })

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

        // Parse the typed JSON event
        let event: Record<string, string>
        try {
          event = JSON.parse(raw)
        } catch {
          // Not JSON — ignore (should not happen with typed events)
          continue
        }

        switch (event.type) {
          case 'token':
            onToken(event.delta ?? '')
            break
          case 'done':
            onDone(event.via_provider ?? '')
            return
          case 'error':
            onError(event.message ?? 'Unknown error')
            return
          case 'step':
            onStep?.(event.label ?? '', event.detail ?? '')
            break
          case 'memory_hit':
            onMemoryHit?.(event.summary ?? '')
            break
          case 'model_call':
            onModelCall?.(event.model ?? '', event.purpose ?? '')
            break
          case 'provider_switch':
            onProviderSwitch?.(event.from ?? '', event.to ?? '')
            break
          default:
            // Unknown event type — ignore silently
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
    body: formData,
  })

  if (!res.ok) {
    let errorDetail = 'Upload failed'
    try {
      const data = await res.json()
      if (data.detail) errorDetail = data.detail
    } catch {
      // ignore JSON parse error
    }
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
  const res = await fetch(`${BASE_URL}/conversations`)
  if (!res.ok) throw new Error('Failed to fetch conversations')
  return res.json()
}

export async function createConversation(title?: string, modelId?: string): Promise<ConversationMeta> {
  const res = await fetch(`${BASE_URL}/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      ...(title ? { title } : {}),
      ...(modelId ? { model_id: modelId } : {}),
    }),
  })
  if (!res.ok) throw new Error('Failed to create conversation')
  return res.json()
}

export async function fetchConversation(convId: string): Promise<ConversationDetail> {
  const res = await fetch(`${BASE_URL}/conversations/${convId}`)
  if (!res.ok) throw new Error(`Failed to fetch conversation: ${convId}`)
  return res.json()
}

export async function deleteConversation(convId: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/conversations/${convId}`, {
    method: 'DELETE',
  })
  if (!res.ok) throw new Error(`Failed to delete conversation: ${convId}`)
}

export async function updateConversationTitle(convId: string, title: string): Promise<ConversationMeta> {
  const res = await fetch(`${BASE_URL}/conversations/${convId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
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
}

export async function fetchRegistryModels(): Promise<RegistryModel[]> {
  const res = await fetch(`${BASE_URL}/registry/models`)
  if (!res.ok) throw new Error('Failed to fetch registry models')
  return res.json()
}


