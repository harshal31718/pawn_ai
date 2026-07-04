import { useEffect, useState } from 'react'
import type { Theme } from '../components/ThemeToggle'

/**
 * Shared theme state: 'system' | 'light' | 'dark', persisted to localStorage
 * under 'pawn-theme', with the resulting `.dark` class applied to <html>.
 * frontend/index.html's inline bootstrap script sets that class before React
 * ever mounts (avoiding a flash of the wrong theme); this hook owns the
 * ongoing toggle interaction and keeps localStorage in sync afterward.
 */
export function useThemePreference() {
  const [theme, setTheme] = useState<Theme>(() => {
    const saved = localStorage.getItem('pawn-theme')
    if (saved === 'light' || saved === 'dark' || saved === 'system') return saved
    return 'system'
  })

  const isDark =
    theme === 'dark' || (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)

  useEffect(() => {
    const dark =
      theme === 'dark' || (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)
    document.documentElement.classList.toggle('dark', dark)
    localStorage.setItem('pawn-theme', theme)
  }, [theme])

  return { theme, setTheme, isDark }
}
