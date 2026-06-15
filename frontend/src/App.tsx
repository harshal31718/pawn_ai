import { useState } from 'react'
import type { Message } from './types'
import ChatWindow from './components/ChatWindow'
import MessageInput from './components/MessageInput'

let nextId = 1

export default function App() {
  const [messages, setMessages] = useState<Message[]>([])

  function handleSend(content: string) {
    const userMsg: Message = { id: String(nextId++), role: 'user', content }
    setMessages((prev) => [...prev, userMsg])
  }

  return (
    <div className="flex flex-col h-screen bg-white">
      <header className="border-b border-zinc-200 px-4 py-3 shrink-0">
        <h1 className="text-sm font-semibold text-zinc-800">PAWN</h1>
      </header>
      <ChatWindow messages={messages} />
      <MessageInput onSend={handleSend} />
    </div>
  )
}
