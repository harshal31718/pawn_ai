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
  return entry.label ? (tense === 'present' ? `${entry.label}…` : entry.label) : 'Working…'
}

// ── Structured grouping (2026-07-13 UX revision: "structured dropdowns per
//    tool / per agent, one big dropdown overall") ─────────────────────────
//
// Level 1: master summary row (whole activity block, auto-collapses on done).
// Level 2: per-agent groups — main's items render top-level; each subagent
//          becomes ONE collapsible group ("researcher · 3 tool calls · 4.1s").
// Level 3: each tool call is ONE collapsible card; the citations/memory-hits
//          it produced fold inside it instead of rendering as sibling rows.

interface ToolItem {
  type: 'tool'
  entry: TraceEntry
  results: TraceEntry[] // citations + memory_hits attributed to this call
}
interface StepItem {
  type: 'step'
  entry: TraceEntry
}
type Item = ToolItem | StepItem

function buildItems(entries: TraceEntry[]): Item[] {
  const items: Item[] = []
  for (const entry of entries) {
    const last = items[items.length - 1]
    if (entry.kind === 'citation' || entry.kind === 'memory_hit') {
      // Attribute results to the tool call that produced them (the most
      // recent tool item); orphans (shouldn't happen) render as steps.
      if (last && last.type === 'tool') {
        last.results.push(entry)
        continue
      }
      items.push({ type: 'step', entry })
    } else if (entry.kind === 'tool') {
      items.push({ type: 'tool', entry, results: [] })
    } else {
      items.push({ type: 'step', entry })
    }
  }
  return items
}

interface AgentGroup {
  agent: string
  items: Item[]
}

function groupByAgent(trace: TraceEntry[]): AgentGroup[] {
  const groups: { agent: string; entries: TraceEntry[] }[] = []
  for (const entry of trace) {
    const last = groups[groups.length - 1]
    if (last && last.agent === entry.agent) last.entries.push(entry)
    else groups.push({ agent: entry.agent, entries: [entry] })
  }
  return groups.map((g) => ({ agent: g.agent, items: buildItems(g.entries) }))
}

function summarize(trace: TraceEntry[]) {
  const steps = trace.length
  const toolCalls = trace.filter((t) => t.kind === 'tool').length
  const sources = trace.filter((t) => t.kind === 'citation').length
  const totalMs = trace.reduce((sum, t) => sum + (t.elapsedMs || 0), 0)
  return { steps, toolCalls, sources, seconds: totalMs / 1000 }
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      className={`w-2.5 h-2.5 shrink-0 transform transition-transform ${open ? 'rotate-180' : ''}`}
      fill="none" stroke="currentColor" viewBox="0 0 24 24"
    >
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M19 9l-7 7-7-7" />
    </svg>
  )
}

/** One result line inside an expanded tool card. */
function ResultRow({ entry }: { entry: TraceEntry }) {
  if (entry.kind === 'citation') {
    return (
      <a
        href={entry.url}
        target="_blank"
        rel="noopener noreferrer"
        className="flex items-start gap-1.5 py-0.5 hover:text-theme-ai-bubble-text transition-colors"
      >
        <span className="select-none shrink-0">↗</span>
        <span className="truncate">{entry.title || entry.url}</span>
      </a>
    )
  }
  // memory_hit
  return (
    <div className="flex items-start gap-1.5 py-0.5 italic">
      <span className="text-amber-400 select-none shrink-0">↩</span>
      <span className="min-w-0">
        {entry.summary}
        {entry.scope === 'project' && (
          <span className="ml-1.5 not-italic rounded-full border border-theme-ai-bubble-text/25 px-1.5 text-[10px] align-middle">
            project{entry.sourceConvId ? ` · from ${entry.sourceConvId.slice(0, 8)}` : ''}
          </span>
        )}
      </span>
    </div>
  )
}

/** Collapsible card for one tool call: header row (label · elapsed · result
 *  count · chevron); body = args/observation preview + its result rows. */
