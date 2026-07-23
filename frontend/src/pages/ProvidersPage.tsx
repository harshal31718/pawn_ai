import { useEffect, useState } from 'react'
import { useNavigate, useOutletContext, useSearchParams } from 'react-router-dom'
import { fetchFreeTiers, getAdminStats, type FreeTiersResponse, type ProviderUsageRow } from '../api/client'
import { useAppContext } from '../contexts/AppContext'
import { useAuth } from '../contexts/AuthContext'
import ApiKeysSection from '../components/ApiKeysSection'
import PoolKeysSection from '../components/PoolKeysSection'
import TabHeaderCard from '../components/TabHeaderCard'
import ModelSwitcher from '../components/ModelSwitcher'
import type { LayoutContext } from './Layout'

type ProvidersTab = 'models' | 'providers' | 'providers-pool'

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

/** Models tab table. One row per MODEL (not per model+provider pair): a
 *  model with several provider endpoints (e.g. llama-3.3-70b has 7) still
 *  gets exactly one row, with every provider serving it listed together in
 *  the Providers column. TPM/RPM/the progress bar all come from the
 *  "primary" endpoint -- the one with the lowest `priority` number, i.e.
 *  the one the resolver actually tries first -- since those numbers are
 *  inherently per-endpoint and one row can't show all of them at once. */
function groupRowsByModel(rows: ProviderUsageRow[]) {
  const byModel = new Map<string, ProviderUsageRow[]>()
  for (const row of rows) {
    const group = byModel.get(row.model_id)
    if (group) group.push(row)
    else byModel.set(row.model_id, [row])
  }
  return Array.from(byModel.values()).map((group) => {
    const primary = [...group].sort((a, b) => a.priority - b.priority)[0]
    const providers = group.map((r) => r.provider)
    return { modelId: primary.model_id, displayName: primary.display_name, providers, primary }
  })
}

