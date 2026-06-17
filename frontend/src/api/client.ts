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
  provider?: string,
  docId?: string,
): Promise<void> {
  const { onToken, onDone, onError, onStep, onMemoryHit, onModelCall, onProviderSwitch } =
    callbacks

  const res = await fetch(`${BASE_URL}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      messages,
      ...(provider ? { provider } : {}),
      ...(docId ? { doc_id: docId } : {}),
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

