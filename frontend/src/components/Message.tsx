import type { Message } from '../types'
import TracePanel from './TracePanel'

interface Props {
  message: Message
  isStreaming: boolean
}

export default function MessageBubble({ message, isStreaming }: Props) {
  const isUser = message.role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-3`}>
      <div className="flex flex-col max-w-[75%]">
        <div
          className={`rounded-2xl px-4 py-2 text-sm leading-relaxed whitespace-pre-wrap ${
            isUser
              ? 'bg-zinc-800 text-white self-end'
              : 'bg-zinc-100 text-zinc-900 self-start'
          }`}
        >
          {message.content}
        </div>
        {!isUser && message.trace && message.trace.length > 0 && (
          <TracePanel trace={message.trace} isStreaming={isStreaming} />
        )}
      </div>
    </div>
  )
}

