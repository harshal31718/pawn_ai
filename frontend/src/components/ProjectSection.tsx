import { useNavigate } from 'react-router-dom'
import SidebarTitleRow from './SidebarTitleRow'
import { FolderIcon } from './icons'

/** "Projects" sidebar entry — a single title row that navigates to the
 *  Projects gallery page. Individual project names are no longer listed
 *  inline in the sidebar (removed per user feedback); the gallery page is
 *  the one place they're browsed. Lives in Sidebar.tsx's static top block
 *  (alongside Search/New chat/Image Lab) rather than the scrollable
 *  Projects/Chats region, so it renders bare here -- no wrapping div,
 *  sticky positioning, or padding of its own; the parent block supplies
 *  that. Split out of Sidebar.tsx per .claude/rules/frontend.md (components
 *  over ~150 lines get split). */
export default function ProjectSection({ expanded = true, onNavigated, isActive = false }: { expanded?: boolean; onNavigated?: () => void; isActive?: boolean }) {
  const navigate = useNavigate()

  return (
    <SidebarTitleRow
      expanded={expanded}
      icon={FolderIcon}
      label="Projects"
      onClick={() => {
        navigate('/projects')
        onNavigated?.()
      }}
      isActive={isActive}
    />
  )
}
