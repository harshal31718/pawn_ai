import { useState, useRef, useLayoutEffect, type ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Message, Segment, TraceEntry } from '../types'
import TraceView, { TraceRun } from './TraceView'
import CitationChips from './CitationChips'
import { LinkIcon } from './icons'

/** Flattens a react-markdown link's children into plain text, to detect a
 *  bare-URL autolink (visible text === the URL itself) vs. real anchor text
 *  like "Statistics Iceland" -- only the former gets swapped for an icon. */
function textOf(node: ReactNode): string {
  if (node == null || typeof node === 'boolean') return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(textOf).join('')
  if (typeof node === 'object' && 'props' in (node as any)) return textOf((node as any).props.children)
  return ''
}

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

type Chunk = { kind: 'text'; content: string } | { kind: 'trace'; entries: TraceEntry[] }

// Phase N — merges the ordered segments list into render-ready chunks:
// consecutive 'tool'-typed segments (a run of trace-worthy events, possibly
// spanning a subagent's whole nested activity) collapse into one TraceEntries
// run; consecutive 'text' segments (arriving as separate token deltas) merge
// into one prose block. Empty text segments are dropped (e.g. a stream that
// hasn't produced its first delta yet).
function chunkSegments(segments: Segment[]): Chunk[] {
  const chunks: Chunk[] = []
  for (const seg of segments) {
    const last = chunks[chunks.length - 1]
    if (seg.type === 'text') {
      if (seg.content === '') continue
      if (last && last.kind === 'text') last.content += seg.content
      else chunks.push({ kind: 'text', content: seg.content })
    } else {
      if (last && last.kind === 'trace') last.entries.push(seg.entry)
      else chunks.push({ kind: 'trace', entries: [seg.entry] })
    }
  }
  return chunks
}

// Researcher/synthesis prompts tell the model to bind facts to sources as
// "(source: <url>)" -- with the inline link now rendered as an icon-only
// link (below), that wrapper text is just noise; strip it down to the bare
// URL so only the icon remains, no "(source: ...)" parenthetical around it.
const _SOURCE_WRAPPER_RE = /\(\s*source:\s*(https?:\/\/[^\s)]+)\s*\)/gi

/** Shared markdown renderer -- used both for the legacy single-block content
 *  render and for each text chunk in the interleaved segments render. */
function MarkdownContent({ content }: { content: string }) {
  const cleaned = content.replace(_SOURCE_WRAPPER_RE, '$1')
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        table: ({ children }) => (
          <div className="overflow-x-auto my-2 rounded-lg border border-theme-border/40">
            <table className="w-full text-sm sm:text-xs border-collapse">{children}</table>
          </div>
        ),
        thead: ({ children }) => (
          <thead className="bg-theme-surface-hover/80 text-theme-text">{children}</thead>
        ),
        th: ({ children }) => (
          <th className="px-3 py-1.5 text-left font-semibold border-b border-theme-border/40 whitespace-nowrap">
            {children}
          </th>
        ),
        td: ({ children }) => (
          <td className="px-3 py-1.5 border-b border-theme-border/20 align-top">{children}</td>
        ),
        tr: ({ children }) => <tr className="even:bg-theme-surface-hover/30">{children}</tr>,
        blockquote: ({ children }) => (
          <blockquote className="border-l-2 border-theme-border pl-3 my-2 text-theme-text-muted italic">
            {children}
          </blockquote>
        ),
        hr: () => <hr className="my-3 border-theme-border/40" />,
        ul: ({ children }) => <ul className="list-disc pl-4 space-y-1 my-1.5">{children}</ul>,
        ol: ({ children }) => <ol className="list-decimal pl-4 space-y-1 my-1.5">{children}</ol>,
        li: ({ children }) => <li className="text-sm my-0.5 leading-relaxed">{children}</li>,
        p: ({ children }) => <p className="my-1.5 first:mt-0 last:mb-0 leading-relaxed">{children}</p>,
        h1: ({ children }) => <h1 className="text-lg font-bold my-2">{children}</h1>,
        h2: ({ children }) => <h2 className="text-base font-bold my-1.5">{children}</h2>,
        h3: ({ children }) => <h3 className="text-sm font-bold my-1">{children}</h3>,
        pre: ({ children }) => (
          <pre className="bg-theme-surface-hover/80 p-3 rounded-lg overflow-x-auto my-2 border border-theme-border/40 font-mono text-sm sm:text-xs leading-normal">
            {children}
          </pre>
        ),
        code: ({ children, className }) => {
          const isInline = !className
          return isInline ? (
            <code className="bg-theme-surface-hover px-1 py-0.5 rounded font-mono text-sm sm:text-xs border border-theme-border/30">
              {children}
            </code>
          ) : (
            <code className={className}>{children}</code>
          )
        },
        a: ({ children, href }) => {
          const label = textOf(children).trim()
          const bareUrl = !!href && (label === href || label.replace(/\/+$/, '') === href.replace(/\/+$/, ''))
          return bareUrl ? (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              title={href}
              className="inline-flex items-center align-text-bottom mx-0.5 text-theme-text-muted hover:text-blue-500 dark:hover:text-blue-400"
            >
              <LinkIcon className="w-3.5 h-3.5" />
            </a>
          ) : (
            <a href={href} target="_blank" rel="noopener noreferrer" className="text-blue-500 dark:text-blue-400 hover:underline">
              {children}
            </a>
          )
        },
      }}
    >
      {cleaned}
    </ReactMarkdown>
  )
}