function ToolCard({ item }: { item: ToolItem }) {
  const running = item.entry.status === 'running'
  const [open, setOpen] = useState(false)
  const label = toolLabel(item.entry, running ? 'present' : 'past')
  const preview = item.entry.observation ?? item.entry.detail
  const nResults = item.results.length
  const hasBody = Boolean(preview) || nResults > 0

  return (
    <div className="rounded-md border border-theme-ai-bubble-text/10 bg-theme-surface/40 my-1 overflow-hidden">
      <button
        type="button"
        disabled={!hasBody && !running}
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 px-2 py-1 text-left hover:bg-theme-surface/70 transition-colors disabled:cursor-default"
      >
        <span className={`select-none ${running ? 'text-emerald-500 animate-pulse' : 'text-theme-ai-bubble-text/60'}`}>●</span>
        <span className="flex-1 min-w-0 truncate">
          {label}
          {!running && item.entry.elapsedMs !== undefined && item.entry.elapsedMs > 0 && (
            <span className="text-theme-ai-bubble-text/50"> · {(item.entry.elapsedMs / 1000).toFixed(1)}s</span>
          )}
          {nResults > 0 && (
            <span className="text-theme-ai-bubble-text/50"> · {nResults} result{nResults === 1 ? '' : 's'}</span>
          )}
        </span>
        {hasBody && <Chevron open={open} />}
      </button>
      {open && hasBody && (
        <div className="px-2 pb-1.5 border-t border-theme-ai-bubble-text/10">
          {preview && (
            <div className="text-theme-ai-bubble-text/70 mt-1 bg-theme-surface/60 p-1.5 rounded font-mono text-[10px] whitespace-pre-wrap border border-theme-ai-bubble-text/10 max-h-24 overflow-y-auto">
              {preview.slice(0, 300)}
            </div>
          )}
          {nResults > 0 && (
            <div className="mt-1">
              {item.results.map((r, i) => <ResultRow key={i} entry={r} />)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/** Plain (non-tool) step row — plan lines, provider switches, model calls. */
function StepRow({ entry }: { entry: TraceEntry }) {
  if (entry.kind === 'provider_switch') {
    return (
      <div className="flex items-center gap-2 py-0.5">
        <span className="select-none">⇄</span>
        <span>Provider switch: {entry.from} → {entry.to}</span>
      </div>
    )
  }
  if (entry.kind === 'model_call') {
    return (
      <div className="flex items-center gap-2 py-0.5">
        <span className="select-none">⚡</span>
        <span>Model call: {entry.model} ({entry.purpose})</span>
      </div>
    )
  }
  if (entry.kind === 'citation' || entry.kind === 'memory_hit') {
    return <ResultRow entry={entry} />
  }
  return (
    <div className="flex items-start gap-2 py-0.5">
      <span className="text-theme-ai-bubble-text/50 mt-0.5 select-none">·</span>
      <div className="flex-1 min-w-0">
        <span>{entry.label}</span>
        {entry.detail && (
          <div className="text-theme-ai-bubble-text/70 mt-0.5 whitespace-pre-wrap">{entry.detail}</div>
        )}
      </div>
    </div>
  )
}

function ItemList({ items }: { items: Item[] }) {
  return (
    <>
      {items.map((item, i) =>
        item.type === 'tool' ? <ToolCard key={i} item={item} /> : <StepRow key={i} entry={item.entry} />,
      )}
    </>
  )
}

/** One collapsible group for a subagent's whole activity. */
function SubagentGroup({ group, isStreaming }: { group: AgentGroup; isStreaming: boolean }) {
  const anyRunning = group.items.some((it) => it.type === 'tool' && it.entry.status === 'running')
  const [open, setOpen] = useState(false)
  const toolCalls = group.items.filter((it) => it.type === 'tool').length
  const ms = group.items.reduce(
    (sum, it) => sum + (it.type === 'tool' ? it.entry.elapsedMs || 0 : 0),
    0,
  )
  const expanded = open || (isStreaming && anyRunning)

  return (
    <div className="rounded-md border border-theme-ai-bubble-text/15 my-1 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 px-2 py-1 text-left font-semibold text-theme-ai-bubble-text/80 hover:bg-theme-surface/70 transition-colors"
      >
        <span className={`select-none ${anyRunning ? 'text-emerald-500 animate-pulse' : ''}`}>▸</span>
        <span className="flex-1 min-w-0 truncate">
          {group.agent}
          <span className="font-normal text-theme-ai-bubble-text/50">
            {' '}· {toolCalls} tool call{toolCalls === 1 ? '' : 's'}{ms > 0 ? ` · ${(ms / 1000).toFixed(1)}s` : ''}
          </span>
        </span>
        <Chevron open={expanded} />
      </button>
      {expanded && (
        <div className="px-2 pb-1 border-t border-theme-ai-bubble-text/10">
          <ItemList items={group.items} />
        </div>
      )}
    </div>
  )
}

/** Renders one run of trace entries grouped by agent (main's items inline,
 *  each subagent as its own collapsible group) -- the reusable core both
 *  TraceView (the full collapsible block, reload/no-segments path) and
 *  Message.tsx's interleaved segments renderer (Phase N, live path) build
 *  on, so a subagent's nested "N tool calls" grouping looks identical in
 *  both rendering modes. */
export function TraceEntries({ entries, isStreaming }: { entries: TraceEntry[]; isStreaming: boolean }) {
  const groups = groupByAgent(entries)
  return (
    <>
      {groups.map((group, gIdx) =>
        group.agent === 'main' ? (
          <ItemList key={gIdx} items={group.items} />
        ) : (
          <SubagentGroup key={gIdx} group={group} isStreaming={isStreaming} />
        ),
      )}
    </>
  )
}

/** P.1 — one collapsible "run" of trace entries inside the interleaved
 *  segments render (Message.tsx's InterleavedContent): the outer, coarser
 *  toggle level ("multi-consecutive-tool/agent-calls specific"), one level
 *  above ToolCard/SubagentGroup's per-tool/per-agent toggles. Auto-open
 *  while this run is the currently-active one (the last chunk, message
 *  still streaming), auto-collapses to a summary line the instant the run
 *  ends (a later chunk begins, or the stream finishes) -- same "auto-
 *  collapse on completion, reopen any time after" contract TraceView's own
 *  top-level toggle already uses. While active, the header shows the
 *  in-flight step's own live label (e.g. "Searching the web…") instead of
 *  the static summary, mirroring Claude's own "Thinking…" affordance. */
export function TraceRun({ entries, isStreaming, isActive }: { entries: TraceEntry[]; isStreaming: boolean; isActive: boolean }) {
  const [isOpen, setIsOpen] = useState(isActive)
  const wasActive = useRef(isActive)

  useEffect(() => {
    if (wasActive.current && !isActive) setIsOpen(false)
    wasActive.current = isActive
  }, [isActive])

  if (entries.length === 0) return null

  const { steps, toolCalls, sources, seconds } = summarize(entries)
  const runningEntry = isActive
    ? [...entries].reverse().find((e) => e.kind === 'tool' && e.status === 'running')
    : undefined
  const liveLabel = runningEntry ? toolLabel(runningEntry, 'present') : null

  return (
    <div className="my-1 flex flex-col w-full text-[11px] text-theme-ai-bubble-text/60">
      <button
        type="button"
        onClick={() => setIsOpen((o) => !o)}
        className="flex items-center gap-1 self-start hover:text-theme-ai-bubble-text transition-colors focus:outline-none cursor-pointer font-medium"
      >
        <span>
          {liveLabel ?? (
            <>
              {steps} step{steps === 1 ? '' : 's'} · {toolCalls} tool call{toolCalls === 1 ? '' : 's'} · {sources} source{sources === 1 ? '' : 's'}
              {seconds > 0 ? ` · ${seconds.toFixed(1)}s` : ''}
            </>
          )}
        </span>
        <Chevron open={isOpen} />
      </button>

      <div className={`overflow-hidden transition-all duration-200 grid ${isOpen ? 'grid-rows-[1fr] opacity-100 mt-1' : 'grid-rows-[0fr] opacity-0'}`}>
        <div className="min-h-0">
          <TraceEntries entries={entries} isStreaming={isStreaming} />
        </div>
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

  return (
    <div className="mb-2 flex flex-col w-full text-[11px] text-theme-ai-bubble-text/60">
      <button
        type="button"
        onClick={() => setIsOpen((o) => !o)}
        className="flex items-center gap-1 self-start hover:text-theme-ai-bubble-text transition-colors focus:outline-none cursor-pointer font-medium"
      >
        <span>
          {steps} step{steps === 1 ? '' : 's'} · {toolCalls} tool call{toolCalls === 1 ? '' : 's'} · {sources} source{sources === 1 ? '' : 's'}
          {seconds > 0 ? ` · ${seconds.toFixed(1)}s` : ''}
        </span>
        <Chevron open={isOpen} />
      </button>

      <div className={`overflow-hidden transition-all duration-200 grid ${isOpen ? 'grid-rows-[1fr] opacity-100 mt-1' : 'grid-rows-[0fr] opacity-0'}`}>
        <div className="min-h-0">
          <TraceEntries entries={trace} isStreaming={isStreaming} />
        </div>
      </div>
    </div>
  )
}
