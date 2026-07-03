import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { AppContextProvider } from './contexts/AppContext'
import LoginPage from './pages/LoginPage'
import PassphraseGate from './pages/PassphraseGate'
import Layout from './pages/Layout'
import ChatPage from './pages/ChatPage'
import SettingsPage from './pages/SettingsPageWrapper'
import ImageLabPage from './pages/ImageLabPageWrapper'

function AppRoutes() {
  const { user } = useAuth()

  return (
    <AppContextProvider userName={user?.name}>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Navigate to="/chat" replace />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/chat/:id" element={<ChatPage />} />
            <Route path="/imagelab" element={<ImageLabPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            {/* Catch-all → redirect to chat */}
            <Route path="*" element={<Navigate to="/chat" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AppContextProvider>
  )
}

function AuthGate() {
  const { isAuthenticated } = useAuth()
  if (!isAuthenticated) return <LoginPage />
  return (
    <PassphraseGate>
      <AppRoutes />
    </PassphraseGate>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <AuthGate />
    </AuthProvider>
  )
}
