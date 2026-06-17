export interface TraceEvent {
  type: 'step' | 'memory_hit' | 'model_call' | 'provider_switch'
  label?: string
  detail?: string
  summary?: string
  model?: string
  purpose?: string
  from?: string
  to?: string
  timestamp: string
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  trace?: TraceEvent[]
}

export interface ChatState {
  messages: Message[]
  isStreaming: boolean
}

