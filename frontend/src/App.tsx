import { useEffect, useRef, useState } from 'react'
import type { Message } from './types'
import ChatWindow from './components/ChatWindow'
import MessageInput from './components/MessageInput'
import { healthCheck, streamChat } from './api/client'

let nextId = 1

export default function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const streamingIdRef = useRef<string | null>(null)

  useEffect(() => {
    healthCheck()
      .then((data) => console.log('Backend:', data))
      .catch((err) => console.error('Backend unreachable:', err))
  }, [])

  async function handleSend(content: string) {
    if (isStreaming) return

    const userMsg: Message = { id: String(nextId++), role: 'user', content }
    const assistantId = String(nextId++)
    streamingIdRef.current = assistantId

    setMessages((prev) => [
      ...prev,
      userMsg,
      { id: assistantId, role: 'assistant', content: '' },
    ])
    setIsStreaming(true)

    const history = [...messages, userMsg].map((m) => ({
      role: m.role,
      content: m.content,
    }))

    await streamChat(
      history,
      (token) => {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId ? { ...m, content: m.content + token } : m,
          ),
        )
      },
      () => {
        setIsStreaming(false)
        streamingIdRef.current = null
      },
      (err) => {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? { ...m, content: `Error: ${err}` }
              : m,
          ),
        )
        setIsStreaming(false)
        streamingIdRef.current = null
      },
    )
  }

  return (
    <div className="flex flex-col h-screen bg-white">
      <header className="border-b border-zinc-200 px-4 py-3 shrink-0">
        <h1 className="text-sm font-semibold text-zinc-800">PAWN</h1>
      </header>
      <ChatWindow messages={messages} />
      <MessageInput onSend={handleSend} disabled={isStreaming} />
    </div>
  )
}