function ModelsTable({ rows, search }: { rows: ProviderUsageRow[]; search: string }) {
  const allModels = groupRowsByModel(rows)
  const query = search.trim().toLowerCase()
  const models = query
    ? allModels.filter(
      (m) =>
        m.displayName.toLowerCase().includes(query) ||
        m.providers.some((p) => p.toLowerCase().includes(query) || formatProviderName(p).toLowerCase().includes(query)),
    )
    : allModels

  if (allModels.length === 0) {
    return (
      <p className="p-3 text-xs text-theme-text-muted">
        No provider keys configured yet. Add one under the Providers tab to see models here.
      </p>
    )
  }

  if (models.length === 0) {
    return <p className="p-3 text-xs text-theme-text-muted">No models match "{search}".</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-theme-border/50 text-[10px] uppercase tracking-wide text-theme-text">
            <th className="text-left font-semibold px-3 py-2">Name</th>
            <th className="text-left font-semibold px-3 py-2">Providers</th>
            <th className="text-left font-semibold px-3 py-2 cursor-help" title="Tokens per minute">TPM</th>
            <th className="text-left font-semibold px-3 py-2 cursor-help" title="Requests per minute">RPM</th>
            <th className="text-left font-semibold px-3 py-2 cursor-help" title="Requests per day">RPD</th>
            <th className="text-left font-semibold px-3 py-2 w-40">Rate Limit</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-theme-border/30">
          {models.map(({ modelId, displayName, providers, primary }) => (
            <tr key={modelId}>
              <td className="px-3 py-2 font-medium text-theme-text whitespace-nowrap">{displayName}</td>
              <td className="px-3 py-2 text-theme-text-muted">
                {providers.length <= 2
                  ? providers.map(formatProviderName).join(', ')
                  : `${providers.slice(0, 2).map(formatProviderName).join(', ')}, +${providers.length - 2}`}
              </td>
              <td className="px-3 py-2 text-theme-text-muted whitespace-nowrap">
                {primary.tpm_limit != null ? `${formatTokens(primary.tpm_used)} / ${formatTokens(primary.tpm_limit)}` : '—'}
              </td>
              <td className="px-3 py-2 text-theme-text-muted whitespace-nowrap">
                {primary.rpm_limit != null ? `${primary.rpm_used} / ${primary.rpm_limit}` : '—'}
              </td>
              <td className="px-3 py-2 text-theme-text-muted whitespace-nowrap">
                {primary.rpd_limit != null ? `${primary.rpd_used} / ${primary.rpd_limit}` : '—'}
              </td>
              <td className="px-3 py-2">
                {primary.has_published_cap && primary.tpd_limit ? (
                  <div className="space-y-1">
                    <BudgetBar used={primary.tpd_used} limit={primary.tpd_limit} />
                    <p className="text-[9px] text-theme-text-muted whitespace-nowrap">
                      {formatTokens(primary.tpd_remaining ?? 0)} left
                    </p>
                  </div>
                ) : (
                  <span className="text-[10px] text-theme-text-muted">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
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
  const { refreshKeys, availableModels, defaultModel, handleSaveDefaultModel, providers } = useAppContext()
  const { user } = useAuth()
  const [searchParams] = useSearchParams()
  const initialTab = searchParams.get('tab')
  const [tab, setTab] = useState<ProvidersTab>(
    initialTab === 'providers' || initialTab === 'providers-pool' ? initialTab : 'models',
  )
  const [data, setData] = useState<FreeTiersResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [modelsSearch, setModelsSearch] = useState('')
  const [providersSearch, setProvidersSearch] = useState('')
  const [adminSearch, setAdminSearch] = useState('')
  const [registeredUsers, setRegisteredUsers] = useState<number | null>(null)

  // Counts for each tab's col-2 search placeholder -- computed straight from
  // the registry (already in context), no extra fetch needed.
  const providerRowsCount =
    providers.filter((p) => p.capabilities.includes('chat') || p.capabilities.includes('internet')).length + 2 // + Drive + Kaggle
  const poolProvidersCount = providers.filter((p) => p.type === 'pool').length

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

  useEffect(() => {
    if (!user?.is_admin) return
    getAdminStats()
      .then((stats) => setRegisteredUsers(stats.registered_users))
      .catch(() => { })
  }, [user?.is_admin])

  // Re-sync the active tab if the ?tab= param changes while this page is
  // already mounted (e.g. clicking the Admin pill while already on
  // /providers doesn't remount the component, so the initial useState value
  // alone wouldn't pick up the new param).
  useEffect(() => {
    const t = searchParams.get('tab')
    if (t === 'providers' || t === 'providers-pool') setTab(t)
  }, [searchParams])

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden relative">
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

      {/* Tab tray + the active tab's search header live in a truly static
          (non-scrolling) area -- no `sticky`, no z-index/offset math, no
          scroll-triggered repaint. Only the rows/table below scroll, inside
          their own independent overflow-y-auto region. */}
      <div className="flex-1 min-h-0 flex flex-col overflow-hidden pt-14">
        <div className="w-full max-w-5xl mx-auto px-4 sm:px-6 pt-3 space-y-3 shrink-0">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-1 bg-theme-surface border border-theme-border/50 rounded-xl p-1 w-fit">
              {(
                [
                  'models',
                  'providers',
                  // Admin-only -- gated the same way Sidebar.tsx gates its Admin
                  // nav entry (UX only; the real control is backend
                  // require_admin on every /admin/pool-keys route).
                  ...(user?.is_admin ? (['providers-pool'] as const) : []),
                ] as const
              ).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setTab(t)}
                  className={`px-4 py-1.5 text-[11px] font-semibold uppercase tracking-wide rounded-lg transition-colors cursor-pointer ${tab === t
                    ? 'bg-theme-bg text-theme-text'
                    : 'text-theme-text-muted hover:text-theme-text'
                    }`}
                >
                  {t === 'models' ? 'Models' : t === 'providers' ? 'Providers (BYOK)' : 'Admin'}
                </button>
              ))}
            </div>

            <ModelSwitcher
              selected={defaultModel}
              onChange={handleSaveDefaultModel}
              models={availableModels}
              triggerLabel="Default Model"
            />
          </div>

          {tab === 'models' ? (
            <TabHeaderCard
              message="One row per model, TPM/RPM/daily budget from its primary (highest-priority) provider."
              search={modelsSearch}
              onSearchChange={setModelsSearch}
              searchPlaceholder="Search models…"
              value={data?.total_tokens_remaining_today != null ? formatTokens(data.total_tokens_remaining_today) : '—'}
              label="Tokens remaining today"
            />
          ) : tab === 'providers' ? (
            <TabHeaderCard
              message="Bring your own providers. Keys are encrypted and never shown again after saving."
              search={providersSearch}
              onSearchChange={setProvidersSearch}
              searchPlaceholder={`Search ${providerRowsCount} providers…`}
              value={data ? new Set(data.rows.map((r) => r.model_id)).size : '—'}
              label="Models Unlocked"
            />
          ) : (
            <TabHeaderCard
              message="Manage the pool providers"
              search={adminSearch}
              onSearchChange={setAdminSearch}
              searchPlaceholder={`Search ${poolProvidersCount} providers…`}
              value={registeredUsers ?? '—'}
              label="Users Registered"
            />
          )}
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto">
          <div className="w-full max-w-5xl mx-auto px-4 sm:px-6 pt-3 pb-12">
            {tab === 'models' ? (
              <div className="bg-theme-surface border border-theme-border/50 rounded-xl overflow-hidden">
                {loading && <p className="p-3 text-xs text-theme-text-muted">Loading…</p>}
                {error && <p className="p-3 text-xs text-red-500">{error}</p>}
                {data && <ModelsTable rows={data.rows} search={modelsSearch} />}
              </div>
            ) : tab === 'providers' ? (
              <ApiKeysSection
                search={providersSearch}
                onKeysChanged={() => {
                  refreshKeys()
                  refresh()
                }}
              />
            ) : (
              <PoolKeysSection search={adminSearch} />
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
