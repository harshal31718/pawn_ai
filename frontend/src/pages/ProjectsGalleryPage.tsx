import { useMemo, useState } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { FolderIcon, MagnifierIcon } from '../components/icons'
import type { LayoutContext } from './Layout'

type SortKey = 'updated' | 'name'

const SORT_LABELS: Record<SortKey, string> = {
  updated: 'Last updated',
  name: 'Name',
}

/** F-10 — Projects gallery: a dedicated landing page for all projects (cards
 *  showing name + description), reached by clicking the sidebar's "Projects"
 *  section label. Individual project cards still route to the existing
 *  ProjectPage (/project/:id) unchanged. */
export default function ProjectsGalleryPage() {
  const navigate = useNavigate()
  const { store } = useOutletContext<LayoutContext>()
  const { projects, createProject } = store

  const [query, setQuery] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('updated')
  const [sortMenuOpen, setSortMenuOpen] = useState(false)

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    const list = q
      ? projects.filter(
          (p) => p.name.toLowerCase().includes(q) || (p.description ?? '').toLowerCase().includes(q),
        )
      : projects
    return [...list].sort((a, b) => {
      if (sortKey === 'name') return a.name.localeCompare(b.name)
      return new Date(b.updated_at ?? b.created_at).getTime() - new Date(a.updated_at ?? a.created_at).getTime()
    })
  }, [projects, query, sortKey])

  function handleNewProject() {
    const id = createProject()
    navigate(`/project/${id}`)
  }

  return (
    <div className="flex-1 flex flex-col h-full overflow-y-auto">
      <div className="w-full max-w-4xl mx-auto px-6 pt-16 pb-12">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-semibold text-theme-text">Projects</h1>
          <div className="flex items-center gap-2">
            <div className="relative">
              <button
                type="button"
                onClick={() => setSortMenuOpen((v) => !v)}
                className="flex items-center gap-1.5 px-3 h-9 rounded-lg bg-theme-surface border border-theme-border text-xs font-medium text-theme-text hover:bg-theme-surface-hover transition-colors cursor-pointer"
              >
                <span className="text-theme-text-muted">Sort by</span> {SORT_LABELS[sortKey]}
              </button>
              {sortMenuOpen && (
                <>
                  <div className="fixed inset-0 z-40" onClick={() => setSortMenuOpen(false)} />
                  <div className="absolute right-0 top-full mt-1 z-50 w-40 bg-theme-bg border border-theme-border rounded-lg shadow-lg py-1 text-xs">
                    {(Object.keys(SORT_LABELS) as SortKey[]).map((key) => (
                      <button
                        key={key}
                        type="button"
                        onClick={() => {
                          setSortKey(key)
                          setSortMenuOpen(false)
                        }}
                        className={`w-full text-left px-3 py-1.5 hover:bg-theme-surface-hover transition-colors cursor-pointer ${
                          key === sortKey ? 'font-semibold text-theme-text' : 'text-theme-text-muted'
                        }`}
                      >
                        {SORT_LABELS[key]}
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
            <button
              type="button"
              onClick={handleNewProject}
              className="px-3 h-9 rounded-lg bg-theme-brand text-theme-brand-text text-xs font-semibold hover:opacity-90 transition-opacity cursor-pointer"
            >
              New project
            </button>
          </div>
        </div>

        {/* Search */}
        <div className="relative mb-6">
          <MagnifierIcon className="w-4 h-4 text-theme-text-muted absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search projects..."
            className="w-full h-10 pl-9 pr-3 rounded-xl text-sm bg-theme-surface border border-theme-border text-theme-text placeholder-theme-text-muted focus:outline-none focus:ring-1 focus:ring-theme-border transition-colors"
          />
        </div>

        {/* Cards */}
        {filtered.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-16 text-theme-text-muted select-none">
            <FolderIcon className="w-6 h-6 opacity-40" />
            <span className="text-sm">{query ? 'No projects match your search' : 'No projects yet'}</span>
            {!query && <span className="text-xs opacity-60">Click "New project" to start one</span>}
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {filtered.map((project) => (
              <button
                key={project.id}
                type="button"
                onClick={() => navigate(`/project/${project.id}`)}
                className="text-left flex flex-col gap-1.5 p-4 rounded-xl bg-theme-surface/60 border border-theme-border/60 hover:bg-theme-surface-hover hover:border-theme-border transition-all cursor-pointer min-h-[104px]"
              >
                <span className="text-sm font-semibold uppercase tracking-wide text-theme-text truncate">
                  {project.name}
                </span>
                {project.description ? (
                  <span className="text-xs text-theme-text-muted line-clamp-2 flex-1">{project.description}</span>
                ) : (
                  <span className="flex-1" />
                )}
                <span className="text-[10px] text-theme-text-muted/70 mt-1">
                  {new Date(project.updated_at ?? project.created_at).toLocaleDateString(undefined, {
                    month: 'short',
                    day: 'numeric',
                  })}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
