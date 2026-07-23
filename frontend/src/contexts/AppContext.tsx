import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import {
  AUTO_MODEL_ID,
  fetchRegistryModels,
  getKeys,
  healthCheck,
  type RegistryModel,
} from '../api/client'
import { useThemePreference } from '../hooks/useThemePreference'

/* ─── types ─── */
type Theme = 'system' | 'light' | 'dark'

interface AppContextValue {
  /* Theme */
  theme: Theme
  setTheme: (t: Theme) => void
  isDark: boolean

  /* Models & Providers */
  models: RegistryModel[]
  configuredProviders: string[]
  availableModels: RegistryModel[]
  refreshKeys: () => void

  /* User preferences */
  displayName: string
  handleSaveDisplayName: (name: string) => void
  defaultModel: string
  handleSaveDefaultModel: (id: string) => void
  userBubbleColor: string
  handleChangeUserBubble: (id: string) => void
  aiBubbleColor: string
  handleChangeAiBubble: (id: string) => void
  backgroundEffect: boolean
  handleToggleBackgroundEffect: () => void
}

const AppContext = createContext<AppContextValue | null>(null)

export function useAppContext() {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useAppContext must be used inside AppContextProvider')
  return ctx
}

export function AppContextProvider({ children, userName }: { children: ReactNode; userName?: string }) {
  /* ── Theme ── */
  const { theme, setTheme, isDark } = useThemePreference()

  /* ── Models & Providers ── */
  const [models, setModels] = useState<RegistryModel[]>([])
  const [configuredProviders, setConfiguredProviders] = useState<string[]>([])

  const availableModels = models.filter((m) =>
    m.providers?.some((p) => configuredProviders.includes(p)),
  )

  function refreshKeys() {
    getKeys()
      .then(setConfiguredProviders)
      .catch((err) => console.error('Failed to fetch configured providers:', err))
  }

  useEffect(() => {
    healthCheck()
      .then((data) => console.log('Backend:', data))
      .catch((err) => console.error('Backend unreachable:', err))

    fetchRegistryModels()
      .then((data) => {
        setModels(data)
      })
      .catch((err) => console.error('Failed to fetch registry models:', err))

    refreshKeys()
  }, [])

  /* ── User preferences ── */
  const [displayName, setDisplayName] = useState(() => userName || localStorage.getItem('pawn-display-name') || 'User')
  // C5: Auto is the default for anyone who hasn't explicitly chosen a model.
  // Previously hardcoded to 'gemini-2.5-flash', which silently pinned every new
  // user to one model regardless of task or which keys they actually hold.
  const [defaultModel, setDefaultModel] = useState(() => localStorage.getItem('pawn-default-model') || AUTO_MODEL_ID)
  const [userBubbleColor, setUserBubbleColor] = useState(() => localStorage.getItem('pawn-user-bubble') || '')
  const [aiBubbleColor, setAiBubbleColor] = useState(() => localStorage.getItem('pawn-ai-bubble') || '')
  const [backgroundEffect, setBackgroundEffect] = useState(() => localStorage.getItem('pawn-bg-effect') !== 'false')

  function handleSaveDisplayName(name: string) {
    setDisplayName(name)
    localStorage.setItem('pawn-display-name', name)
  }

  function handleSaveDefaultModel(modelId: string) {
    setDefaultModel(modelId)
    localStorage.setItem('pawn-default-model', modelId)
  }

  function handleChangeUserBubble(id: string) {
    setUserBubbleColor(id)
    localStorage.setItem('pawn-user-bubble', id)
  }

  function handleChangeAiBubble(id: string) {
    setAiBubbleColor(id)
    localStorage.setItem('pawn-ai-bubble', id)
  }

  function handleToggleBackgroundEffect() {
    setBackgroundEffect((v) => {
      localStorage.setItem('pawn-bg-effect', String(!v))
      return !v
    })
  }

  // Sync bubble color CSS vars
  useEffect(() => {
    const el = document.documentElement
    const PRESETS: Record<string, { bg: string; text: string }> = {
      blue: { bg: '#3b82f6', text: '#ffffff' },
      indigo: { bg: '#4f46e5', text: '#ffffff' },
      violet: { bg: '#7c3aed', text: '#ffffff' },
      teal: { bg: '#0d9488', text: '#ffffff' },
      emerald: { bg: '#059669', text: '#ffffff' },
      rose: { bg: '#e11d48', text: '#ffffff' },
      amber: { bg: '#d97706', text: '#ffffff' },
      slate: { bg: '#475569', text: '#ffffff' },
      black: { bg: '#000000', text: '#ffffff' },
      white: { bg: '#ffffff', text: '#000000' },
    }

    const up = PRESETS[userBubbleColor]
    if (up) {
      el.style.setProperty('--theme-user-bubble', up.bg)
      el.style.setProperty('--theme-user-bubble-text', up.text)
    } else {
      el.style.removeProperty('--theme-user-bubble')
      el.style.removeProperty('--theme-user-bubble-text')
    }

    const ap = PRESETS[aiBubbleColor]
    if (ap) {
      el.style.setProperty('--theme-ai-bubble', ap.bg)
      el.style.setProperty('--theme-ai-bubble-text', ap.text)
    } else {
      el.style.removeProperty('--theme-ai-bubble')
      el.style.removeProperty('--theme-ai-bubble-text')
    }
  }, [userBubbleColor, aiBubbleColor])

  // Coerce model selections when available models change
  useEffect(() => {
    if (availableModels.length === 0) return
    const ids = availableModels.map((m) => m.model_id)
    // C5: 'auto' is a valid selection but is deliberately NOT a registry model,
    // so it must be exempted here -- otherwise this coercion would immediately
    // overwrite Auto with a concrete model on every load.
    if (defaultModel !== AUTO_MODEL_ID && !ids.includes(defaultModel)) {
      handleSaveDefaultModel(AUTO_MODEL_ID)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [availableModels, defaultModel])

  const value: AppContextValue = {
    theme,
    setTheme,
    isDark,
    models,
    configuredProviders,
    availableModels,
    refreshKeys,
    displayName,
    handleSaveDisplayName,
    defaultModel,
    handleSaveDefaultModel,
    userBubbleColor,
    handleChangeUserBubble,
    aiBubbleColor,
    handleChangeAiBubble,
    backgroundEffect,
    handleToggleBackgroundEffect,
  }

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}
