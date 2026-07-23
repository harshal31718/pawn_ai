import { useNavigate, useOutletContext } from 'react-router-dom'
import SettingsPageComponent from '../components/SettingsPage'
import { useAuth } from '../contexts/AuthContext'
import { useAppContext } from '../contexts/AppContext'
import type { LayoutContext } from './Layout'

export default function SettingsPage() {
  const navigate = useNavigate()
  const { store, isSidebarOpen, setIsSidebarOpen } = useOutletContext<LayoutContext>()
  const { user, logout } = useAuth()
  const {
    theme,
    setTheme,
    displayName,
    handleSaveDisplayName,
    userBubbleColor,
    handleChangeUserBubble,
    aiBubbleColor,
    handleChangeAiBubble,
    backgroundEffect,
    handleToggleBackgroundEffect,
  } = useAppContext()

  return (
    <SettingsPageComponent
      onClose={() => navigate('/chat')}
      isSidebarOpen={isSidebarOpen}
      onOpenSidebar={() => setIsSidebarOpen(true)}
      theme={theme}
      onChangeTheme={setTheme}
      displayName={displayName}
      onSaveDisplayName={handleSaveDisplayName}
      userBubbleColor={userBubbleColor}
      onChangeUserBubble={handleChangeUserBubble}
      aiBubbleColor={aiBubbleColor}
      onChangeAiBubble={handleChangeAiBubble}
      backgroundEffect={backgroundEffect}
      onToggleBackgroundEffect={handleToggleBackgroundEffect}
      conversations={store.conversations}
      email={user?.email || ''}
      onLogout={logout}
    />
  )
}
