import { createContext, useContext, useState, useEffect, type ReactNode } from 'react'
import { BASE_URL } from '../api/client'
import { clearSession } from '../crypto/session'

export interface AuthUser {
  id: string
  email: string
  name: string
  picture: string
  // PAWN 2.0 Phase B.1: carried on the OAuth callback redirect payload, not
  // re-fetched later -- the frontend keys admin UI off this backend flag
  // rather than duplicating the magic admin email client-side.
  is_admin?: boolean
  // Login-change plan (2026-07-23): false until the user replaces their
  // auto-generated password at least once -- drives PasswordNudgeModal.
  // Server-side source of truth, not a client-only flag.
  password_changed?: boolean
}

interface AuthContextValue {
  user: AuthUser | null
  token: string | null
  isAuthenticated: boolean
  login: () => Promise<void>
  loginWithPassword: (email: string, password: string) => Promise<void>
  logout: () => void
  updateUser: (partial: Partial<AuthUser>) => void
  // One-time plaintext reveal after a fresh Google signup -- never persisted
  // to localStorage, cleared by GeneratedPasswordModal's "Done" action.
  generatedPassword: string | null
  clearGeneratedPassword: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('pawn-token'))
  const [user, setUser] = useState<AuthUser | null>(() => {
    const saved = localStorage.getItem('pawn-user')
    if (!saved) return null
    try { return JSON.parse(saved) } catch { return null }
  })
  const [generatedPassword, setGeneratedPassword] = useState<string | null>(null)

  // Shared by the OAuth-callback effect and loginWithPassword -- both land
  // on the exact same {token, user} shape from the backend.
  function applySession(newToken: string, newUser: AuthUser) {
    localStorage.setItem('pawn-token', newToken)
    localStorage.setItem('pawn-user', JSON.stringify(newUser))
    setToken(newToken)
    setUser(newUser)
  }

  // Handle OAuth callback redirect: /?token=...&user=...&generated_password=...
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const callbackToken = params.get('token')
    const callbackUser = params.get('user')
    const callbackGeneratedPassword = params.get('generated_password')
    if (callbackToken && callbackUser) {
      try {
        const parsed: AuthUser = JSON.parse(decodeURIComponent(callbackUser))
        applySession(callbackToken, parsed)
        if (callbackGeneratedPassword) {
          setGeneratedPassword(callbackGeneratedPassword)
        }
        window.history.replaceState({}, '', '/')
      } catch {
        // Malformed callback — ignore
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function login() {
    const res = await fetch(`${BASE_URL}/auth/login`)
    if (!res.ok) throw new Error('Auth endpoint unavailable')
    const { auth_url } = await res.json()
    window.location.href = auth_url
  }

  async function loginWithPassword(email: string, password: string) {
    const res = await fetch(`${BASE_URL}/auth/login-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(body.detail || 'Sign in failed')
    }
    const { token: newToken, user: newUser } = await res.json()
    applySession(newToken, newUser)
  }

  function logout() {
    clearSession() // wipe the in-memory encryption key
    localStorage.removeItem('pawn-token')
    localStorage.removeItem('pawn-user')
    setToken(null)
    setUser(null)
  }

  function updateUser(partial: Partial<AuthUser>) {
    setUser((prev) => {
      if (!prev) return prev
      const next = { ...prev, ...partial }
      localStorage.setItem('pawn-user', JSON.stringify(next))
      return next
    })
  }

  function clearGeneratedPassword() {
    setGeneratedPassword(null)
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        isAuthenticated: !!token && !!user,
        login,
        loginWithPassword,
        logout,
        updateUser,
        generatedPassword,
        clearGeneratedPassword,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
