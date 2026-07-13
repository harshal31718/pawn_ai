import { useEffect, useRef, useState } from 'react'
import type { TraceEntry } from '../types'

interface Props {
  trace: TraceEntry[]
  /** Whether this message's stream is still live. Drives the present-tense/
   *  past-tense flip on the last "running" tool entry and the auto-collapse
   *  on completion (Phase A / A.8). */
  isStreaming: boolean
}

// Friendly present/past-tense labels for known tool names (Phase A / A.8,
// "Claude-app style" locked with the user 2026-07-13). Anything not in this
// table (an unrecognized tool, or a future one) falls back to its raw name.
const TOOL_PRESENT: Record<string, string> = {
  web_search: 'Searching the web…',
  fetch_url: 'Reading page…',
  search_memory: 'Searching memory…',
  doc_search: 'Searching the document…',
  calculator: 'Calculating…',
  get_datetime: 'Checking the time…',
}
const TOOL_PAST: Record<string, string> = {
  web_search: 'Searched the web',
  fetch_url: 'Read page',
  search_memory: 'Searched memory',
  doc_search: 'Searched the document',
  calculator: 'Calculated',
  get_datetime: 'Checked the time',
}
const SUBAGENTS = new Set(['researcher', 'summarizer', 'coder'])

function bareName(name: string): string {
  return name.startsWith('delegate_') ? name.slice('delegate_'.length) : name
}

function toolLabel(entry: TraceEntry, tense: 'present' | 'past'): string {
  const name = entry.name ? bareName(entry.name) : ''
  if (name && SUBAGENTS.has(name)) {
    return tense === 'present' ? `Delegating to ${name}…` : `Delegated to ${name}`
  }
  const table = tense === 'present' ? TOOL_PRESENT : TOOL_PAST
  if (name && table[name]) return table[name]
  if (name) return tense === 'present' ? `Calling ${name}…` : `Called ${name}`
  // No resolved tool name yet (onToolCall hasn't landed) — fall back to the
  // raw step label, which is always present.
  return entry.label ? (tense === 'present' ? `${entry.label}…` : entry.label) : 'Working…'
}

interface Group {
  agent: string
  entries: TraceEntry[]
}

function groupByAgent(trace: TraceEntry[]): Group[] {
  const groups: Group[] = []
  for (const entry of trace) {
    const last = groups[groups.length - 1]
    if (last && last.agent === entry.agent) last.entries.push(entry)
    else groups.push({ agent: entry.agent, entries: [entry] })
  }
  return groups
}

function summarize(trace: TraceEntry[]) {
  const steps = trace.length
  const toolCalls = trace.filter((t) => t.kind === 'tool').length
  const sources = trace.filter((t) => t.kind === 'citation').length
  const totalMs = trace.reduce((sum, t) => sum + (t.elapsedMs || 0), 0)
  return { steps, toolCalls, sources, seconds: totalMs / 1000 }
}

