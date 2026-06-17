import { useEffect, useRef } from 'react'
import type { Message } from '../types'
import MessageBubble from './Message'

interface Props {
  messages: Message[]
  isStreaming: boolean
}

export default function ChatWindow({ messages, isStreaming }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  return (
    <div className="flex-1 overflow-y-auto px-4 py-4">
      {messages.length === 0 && (
        <p className="text-center text-zinc-400 text-sm mt-8">
          Start a conversation
        </p>
      )}
      {messages.map((msg, index) => {
        const isLast = index === messages.length - 1
        return (
          <MessageBubble
            key={msg.id}
            message={msg}
            isStreaming={isLast && isStreaming}
          />
        )
      })}
      <div ref={bottomRef} />
    </div>
  )
}

