import {
  Library,
  LogOut,
  MessageSquare,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  PencilLine,
  Pin,
  PinOff,
  Settings,
  SquarePen,
  Trash2,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useAppStore } from '../store/store.js'
import { useDialogA11y } from '../utils/useDialogA11y.js'

function ChatItemRow({ chat, isActive, isMenuOpen, onSelect, onToggleMenu }) {
  return (
    <div className={`chat-item ${isActive ? 'chat-item--active' : ''} ${isMenuOpen ? 'chat-item--menu-open' : ''}`}>
      <button type="button" className="chat-item__main" onClick={onSelect}>
        <MessageSquare size={14} className="chat-item__icon" aria-hidden="true" />
        <span className="chat-item__title-window">
          <span className="chat-item__title">{chat.title}</span>
        </span>
      </button>

      <div className="chat-item__actions">
        <button
          type="button"
          className="chat-item__menu-trigger"
          aria-label={`Chat actions for ${chat.title}`}
          onClick={(event) => onToggleMenu(chat, event)}
        >
          <MoreHorizontal size={15} />
        </button>
      </div>
    </div>
  )
}

export default function Sidebar() {
  const currentUser = useAppStore((state) => state.currentUser)
  const logoutUser = useAppStore((state) => state.logoutUser)
  const chats = useAppStore((state) => state.chats)
  const activeChatId = useAppStore((state) => state.activeChatId)
  const selectChat = useAppStore((state) => state.selectChat)
  const newChat = useAppStore((state) => state.newChat)
  const renameChat = useAppStore((state) => state.renameChat)
  const deleteChat = useAppStore((state) => state.deleteChat)
  const pinnedChatIds = useAppStore((state) => state.pinnedChatIds)
  const togglePinChat = useAppStore((state) => state.togglePinChat)
  const sidebarOpen = useAppStore((state) => state.sidebarOpen)
  const sidebarCollapsed = useAppStore((state) => state.sidebarCollapsed)
  const toggleSidebarCollapse = useAppStore((state) => state.toggleSidebarCollapse)
  const closeSidebar = useAppStore((state) => state.closeSidebar)
  const chatsLoading = useAppStore((state) => state.chatsLoading)

  const navigate = useNavigate()
  const location = useLocation()
  const isChatRouteActive = location.pathname === '/' || location.pathname === '/chat'
  const [openMenuId, setOpenMenuId] = useState(null)
  const [menuPosition, setMenuPosition] = useState(null)
  const [dialog, setDialog] = useState({ type: null, chat: null, value: '' })
  const dialogRef = useRef(null)
  const dialogInputRef = useRef(null)
  const dialogCancelRef = useRef(null)

  const closeDialog = () => setDialog({ type: null, chat: null, value: '' })
  const closeMenu = () => {
    setOpenMenuId(null)
    setMenuPosition(null)
  }

  useDialogA11y({
    isOpen: Boolean(dialog.type),
    onClose: closeDialog,
    containerRef: dialogRef,
    initialFocusRef: dialog.type === 'rename' ? dialogInputRef : dialogCancelRef,
  })

  useEffect(() => {
    if (!openMenuId) return undefined
    const handleViewportChange = () => closeMenu()
    window.addEventListener('scroll', handleViewportChange, true)
    window.addEventListener('resize', handleViewportChange)
    return () => {
      window.removeEventListener('scroll', handleViewportChange, true)
      window.removeEventListener('resize', handleViewportChange)
    }
  }, [openMenuId])

  const { pinned, recent } = useMemo(() => {
    const pinnedList = []
    const recentList = []

    for (const chat of chats) {
      if (pinnedChatIds.has(chat.id)) pinnedList.push(chat)
      else recentList.push(chat)
    }

    return { pinned: pinnedList, recent: recentList }
  }, [chats, pinnedChatIds])

  const handleNewChat = async () => {
    closeMenu()
    await newChat()
    navigate('/chat')
  }

  const handleRename = (chat) => {
    closeMenu()
    setDialog({ type: 'rename', chat, value: chat.title })
  }

  const handleDelete = (chat) => {
    closeMenu()
    setDialog({ type: 'delete', chat, value: '' })
  }

  const handlePin = (chat) => {
    closeMenu()
    togglePinChat(chat.id)
  }

  const toggleChatMenu = (chat, event) => {
    const triggerRect = event.currentTarget.getBoundingClientRect()
    const menuWidth = 172
    const menuHeight = 132
    const viewportWidth = window.innerWidth
    const viewportHeight = window.innerHeight
    const nextLeft = Math.max(12, Math.min(triggerRect.right - menuWidth, viewportWidth - menuWidth - 12))
    const enoughRoomBelow = triggerRect.bottom + menuHeight + 12 <= viewportHeight

    if (openMenuId === chat.id) {
      closeMenu()
      return
    }

    setOpenMenuId(chat.id)
    setMenuPosition(
      enoughRoomBelow
        ? { top: triggerRect.bottom + 8, left: nextLeft }
        : { bottom: viewportHeight - triggerRect.top + 8, left: nextLeft },
    )
  }

  const confirmDialog = async () => {
    if (!dialog.chat) return
    if (dialog.type === 'rename') {
      const nextTitle = dialog.value.trim()
      if (!nextTitle || nextTitle === dialog.chat.title) {
        closeDialog()
        return
      }
      await renameChat(dialog.chat.id, nextTitle)
    }
    if (dialog.type === 'delete') {
      await deleteChat(dialog.chat.id)
      navigate('/chat')
    }
    closeDialog()
  }

  const activeMenuChat = chats.find((chat) => chat.id === openMenuId)
  const activeMenuIsPinned = activeMenuChat ? pinnedChatIds.has(activeMenuChat.id) : false

  const renderChatList = (list) =>
    list.map((chat) => (
      <ChatItemRow
        key={chat.id}
        chat={chat}
        isActive={isChatRouteActive && activeChatId === chat.id}
        isMenuOpen={openMenuId === chat.id}
        onSelect={async () => {
          await selectChat(chat.id)
          navigate('/chat')
        }}
        onToggleMenu={toggleChatMenu}
      />
    ))

  return (
    <>
      <aside className="sidebar-rail" aria-label="Collapsed sidebar">
        <button
          type="button"
          className="sidebar-rail__btn"
          onClick={toggleSidebarCollapse}
          title="Expand sidebar"
          aria-label="Expand sidebar"
        >
          <PanelLeftOpen size={18} />
        </button>

        <button
          type="button"
          className="sidebar-rail__btn sidebar-rail__new-btn"
          onClick={handleNewChat}
          title="New chat"
          aria-label="New chat"
        >
          <SquarePen size={18} />
        </button>

        <NavLink
          to="/documents"
          className={({ isActive }) => `sidebar-rail__btn ${isActive ? 'sidebar-rail__btn--active' : ''}`}
          title="Documents"
          aria-label="Documents"
        >
          <Library size={18} />
        </NavLink>

        <div className="sidebar-rail__spacer" />

        <NavLink
          to="/settings"
          className={({ isActive }) => `sidebar-rail__btn ${isActive ? 'sidebar-rail__btn--active' : ''}`}
          title="Settings"
          aria-label="Settings"
        >
          <Settings size={18} />
        </NavLink>

        {currentUser && (
          <button
            type="button"
            className="sidebar-rail__btn"
            onClick={logoutUser}
            title={`Log out (${currentUser})`}
            aria-label={`Log out (${currentUser})`}
            style={{ color: 'var(--color-danger)' }}
          >
            <LogOut size={18} />
          </button>
        )}
      </aside>

      <aside className="sidebar" data-open={sidebarOpen} data-collapsed={sidebarCollapsed}>
        <div className="brand">
          <div className="brand__row">
            <div className="brand__lockup">
              <div className="brand__type">
                <h1 className="brand__title">Local Mind</h1>
                <p className="brand__subtitle">Private data intelligence</p>
              </div>
            </div>
            <button
              type="button"
              className="icon-button desktop-toggle"
              onClick={toggleSidebarCollapse}
              aria-label="Collapse sidebar"
            >
              <PanelLeftClose size={18} />
            </button>
          </div>
        </div>

        <div className="sidebar__new-chat-row">
          <button type="button" className="new-chat-action" onClick={handleNewChat}>
            <SquarePen size={16} />
            <span>New chat</span>
          </button>
        </div>

        <nav className="sidebar__documents-row">
          <NavLink
            to="/documents"
            className={({ isActive }) => `nav-item nav-item--documents ${isActive ? 'nav-item--active' : ''}`}
            onClick={closeSidebar}
          >
            <Library size={16} />
            <span>Documents</span>
          </NavLink>
        </nav>

        <div className="sidebar__scroll scrollbar-auto">
          {chatsLoading ? (
            <section className="sidebar__section sidebar__section--grow">
              <p className="section-title">Recent chats</p>
              <div className="chat-list" aria-busy="true" aria-label="Loading chats">
                {[0, 1, 2, 3].map((index) => (
                  <div key={index} className="chat-item-skeleton" style={{ animationDelay: `${index * 80}ms` }} />
                ))}
              </div>
            </section>
          ) : (
            <>
              {pinned.length > 0 ? (
                <section className="sidebar__section">
                  <p className="section-title">Pinned</p>
                  <div className="chat-list">{renderChatList(pinned)}</div>
                </section>
              ) : null}

              <section className="sidebar__section sidebar__section--grow">
                <p className="section-title">Recent chats</p>
                <div className="chat-list">
                  {recent.length ? renderChatList(recent) : (
                    pinned.length === 0 ? <p className="chat-list__empty">No chats yet</p> : null
                  )}
                </div>
              </section>
            </>
          )}
        </div>

        <footer className="sidebar__footer" style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {currentUser && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '8px 10px',
                borderRadius: 'var(--radius-control)',
                background: 'var(--color-control)',
                border: '1px solid var(--color-border)',
                fontSize: '13px',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', overflow: 'hidden' }}>
                <div
                  style={{
                    width: '24px',
                    height: '24px',
                    borderRadius: '50%',
                    background: 'var(--accent)',
                    color: 'var(--accent-on)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: '11px',
                    fontWeight: 700,
                    textTransform: 'uppercase',
                    flexShrink: 0,
                  }}
                >
                  {currentUser.slice(0, 1)}
                </div>
                <span
                  style={{
                    fontWeight: 600,
                    color: 'var(--color-text)',
                    textTransform: 'capitalize',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {currentUser}
                </span>
              </div>
              <button
                type="button"
                onClick={logoutUser}
                title="Log out"
                aria-label="Log out"
                style={{
                  background: 'transparent',
                  border: 'none',
                  cursor: 'pointer',
                  padding: '4px',
                  color: 'var(--color-text-muted)',
                  display: 'flex',
                  alignItems: 'center',
                  borderRadius: '4px',
                  transition: 'color 0.15s ease',
                }}
                onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--color-danger)')}
                onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--color-text-muted)')}
              >
                <LogOut size={15} />
              </button>
            </div>
          )}
          <NavLink
            to="/settings"
            className={({ isActive }) => `nav-item nav-item--footer ${isActive ? 'nav-item--active' : ''}`}
            onClick={closeSidebar}
          >
            <Settings size={16} />
            <span>Settings</span>
          </NavLink>
        </footer>
      </aside>

      {openMenuId && activeMenuChat ? createPortal(
        <div className="chat-menu-backdrop" role="presentation" onClick={closeMenu}>
          <div
            className="chat-menu"
            role="menu"
            aria-label="Chat actions"
            style={menuPosition ?? undefined}
            onClick={(event) => event.stopPropagation()}
          >
            <button type="button" className="chat-menu__item" onClick={() => handlePin(activeMenuChat)} role="menuitem">
              {activeMenuIsPinned ? <PinOff size={14} /> : <Pin size={14} />}
              <span>{activeMenuIsPinned ? 'Unpin' : 'Pin'}</span>
            </button>
            <button type="button" className="chat-menu__item" onClick={() => handleRename(activeMenuChat)} role="menuitem">
              <PencilLine size={14} />
              <span>Rename</span>
            </button>
            <button
              type="button"
              className="chat-menu__item chat-menu__item--danger"
              onClick={() => handleDelete(activeMenuChat)}
              role="menuitem"
            >
              <Trash2 size={14} />
              <span>Delete</span>
            </button>
          </div>
        </div>,
        document.body,
      ) : null}

      {sidebarOpen ? (
        <button type="button" className="sidebar-backdrop" onClick={closeSidebar} aria-label="Close navigation" />
      ) : null}

      {dialog.type ? (
        <div className="dialog-backdrop" role="presentation" onClick={closeDialog}>
          <div
            ref={dialogRef}
            className="dialog-card"
            role="dialog"
            aria-modal="true"
            aria-labelledby="chat-dialog-title"
            aria-describedby="chat-dialog-desc"
            onClick={(event) => event.stopPropagation()}
          >
            <p className="dialog-card__eyebrow">Chat action</p>
            <h3 id="chat-dialog-title" className="dialog-card__title">
              {dialog.type === 'rename' ? 'Rename chat' : 'Delete chat'}
            </h3>
            <p id="chat-dialog-desc" className="dialog-card__text">
              {dialog.type === 'rename'
                ? 'Give this conversation a new name.'
                : `This will remove "${dialog.chat?.title}" from your chats.`}
            </p>
            {dialog.type === 'rename' ? (
              <input
                ref={dialogInputRef}
                className="dialog-card__input"
                value={dialog.value}
                onChange={(event) => setDialog((current) => ({ ...current, value: event.target.value }))}
                placeholder="Chat title"
              />
            ) : null}
            <div className="dialog-card__actions">
              <button ref={dialogCancelRef} type="button" className="secondary-button" onClick={closeDialog}>
                Cancel
              </button>
              <button
                type="button"
                className={`primary-button ${dialog.type === 'delete' ? 'primary-button--danger' : ''}`}
                onClick={confirmDialog}
              >
                {dialog.type === 'rename' ? 'Save changes' : 'Delete chat'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  )
}