function EntryRow({ entry }: { entry: TraceEntry }) {
  if (entry.kind === 'tool') {
    const running = entry.status === 'running'
    const label = toolLabel(entry, running ? 'present' : 'past')
    const preview = entry.observation ?? entry.detail
    return (
      <div className="flex items-start gap-2 pt-1.5 first:pt-0">
        <span className={`mt-0.5 select-none ${running ? 'text-emerald-500 animate-pulse' : 'text-theme-text-muted'}`}>●</span>
        <div className="flex-1 min-w-0">
          <span>
            {label}
            {!running && entry.elapsedMs !== undefined && entry.elapsedMs > 0 && (
              <span className="text-theme-text-muted/70"> · {(entry.elapsedMs / 1000).toFixed(1)}s</span>
            )}
          </span>
          {!running && preview && (
            <div className="text-theme-text-muted/80 mt-0.5 bg-theme-surface/60 p-1.5 rounded font-mono text-[10px] whitespace-pre-wrap border border-theme-border/20 max-h-20 overflow-y-auto">
              {preview.slice(0, 300)}
            </div>
          )}
        </div>
      </div>
    )
  }

  if (entry.kind === 'citation') {
    return (
      <div className="flex items-start gap-2 pt-1.5">
        <span className="text-theme-text-muted mt-0.5 select-none">↗</span>
        <span className="truncate">{entry.title || entry.url}</span>
      </div>
    )
  }

  if (entry.kind === 'memory_hit') {
    return (
      <div className="flex items-start gap-2 pt-1.5 italic">
        <span className="text-amber-500/80 mt-0.5 select-none">↩</span>
        <div className="flex-1 min-w-0">
          <span className="not-italic">Memory hit:</span> {entry.summary}
          {entry.scope === 'project' && (
            <span className="ml-1.5 not-italic rounded-full border border-theme-border px-1.5 py-0.5 text-[10px] align-middle">
              project{entry.sourceConvId ? ` · from ${entry.sourceConvId.slice(0, 8)}` : ''}
            </span>
          )}
        </div>
      </div>
    )
  }

  if (entry.kind === 'provider_switch') {
    return (
      <div className="flex items-center gap-2 pt-1.5">
        <span className="select-none">⇄</span>
        <span>Provider switch: {entry.from} → {entry.to}</span>
      </div>
    )
  }

  if (entry.kind === 'model_call') {
    return (
      <div className="flex items-center gap-2 pt-1.5">
        <span className="select-none">⚡</span>
        <span>Model call: {entry.model} ({entry.purpose})</span>
      </div>
    )
  }

  // kind === 'step' (Plan, Composing final answer, ...)
  return (
    <div className="flex items-start gap-2 pt-1.5 first:pt-0">
      <span className="text-theme-text-muted/60 mt-0.5 select-none">·</span>
      <div className="flex-1 min-w-0">
        <span>{entry.label}</span>
        {entry.detail && (
          <div className="text-theme-text-muted/80 mt-0.5 whitespace-pre-wrap">{entry.detail}</div>
        )}
      </div>
    </div>
  )
}

export default function TraceView({ trace, isStreaming }: Props) {
  const [isOpen, setIsOpen] = useState(isStreaming)
  const wasStreaming = useRef(isStreaming)

  useEffect(() => {
    // Auto-collapse the moment this message's stream finishes; the user can
    // still re-expand via the chevron at any time afterward.
    if (wasStreaming.current && !isStreaming) setIsOpen(false)
    wasStreaming.current = isStreaming
  }, [isStreaming])

  if (trace.length === 0) return null

  const { steps, toolCalls, sources, seconds } = summarize(trace)
  const groups = groupByAgent(trace)

  return (
    <div className="mt-1 flex flex-col w-full text-[11px] text-theme-text-muted">
      <button
        type="button"
        onClick={() => setIsOpen((o) => !o)}
        className="flex items-center gap-1 self-start hover:text-theme-text transition-colors focus:outline-none cursor-pointer font-medium"
      >
        <span>
          {steps} step{steps === 1 ? '' : 's'} · {toolCalls} tool call{toolCalls === 1 ? '' : 's'} · {sources} source{sources === 1 ? '' : 's'}
          {seconds > 0 ? ` · ${seconds.toFixed(1)}s` : ''}
        </span>
        <svg
          className={`w-3 h-3 transform transition-transform ${isOpen ? 'rotate-180' : ''}`}
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      <div className={`overflow-hidden transition-all duration-200 grid ${isOpen ? 'grid-rows-[1fr] opacity-100 mt-1' : 'grid-rows-[0fr] opacity-0'}`}>
        <div className="min-h-0">
          <div className="divide-y divide-theme-border/10">
            {groups.map((group, gIdx) =>
              group.agent === 'main' ? (
                group.entries.map((entry, eIdx) => <EntryRow key={`${gIdx}-${eIdx}`} entry={entry} />)
              ) : (
                <div key={gIdx} className="pt-1.5 pl-3 border-l border-theme-border/30 ml-1">
                  <div className="font-semibold text-theme-text-muted/90 mb-1">▸ {group.agent}</div>
                  <div className="pl-2 space-y-0">
                    {group.entries.map((entry, eIdx) => <EntryRow key={eIdx} entry={entry} />)}
                  </div>
                </div>
              ),
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
