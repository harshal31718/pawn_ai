export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
}

export interface ChatState {
  messages: Message[]
  isStreaming: boolean
}
