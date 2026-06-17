import type { Message } from '../types'
import TracePanel from './TracePanel'

interface Props {
  message: Message
  isStreaming: boolean
}

const formatProviderName = (p: string) => {
  if (!p) return ''
  if (p === 'huggingface') return 'HuggingFace'
  if (p === 'openrouter') return 'OpenRouter'
  if (p === 'github') return 'GitHub'
  return p.charAt(0).toUpperCase() + p.slice(1)
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
        {!isUser && message.viaProvider && (
          <div className="text-[10px] text-zinc-400 mt-1 ml-2 self-start font-medium tracking-wider select-none animate-in fade-in duration-200">
            via {formatProviderName(message.viaProvider)}
          </div>
        )}
        {!isUser && message.trace && message.trace.length > 0 && (
          <TracePanel trace={message.trace} isStreaming={isStreaming} />
        )}
      </div>
    </div>
  )
}

