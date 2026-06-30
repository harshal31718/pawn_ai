import { createContext, useContext, useState, useEffect, type ReactNode } from 'react'
import { BASE_URL } from '../api/client'

export interface AuthUser {
  id: string
  email: string
  name: string
  picture: string
}

interface AuthContextValue {
  user: AuthUser | null
  token: string | null
  isAuthenticated: boolean
  login: () => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('pawn-token'))
  const [user, setUser] = useState<AuthUser | null>(() => {
    const saved = localStorage.getItem('pawn-user')
    if (!saved) return null
    try { return JSON.parse(saved) } catch { return null }
  })

  // Handle OAuth callback redirect: /?token=...&user=...
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const callbackToken = params.get('token')
    const callbackUser = params.get('user')
    if (callbackToken && callbackUser) {
      try {
        const parsed: AuthUser = JSON.parse(decodeURIComponent(callbackUser))
        localStorage.setItem('pawn-token', callbackToken)
        localStorage.setItem('pawn-user', JSON.stringify(parsed))
        setToken(callbackToken)
        setUser(parsed)
        window.history.replaceState({}, '', '/')
      } catch {
        // Malformed callback — ignore
      }
    }
  }, [])

  async function login() {
    const res = await fetch(`${BASE_URL}/auth/login`)
    if (!res.ok) throw new Error('Auth endpoint unavailable')
    const { auth_url } = await res.json()
    window.location.href = auth_url
  }

  function logout() {
    localStorage.removeItem('pawn-token')
    localStorage.removeItem('pawn-user')
    setToken(null)
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, token, isAuthenticated: !!token && !!user, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
