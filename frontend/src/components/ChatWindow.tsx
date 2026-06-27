import { useEffect, useRef } from 'react'
import type { Message } from '../types'
import MessageBubble from './Message'

interface Props {
  messages: Message[]
  isStreaming: boolean
}

export default function ChatWindow({ messages, isStreaming }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const lastUserMsgIdRef = useRef<string | null>(null)
  const reachedTopRef = useRef<boolean>(false)

  useEffect(() => {
    // Find the last user message
    const userMessages = messages.filter((m) => m.role === 'user')
    if (userMessages.length === 0) return

    const lastUserMsg = userMessages[userMessages.length - 1]

    // Reset tracking if it's a new user message thread
    if (lastUserMsgIdRef.current !== lastUserMsg.id) {
      lastUserMsgIdRef.current = lastUserMsg.id
      reachedTopRef.current = false
    }

    // Stop auto-scrolling if the message has already aligned at the top
    if (reachedTopRef.current) return

    const container = containerRef.current
    if (!container) return

    // Evaluate position after layout paint
    setTimeout(() => {
      const element = document.getElementById(`msg-${lastUserMsg.id}`)
      if (!element) return

      const containerRect = container.getBoundingClientRect()
      const elementRect = element.getBoundingClientRect()
      const relativeTop = elementRect.top - containerRect.top

      // If the message is still below the top boundary, keep scrolling it up
      if (relativeTop > 5) {
        element.scrollIntoView({ behavior: 'auto', block: 'start' })
      } else {
        // Once aligned at the top (or passed it), freeze scroll updates
        reachedTopRef.current = true
      }
    }, 30)
  }, [messages])

  return (
    <div ref={containerRef} className="flex-1 overflow-y-auto px-4 pt-20 pb-48">
      {messages.length === 0 && null}
      {messages.map((msg, index) => {
        const isLast = index === messages.length - 1
        return (
          <div key={msg.id} id={`msg-${msg.id}`}>
            <MessageBubble
              message={msg}
              isStreaming={isLast && isStreaming}
            />
          </div>
        )
      })}
    </div>
  )
}

