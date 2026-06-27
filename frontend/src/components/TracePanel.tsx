import { useState, useEffect } from 'react'
import type { TraceEvent } from '../types'

interface Props {
  trace?: TraceEvent[]
  isStreaming: boolean
}

export default function TracePanel({ trace, isStreaming }: Props) {
  const [isOpen, setIsOpen] = useState(true)

  useEffect(() => {
    if (!isStreaming && trace && trace.length > 0) {
      const timer = setTimeout(() => setIsOpen(false), 500)
      return () => clearTimeout(timer)
    }
  }, [isStreaming, trace])

  if (!trace || trace.length === 0) return null

  return (
    <div className="mt-2 text-xs border border-zinc-200/50 rounded-lg overflow-hidden bg-zinc-50/50 max-w-[95%]">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full px-3 py-2 flex items-center justify-between text-zinc-500 hover:text-zinc-800 hover:bg-zinc-100/50 transition-colors select-none font-medium border-b border-zinc-200/30"
      >
        <span className="flex items-center gap-1.5">
          <span className="flex h-2 w-2 relative">
            {isStreaming && (
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
            )}
            <span className={`relative inline-flex rounded-full h-2 w-2 ${isStreaming ? 'bg-emerald-500' : 'bg-zinc-400'}`}></span>
          </span>
          Agent Execution Trace ({trace.length} step{trace.length > 1 ? 's' : ''})
        </span>
        <svg
          className={`w-3.5 h-3.5 transform transition-transform ${isOpen ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {isOpen && (
        <div className="p-3 space-y-2.5 max-h-60 overflow-y-auto divide-y divide-zinc-200/20">
          {trace.map((event, idx) => {
            if (event.type === 'step') {
              return (
                <div key={idx} className="flex items-start gap-2 pt-2 first:pt-0">
                  <span className="text-emerald-500 font-semibold mt-0.5 select-none">●</span>
                  <div className="flex-1">
                    <span className="font-semibold text-zinc-700">{event.label}</span>
                    {event.detail && (
                      <span className="text-zinc-500 block mt-0.5 bg-zinc-100/30 p-1 rounded font-mono text-[10px] whitespace-pre-wrap border border-zinc-200/20">
                        {event.detail}
                      </span>
                    )}
                  </div>
                </div>
              )
            }
            
            if (event.type === 'memory_hit') {
              return (
                <div key={idx} className="flex items-start gap-2 pt-2 text-zinc-400 italic">
                  <span className="text-amber-500 font-bold mt-0.5 select-none">↩</span>
                  <div className="flex-1 text-[11px] leading-relaxed">
                    <span className="font-medium text-zinc-500 not-italic">Memory Hit:</span> {event.summary}
                  </div>
                </div>
              )
            }

            if (event.type === 'model_call') {
              return (
                <div key={idx} className="flex items-center gap-2 pt-2 text-zinc-500">
                  <span className="text-indigo-500 select-none">⚡</span>
                  <div className="flex items-center gap-1.5">
                    <span className="font-medium">Model Call:</span>
                    <span className="px-1.5 py-0.5 rounded bg-indigo-50 border border-indigo-100 text-indigo-600 font-mono text-[10px]">
                      {event.model}
                    </span>
                    <span className="text-[10px] text-zinc-400 capitalize">({event.purpose})</span>
                  </div>
                </div>
              )
            }

            if (event.type === 'provider_switch') {
              return (
                <div key={idx} className="flex items-center gap-2 pt-2 text-rose-500 bg-rose-50/30 p-1.5 rounded border border-rose-100/30">
                  <span className="select-none">⇄</span>
                  <div>
                    <span className="font-semibold">Provider Switch:</span>
                    <span className="ml-1 font-mono text-[10px]">
                      {event.from} → {event.to}
                    </span>
                  </div>
                </div>
              )
            }

            return null
          })}
        </div>
      )}
    </div>
  )
}
