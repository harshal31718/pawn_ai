import { useState, useRef, useLayoutEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import type { Message } from '../types'

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
  const [isExpanded, setIsExpanded] = useState(false)
  const [isLong, setIsLong] = useState(false)
  const [isTraceOpen, setIsTraceOpen] = useState(true)
  const contentRef = useRef<HTMLDivElement>(null)

  // useLayoutEffect fires before paint — gives reliable scrollHeight; also resets when content shrinks
  useLayoutEffect(() => {
    if (!isUser) return
    const el = contentRef.current
    if (el && el.scrollHeight > 140) {
      setIsLong(true)
    } else if (el) {
      setIsLong(false)
    }
  }, [message.content, isUser])

  // Notice messages render as a centered pill (provider failover announcements etc.)
  if (message.role === 'notice') {
    return (
      <div className="flex justify-center my-2">
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full
                         bg-theme-surface border border-theme-border/40
                         text-[10px] text-theme-text-muted font-medium select-none">
          <span>⇄</span>{message.content}
        </span>
      </div>
    )
  }

  const showTruncated = isUser && isLong && !isExpanded && !isStreaming

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-3`}>
      <div className={`flex flex-col w-fit ${isUser ? 'max-w-[50%] ml-auto' : 'max-w-[85%] md:max-w-[75%] mr-auto'}`}>
        <div
          ref={contentRef}
          className={`rounded-2xl px-4 py-2 text-sm leading-relaxed relative break-words break-all ${
            isUser
              ? 'bg-theme-user-bubble text-theme-user-bubble-text whitespace-pre-wrap'
              : 'bg-theme-ai-bubble text-theme-ai-bubble-text border border-theme-border/40'
          } ${showTruncated ? 'max-h-[140px] overflow-hidden' : `max-h-none ${isUser && isLong ? 'pb-7' : ''}`}`}
        >
          {/* Fade Overlay */}
          {showTruncated && (
            <div className={`absolute bottom-0 left-0 right-0 h-10 bg-gradient-to-t ${isUser ? 'from-theme-user-bubble via-theme-user-bubble/80' : 'from-theme-ai-bubble via-theme-ai-bubble/80'} to-transparent pointer-events-none z-10`} />
          )}

          {/* Toggle Button */}
          {isUser && isLong && !isStreaming && (
            <button
              type="button"
              onClick={() => setIsExpanded(!isExpanded)}
              className="absolute bottom-1.5 right-4 text-[10px] font-bold select-none cursor-pointer hover:underline underline-offset-2 z-20 text-theme-user-bubble-text/90 hover:text-theme-user-bubble-text"
            >
              {isExpanded ? 'less' : 'more'}
            </button>
          )}

          {isUser ? (
            message.content
          ) : message.content === '' && isStreaming ? (
            /* Thinking indicator: shown before first token arrives */
            <span className="flex items-center gap-1.5 py-0.5" aria-label="Thinking">
              <span className="thinking-dot w-1.5 h-1.5 rounded-full bg-theme-text-muted" />
              <span className="thinking-dot w-1.5 h-1.5 rounded-full bg-theme-text-muted" style={{ animationDelay: '0.2s' }} />
              <span className="thinking-dot w-1.5 h-1.5 rounded-full bg-theme-text-muted" style={{ animationDelay: '0.4s' }} />
            </span>
          ) : (
            <>
              <ReactMarkdown
                components={{
                  ul: ({ children }) => <ul className="list-disc pl-4 space-y-1 my-1.5">{children}</ul>,
                  ol: ({ children }) => <ol className="list-decimal pl-4 space-y-1 my-1.5">{children}</ol>,
                  li: ({ children }) => <li className="text-sm my-0.5 leading-relaxed">{children}</li>,
                  p: ({ children }) => <p className="my-1.5 first:mt-0 last:mb-0 leading-relaxed">{children}</p>,
                  h1: ({ children }) => <h1 className="text-lg font-bold my-2">{children}</h1>,
                  h2: ({ children }) => <h2 className="text-base font-bold my-1.5">{children}</h2>,
                  h3: ({ children }) => <h3 className="text-sm font-bold my-1">{children}</h3>,
                  pre: ({ children }) => (
                    <pre className="bg-theme-surface-hover/80 p-3 rounded-lg overflow-x-auto my-2 border border-theme-border/40 font-mono text-xs leading-normal">
                      {children}
                    </pre>
                  ),
                  code: ({ children, className }) => {
                    const isInline = !className
                    return isInline ? (
                      <code className="bg-theme-surface-hover px-1 py-0.5 rounded font-mono text-xs border border-theme-border/30">
                        {children}
                      </code>
                    ) : (
                      <code className={className}>{children}</code>
                    )
                  },
                  a: ({ children, href }) => (
                    <a href={href} target="_blank" rel="noopener noreferrer" className="text-blue-500 dark:text-blue-400 hover:underline">
                      {children}
                    </a>
                  ),
                }}
              >
                {message.content}
              </ReactMarkdown>
              {/* Blinking cursor during active stream */}
              {isStreaming && (
                <span className="inline-block w-0.5 h-3.5 bg-theme-text-muted opacity-75 animate-pulse ml-px align-middle" aria-hidden />
              )}
            </>
          )}
        </div>

        {/* Metadata + Agent Trace Panel */}
        {!isUser && (message.viaProvider || (message.trace && message.trace.length > 0)) && (
          <div className="mt-1.5 flex flex-col w-full px-2 relative z-10">
            {/* Metadata Row */}
            <div className="flex items-center justify-between text-[10px] text-theme-text-muted font-medium select-none">
              {/* Left: Provider badge */}
              <div>
                {message.viaProvider && (
                  <span className="inline-flex items-center px-1.5 py-0.5 rounded-full
                                   bg-theme-surface border border-theme-border/40
                                   text-[10px] text-theme-text-muted font-medium leading-none">
                    via {formatProviderName(message.viaProvider)}
                  </span>
                )}
              </div>

              {/* Right: Agent trace toggle */}
              {message.trace && message.trace.length > 0 && (
                <button
                  type="button"
                  onClick={() => setIsTraceOpen(!isTraceOpen)}
                  className="flex items-center gap-1 hover:text-theme-text transition-colors focus:outline-none cursor-pointer font-semibold"
                >
                  <span>Agent Execution ({message.trace.length} step{message.trace.length > 1 ? 's' : ''})</span>
                  <svg
                    className={`w-3 h-3 transform transition-transform ${isTraceOpen ? 'rotate-180' : ''}`}
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M19 9l-7 7-7-7" />
                  </svg>
                </button>
              )}
            </div>

            {/* Trace panel: smooth height collapse via grid-rows (no JS measurement needed) */}
            {message.trace && message.trace.length > 0 && (
              <div className={`mt-1.5 overflow-hidden transition-all duration-200 grid ${
                isTraceOpen ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'
              }`}>
                <div className="min-h-0">
                  <div className="p-3 rounded-xl border border-theme-border/40 bg-theme-bg text-xs text-theme-text shadow-sm divide-y divide-theme-border/10 max-h-60 overflow-y-auto">
                    {message.trace.map((event, idx) => {
                      if (event.type === 'step') {
                        return (
                          <div key={idx} className="flex items-start gap-2 pt-2 first:pt-0">
                            <span className="text-emerald-500 font-semibold mt-0.5 select-none">●</span>
                            <div className="flex-1">
                              <span className="font-semibold text-theme-text">{event.label}</span>
                              {event.detail && (
                                <span className="text-theme-text-muted block mt-0.5 bg-theme-surface/60 p-1.5 rounded font-mono text-[10px] whitespace-pre-wrap border border-theme-border/30">
                                  {event.detail}
                                </span>
                              )}
                            </div>
                          </div>
                        )
                      }

                      if (event.type === 'memory_hit') {
                        return (
                          <div key={idx} className="flex items-start gap-2 pt-2 italic">
                            <span className="text-amber-500 font-bold mt-0.5 select-none">↩</span>
                            <div className="flex-1 text-[11px] leading-relaxed text-theme-text-muted">
                              <span className="font-medium text-theme-text not-italic">Memory Hit:</span> {event.summary}
                            </div>
                          </div>
                        )
                      }

                      if (event.type === 'model_call') {
                        return (
                          <div key={idx} className="flex items-center gap-2 pt-2 text-theme-text-muted">
                            <span className="text-theme-text select-none">⚡</span>
                            <div className="flex items-center gap-1.5 flex-wrap">
                              <span className="font-medium text-theme-text">Model Call:</span>
                              <span className="px-1.5 py-0.5 rounded bg-theme-surface border border-theme-border/50 text-theme-text font-mono text-[10px]">
                                {event.model}
                              </span>
                              <span className="text-[10px] text-theme-text-muted capitalize">({event.purpose})</span>
                            </div>
                          </div>
                        )
                      }

                      if (event.type === 'provider_switch') {
                        return (
                          <div key={idx} className="flex items-center gap-2 pt-2 text-theme-text bg-theme-surface/40 p-1.5 rounded border border-theme-border/30">
                            <span className="select-none text-theme-text-muted">⇄</span>
                            <div>
                              <span className="font-semibold">Provider Switch:</span>
                              <span className="ml-1 font-mono text-[10px] text-theme-text-muted">
                                {event.from} → {event.to}
                              </span>
                            </div>
                          </div>
                        )
                      }
                      return null
                    })}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
