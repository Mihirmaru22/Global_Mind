import { HelpCircle, Menu, UserCircle2 } from 'lucide-react'
import { useLocation } from 'react-router-dom'
import { useAppStore } from '../store/store.js'
import Button from './Button.jsx'

const titleMap = {
  '/': 'Chat',
  '/chat': 'Chat',
  '/documents': 'Documents',
  '/settings': 'Settings',
  '/about': 'About',
}

export default function Header() {
  const location = useLocation()
  const toggleSidebar = useAppStore((state) => state.toggleSidebar)
  const title = titleMap[location.pathname] || 'Local Mind'

  return (
    <header className="header">
      <div className="header__left">
        <Button
          type="button"
          variant="secondary"
          className="icon-button mobile-toggle"
          onClick={toggleSidebar}
          aria-label="Open navigation"
        >
          <Menu size={18} />
        </Button>
        <h1 className="header__title">{title}</h1>
      </div>

      <div className="header__actions">
        <button className="icon-button" type="button" aria-label="Help">
          <HelpCircle size={18} />
        </button>
        <button className="icon-button" type="button" aria-label="Profile">
          <UserCircle2 size={18} />
        </button>
      </div>
    </header>
  )
}
