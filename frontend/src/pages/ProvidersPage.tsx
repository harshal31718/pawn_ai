import { useEffect, useState } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { fetchFreeTiers, type FreeTiersResponse, type ProviderUsageRow } from '../api/client'
import type { LayoutContext } from './Layout'

/** Same small local formatter used in ModelSwitcher.tsx / Message.tsx --
 *  project convention is a per-file copy of this pure function rather than a
 *  shared import (it's a 5-line pure mapping, not shared state). */
const formatProviderName = (p: string) => {
  if (!p) return ''
  if (p === 'huggingface') return 'HuggingFace'
  if (p === 'openrouter') return 'OpenRouter'
  if (p === 'github') return 'GitHub'
  if (p === 'nvidia') return 'NVIDIA'
  return p.charAt(0).toUpperCase() + p.slice(1)
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n % 1_000_000 === 0 ? 0 : 1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(n % 1_000 === 0 ? 0 : 1)}K`
  return String(n)
}

function BudgetBar({ used, limit }: { used: number; limit: number }) {
  const pct = limit > 0 ? Math.min(100, (used / limit) * 100) : 0
  const color = pct >= 90 ? 'bg-red-500' : pct >= 70 ? 'bg-amber-500' : 'bg-theme-brand'
  return (
    <div className="w-full h-1.5 rounded-full bg-theme-bg overflow-hidden">
      <div className={`h-full ${color} transition-all`} style={{ width: `${pct}%` }} />
    </div>
  )
}

/** One provider/endpoint card. Each card is self-contained (own border,
 *  own padding) so the parent can lay them out in a responsive grid --
 *  1 column on mobile, more on wider screens -- instead of a single long
 *  divided list that wastes desktop width. */
function ProviderCard({ row }: { row: ProviderUsageRow }) {
  return (
    <div className="bg-theme-surface border border-theme-border/50 rounded-xl p-3 space-y-1.5 min-w-0">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="text-xs font-medium text-theme-text truncate">{row.display_name}</p>
          <p className="text-[10px] text-theme-text-muted truncate">{formatProviderName(row.provider)}</p>
        </div>
        <span className="text-[9px] font-semibold uppercase tracking-wide text-theme-text-muted bg-theme-bg/60 px-1.5 py-0.5 rounded-full shrink-0 select-none">
          {row.key_source}
        </span>
      </div>

      {row.has_published_cap && row.tpd_limit ? (
        <>
          <BudgetBar used={row.tpd_used} limit={row.tpd_limit} />
          <p className="text-[10px] text-theme-text-muted">
            {formatTokens(row.tpd_remaining ?? 0)} tokens left today · {formatTokens(row.tpd_used)} /{' '}
            {formatTokens(row.tpd_limit)}
          </p>
          {/* PAWN 2.0 Phase D.3: pool rows show the honest, guaranteed-yours
              share alongside the raw (shared) number above -- the raw
              number overstates what's actually this user's on a pool key. */}
          {row.key_source === 'pool' && row.fair_share_remaining != null && (
            <p className="text-[10px] text-theme-text-muted">
              Your fair share: {formatTokens(row.fair_share_remaining)} tokens
            </p>
          )}
        </>
      ) : (
        <p className="text-[10px] text-theme-text-muted italic">No published token cap</p>
      )}

      {row.rpd_limit != null && (
        <p className="text-[9px] text-theme-text-muted">
          {row.rpd_used} / {row.rpd_limit} requests today
        </p>
      )}
    </div>
  )
}

/** R3 — Providers page: shows this user's free-tier budget across every
 *  provider they've configured a key for. Functionality mirrors OmniRoute's
 *  own free-tier dashboard (the inspiration, credited in README.md only,
 *  never in-app); visual language matches the rest of PAWN's Settings-style
 *  cards (theme-* variables, rounded-xl). Card grid (1/2/3 columns by
 *  breakpoint) rather than a single divided list, so it scales from a phone
 *  up to a wide desktop window instead of leaving most of the screen empty.
 *
 *  Honest-math rules carried over from the backend (see routes/dashboard.py):
 *  the headline total only ever sums endpoints with a PUBLISHED token cap --
 *  providers with no cap are listed separately, never folded in as a guess. */
export default function ProvidersPage() {
  const navigate = useNavigate()
  const { isSidebarOpen, setIsSidebarOpen } = useOutletContext<LayoutContext>()
  const [data, setData] = useState<FreeTiersResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  async function refresh() {
    setError(null)
    try {
      const res = await fetchFreeTiers()
      setData(res)
    } catch {
      setError('Could not load provider usage.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
  }, [])

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden relative bg-theme-bg">
      {/* Floating Top Header -- identical pill chip to SettingsPage.tsx's/
          ImageLabPage.tsx's ("< Providers", nothing else inside the chip). */}
      <header className="absolute top-0 left-0 right-0 z-30 pointer-events-none p-4 flex items-center justify-between w-full">
        <div className="flex items-center gap-2 h-7 pl-2 pr-3 bg-theme-surface border border-theme-border/60 rounded-xl shadow-md pointer-events-auto z-20 transition-all">
          {/* Mobile-only reopen affordance -- on narrow screens the sidebar is
              a full-width overlay that closes on navigation (see Sidebar.tsx's
              handleOpenProviders), so without this there'd be no way back to
              it from here. Mirrors SettingsPage.tsx's own toggle. */}
          {!isSidebarOpen && (
            <button
              type="button"
              onClick={() => setIsSidebarOpen(true)}
              className="md:hidden rounded-full text-theme-text-muted hover:bg-theme-bg/50 hover:text-theme-text transition-colors focus:outline-none flex items-center justify-center"
              title="Open sidebar"
            >
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4 h-4">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
              </svg>
            </button>
          )}
          <button
            type="button"
            onClick={() => navigate('/chat')}
            className="rounded-full text-theme-text-muted hover:bg-theme-bg/50 hover:text-theme-text transition-colors focus:outline-none flex items-center justify-center"
            title="Back to chat"
          >
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4 h-4">
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
            </svg>
          </button>
          <h1 className="text-xs font-semibold text-theme-text select-none">Providers</h1>
        </div>
      </header>

      <div className="h-full overflow-y-auto pt-14">
      <div className="w-full max-w-5xl mx-auto px-4 sm:px-6 pb-12 space-y-6">
        <p className="text-xs text-theme-text-muted leading-relaxed">
          Your free-tier budget across every provider you've configured a key for.
        </p>

        {loading && <p className="text-xs text-theme-text-muted">Loading…</p>}
        {error && <p className="text-xs text-red-500">{error}</p>}

        {data && (
          <>
            {/* Headline budget -- None means "no capped endpoint configured",
                distinct from 0 (exhausted). Rendered as two different, honest
                states rather than collapsing both into "0 tokens". */}
            <div className="bg-theme-surface border border-theme-border/50 rounded-xl p-4">
              <p className="text-[10px] font-semibold uppercase tracking-widest text-theme-text-muted mb-1">
                Free tokens remaining today
              </p>
              {data.total_tokens_remaining_today != null ? (
                <p className="text-2xl sm:text-3xl font-semibold text-theme-text">
                  {formatTokens(data.total_tokens_remaining_today)}
                </p>
              ) : (
                <p className="text-xs text-theme-text-muted italic">
                  No endpoints with a published daily token cap yet — add a key for a
                  provider that publishes one (e.g. Groq, Cerebras) to see a number here.
                </p>
              )}
              {data.uncapped_providers.length > 0 && (
                <p className="text-[10px] text-theme-text-muted mt-2">
                  Also configured, no published cap:{' '}
                  {data.uncapped_providers.map(formatProviderName).join(', ')}
                </p>
              )}
            </div>

            {data.rows.length === 0 ? (
              <p className="text-xs text-theme-text-muted">
                No provider keys configured yet. Add one in Settings to see your free-tier
                budget here.
              </p>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {data.rows.map((row) => (
                  <ProviderCard key={row.endpoint_id} row={row} />
                ))}
              </div>
            )}
          </>
        )}
      </div>
      </div>
    </div>
  )
}