/** Phase N — live interleaved rendering: walks `segments` in arrival order,
 *  rendering prose and trace-entry runs exactly where they occurred instead
 *  of the legacy "trace block above, content below" split. Only used once a
 *  message actually has at least one tool-typed segment (a pure-text stream
 *  falls back to the legacy single-block path, which is equivalent and
 *  simpler). */
function InterleavedContent({ segments, isStreaming }: { segments: Segment[]; isStreaming: boolean }) {
  const chunks = chunkSegments(segments)
  const lastChunk = chunks[chunks.length - 1]

  return (
    <>
      {chunks.map((chunk, i) =>
        chunk.kind === 'trace' ? (
          // P.1 — each run of consecutive tool-typed segments gets its own
          // outer collapsible toggle (auto-open while it's the active/last
          // run and the message is still streaming, auto-collapse the
          // instant a later chunk begins), one level above the per-tool/
          // per-agent toggles TraceEntries already renders inside it.
          <TraceRun key={i} entries={chunk.entries} isStreaming={isStreaming} isActive={isStreaming && i === chunks.length - 1} />
        ) : (
          <MarkdownContent key={i} content={chunk.content} />
        ),
      )}
      {isStreaming && lastChunk?.kind === 'text' && (
        <span className="inline-block w-0.5 h-3.5 bg-theme-ai-bubble-text opacity-75 animate-pulse ml-px align-middle" aria-hidden />
      )}
    </>
  )
}

export default function MessageBubble({ message, isStreaming }: Props) {
  const isUser = message.role === 'user'
  const [isExpanded, setIsExpanded] = useState(false)
  const [isLong, setIsLong] = useState(false)
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
      <div className={`flex flex-col w-fit ${isUser ? 'max-w-[70%] sm:max-w-[50%] ml-auto' : 'max-w-[85%] md:max-w-[75%] mr-auto'}`}>
        <div
          ref={contentRef}
          className={`rounded-2xl px-4 py-2 text-sm leading-relaxed relative break-words ${
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
          ) : (message.segments && message.segments.some((s) => s.type === 'tool')) ? (
            /* Phase N — interleaved live rendering: text and tool cards render
               in true arrival order instead of one trace block above the
               whole reply. Only taken once a message has actually produced a
               tool-typed segment; reloaded/historical messages (no segments)
               and pure-text streams both fall back to the legacy path below,
               which is equivalent for them and simpler. */
            <InterleavedContent segments={message.segments} isStreaming={isStreaming} />
          ) : (
            <>
              {/* Legacy path: reloaded/historical messages (trace/content as
                  separate persisted fields, Phase A / A.8) and pure-text live
                  streams (no tool activity to interleave) both render here —
                  agent activity above the reply, inside the same bubble. */}
              {message.trace && message.trace.length > 0 && (
                <TraceView trace={message.trace} isStreaming={isStreaming} />
              )}
              {message.content === '' && isStreaming ? (
                /* Thinking indicator: shown before first token arrives */
                <span className="flex items-center gap-1.5 py-0.5" aria-label="Thinking">
                  <span className="thinking-dot w-1.5 h-1.5 rounded-full bg-theme-ai-bubble-text/60" />
                  <span className="thinking-dot w-1.5 h-1.5 rounded-full bg-theme-ai-bubble-text/60" style={{ animationDelay: '0.2s' }} />
                  <span className="thinking-dot w-1.5 h-1.5 rounded-full bg-theme-ai-bubble-text/60" style={{ animationDelay: '0.4s' }} />
                </span>
              ) : (
                <>
                  <MarkdownContent content={message.content} />
                  {/* Blinking cursor during active stream */}
                  {isStreaming && (
                    <span className="inline-block w-0.5 h-3.5 bg-theme-ai-bubble-text opacity-75 animate-pulse ml-px align-middle" aria-hidden />
                  )}
                </>
              )}
            </>
          )}
        </div>

        {!isUser && message.citations && message.citations.length > 0 && (
          <CitationChips citations={message.citations} />
        )}

        {/* Provider badge — the agent trace itself now renders inline inside
            the bubble, above the reply (Phase A / A.8). */}
        {!isUser && message.viaProvider && (
          <span className="mt-1.5 ml-2 inline-flex items-center self-start px-1.5 py-0.5 rounded-full
                           bg-theme-surface border border-theme-border/40
                           text-[10px] text-theme-text-muted font-medium leading-none select-none">
            via {formatProviderName(message.viaProvider)}
          </span>
        )}
      </div>
    </div>
  )
}
