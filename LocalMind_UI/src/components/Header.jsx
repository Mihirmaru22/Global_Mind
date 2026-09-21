import { useEffect, useRef, useState } from 'react'
import { Download, FileText, Menu } from 'lucide-react'
import { useLocation } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { toast } from 'sonner'
import { useAppStore } from '../store/store.js'
import { exportChatTranscript } from '../utils/pdfExport.js'

function useDismiss(ref, onDismiss, active) {
  useEffect(() => {
    if (!active) return undefined

    const onPointer = (event) => {
      if (ref.current && !ref.current.contains(event.target)) onDismiss()
    }
    const onKey = (event) => {
      if (event.key === 'Escape') onDismiss()
    }

    document.addEventListener('mousedown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [ref, onDismiss, active])
}

export default function Header() {
  const location = useLocation()
  const activeChatId = useAppStore((state) => state.activeChatId)
  const chats = useAppStore((state) => state.chats)
  const messagesByChatId = useAppStore((state) => state.messagesByChatId)
  const sidebarOpen = useAppStore((state) => state.sidebarOpen)
  const toggleSidebar = useAppStore((state) => state.toggleSidebar)
  const [downloadOpen, setDownloadOpen] = useState(false)
  const downloadRef = useRef(null)

  const isChatRoute = location.pathname === '/' || location.pathname === '/chat'
  const activeChat = chats.find((chat) => chat.id === activeChatId)
  const messages = messagesByChatId[activeChatId] || []
  const exportableMessages = messages.filter(
    (message) => message != null && message.status !== 'loading' && message.kind !== 'ingestion',
  )
  const canExport = Boolean(activeChat) && exportableMessages.length > 0
  const pageTitle = isChatRoute
    ? (activeChat?.title || 'LocalMind')
    : location.pathname.slice(1).charAt(0).toUpperCase() + location.pathname.slice(2)

  useDismiss(downloadRef, () => setDownloadOpen(false), downloadOpen)

  const handleTranscript = async () => {
    setDownloadOpen(false)
    if (!canExport) return
    try {
      await exportChatTranscript(activeChat, exportableMessages)
    } catch (error) {
      console.error(error)
      toast.error('Could not export the transcript.')
    }
  }

  return (
    <header className="header">
      <div className="header__left">
        <button
          type="button"
          className="header__menu-btn"
          onClick={toggleSidebar}
          aria-label="Open navigation"
          aria-expanded={sidebarOpen}
        >
          <Menu size={18} />
        </button>
        <div className="header__chat-identity">
          <h1 className="header__chat-title">{pageTitle}</h1>
        </div>
      </div>

      <div className="header__actions">
        {isChatRoute ? (
          <>
            <div className="topbar-download" ref={downloadRef}>
              <button
                type="button"
                className="topbar-btn topbar-btn--icon-only"
                aria-haspopup="menu"
                aria-expanded={downloadOpen}
                aria-label="Download conversation"
                onClick={() => setDownloadOpen((value) => !value)}
                disabled={!canExport}
                title="Download conversation"
              >
                <Download size={15} />
              </button>

              <AnimatePresence>
                {downloadOpen ? (
                  <motion.div
                    className="topbar-menu"
                    role="menu"
                    aria-label="Download options"
                    initial={{ opacity: 0, y: 6, scale: 0.97 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, y: 6, scale: 0.97 }}
                    transition={{ duration: 0.12 }}
                  >
                    <button type="button" className="topbar-menu__item" role="menuitem" onClick={handleTranscript}>
                      <FileText size={14} />
                      <span>
                        <strong>Chat transcript</strong>
                        <em>Formatted conversation with charts</em>
                      </span>
                    </button>
                  </motion.div>
                ) : null}
              </AnimatePresence>
            </div>
          </>
        ) : null}
      </div>
    </header>
  )
}
