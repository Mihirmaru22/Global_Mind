import { Download, Menu, PanelLeftOpen } from 'lucide-react'
import { useLocation } from 'react-router-dom'
import { useAppStore } from '../store/store.js'
import Button from './Button.jsx'
import { exportChatPdf } from '../utils/exportChatPdf.js'

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
  const toggleSidebarCollapse = useAppStore((state) => state.toggleSidebarCollapse)
  const sidebarCollapsed = useAppStore((state) => state.sidebarCollapsed)
  const activeChatId = useAppStore((state) => state.activeChatId)
  const chats = useAppStore((state) => state.chats)
  const messagesByChatId = useAppStore((state) => state.messagesByChatId)
  const title = titleMap[location.pathname] || 'Local Mind'
  const hideTitle = location.pathname === '/' || location.pathname === '/chat' || location.pathname === '/settings'
  const activeChat = chats.find((chat) => chat.id === activeChatId)
  const messages = messagesByChatId[activeChatId] || []
  const exportableMessages = messages.filter((message) => message.status !== 'loading')
  const canExport = Boolean(activeChat) && exportableMessages.length > 0

  const handleExport = () => {
    if (!canExport) return
    exportChatPdf(activeChat, exportableMessages)
  }

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
        {!sidebarCollapsed ? null : (
          <button
            type="button"
            className="icon-button desktop-toggle"
            onClick={toggleSidebarCollapse}
            aria-label="Open sidebar"
          >
            <PanelLeftOpen size={18} />
          </button>
        )}
        {hideTitle ? null : <h1 className="header__title">{title}</h1>}
      </div>

      <div className="header__actions">
        <button
          className="icon-button"
          type="button"
          aria-label="Export chat as PDF"
          onClick={handleExport}
          disabled={!canExport}
        >
          <Download size={18} />
        </button>
      </div>
    </header>
  )
}
