import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { AppContextProvider } from './contexts/AppContext'
import LandingPage from './pages/LandingPage'
import PrivacyPolicyPage from './pages/PrivacyPolicyPage'
import Layout from './pages/Layout'
import ChatPage from './pages/ChatPage'
import ProjectPage from './pages/ProjectPage'
import ProjectsGalleryPage from './pages/ProjectsGalleryPage'
import SettingsPage from './pages/SettingsPageWrapper'
import ImageLabPage from './pages/ImageLabPageWrapper'
import ProvidersPage from './pages/ProvidersPage'
import SignInPage from './pages/SignInPage'
import GeneratedPasswordModal from './components/GeneratedPasswordModal'

/** Pathless guard route: everything nested under it requires auth. */
function RequireAuth() {
  const { isAuthenticated } = useAuth()
  if (!isAuthenticated) return <Navigate to="/" replace />
  return <Outlet />
}

/** Pathless layout route: mounts AppContextProvider + Layout only for the authenticated subtree. */
function AuthedShell() {
  const { user } = useAuth()
  return (
    <AppContextProvider userName={user?.name}>
      {/* Login-change plan: renders nothing unless a fresh Google signup just
          happened (generatedPassword non-null) -- mounted here so it's
          present right after the post-signup redirect lands on /chat. */}
      <GeneratedPasswordModal />
      <Layout />
    </AppContextProvider>
  )
}

function AppRoutes() {
  const { isAuthenticated } = useAuth()
  return (
    <Routes>
      {/* Public — reachable regardless of auth state (required for Google's
          OAuth verification URL checks and for reviewers to load them cold). */}
      <Route path="/" element={isAuthenticated ? <Navigate to="/chat" replace /> : <LandingPage />} />
      <Route path="/privacy" element={<PrivacyPolicyPage />} />
      <Route path="/login" element={isAuthenticated ? <Navigate to="/chat" replace /> : <SignInPage />} />

      <Route element={<RequireAuth />}>
        <Route element={<AuthedShell />}>
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/chat/:id" element={<ChatPage />} />
          <Route path="/projects" element={<ProjectsGalleryPage />} />
          <Route path="/project/:projectId" element={<ProjectPage />} />
          <Route path="/project/:projectId/chat/:id" element={<ChatPage />} />
          <Route path="/imagelab" element={<ImageLabPage />} />
          <Route path="/providers" element={<ProvidersPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
      </Route>

      <Route path="*" element={<Navigate to={isAuthenticated ? '/chat' : '/'} replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </AuthProvider>
  )
}
