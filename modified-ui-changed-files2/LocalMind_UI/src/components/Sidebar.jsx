import {
  Library,
  MessageSquare,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  Pin,
  PinOff,
  Settings,
  Trash2,
  PencilLine,
  SquarePen,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import { NavLink, useNavigate } from 'react-router-dom'
import { useAppStore } from '../store/store.js'

dayjs.extend(relativeTime)

// Short relative time ("2m ago", "Yesterday") — no date-header grouping.
// A flat, searchable-by-scanning list holds up fine at the scale this app
// actually sees; if/when a search box gets added this is what it'd filter.
function formatRelativeTime(iso) {
  if (!iso) return ''
  const d = dayjs(iso)
  const now = dayjs()
  if (now.diff(d, 'day') < 1 && now.isSame(d, 'day')) return d.fromNow()
  if (now.diff(d, 'day') === 1 || (now.diff(d, 'hour') < 48 && !now.isSame(d, 'day'))) return 'Yesterday'
  return d.fromNow()
}

function ChatItemRow({ chat, isActive, isMenuOpen, onSelect, onToggleMenu }) {
  const titleRef = useRef(null)
  const windowRef = useRef(null)
  const [offset, setOffset] = useState(0)

  const handleMouseEnter = () => {
    if (!titleRef.current || !windowRef.current) return
    const overflow = titleRef.current.scrollWidth - windowRef.current.clientWidth
    if (overflow > 1) {
      setOffset(overflow)
    }
  }

  const handleMouseLeave = () => {
    setOffset(0)
  }

  return (
    <div
      className={`chat-item ${isActive ? 'chat-item--active' : ''} ${isMenuOpen ? 'chat-item--menu-open' : ''}`}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <button
        type="button"
        className="chat-item__main"
        onClick={onSelect}
      >
        <MessageSquare size={14} className="chat-item__icon" aria-hidden="true" />
        <span ref={windowRef} className="chat-item__title-window">
          <span
            ref={titleRef}
            className="chat-item__title"
            style={{
              transform: offset > 0 ? `translateX(-${offset}px)` : 'translateX(0)',
              transition: offset > 0
                ? `transform ${Math.max(1.6, offset * 0.022)}s linear 0.35s`
                : 'transform 0.22s ease-out',
            }}
          >
            {chat.title}
          </span>
        </span>
        <span className="chat-item__time">{formatRelativeTime(chat.updatedAt)}</span>
      </button>

      <div className="chat-item__actions">
        <button
          type="button"
          className="chat-item__menu-trigger"
          aria-label={`Chat actions for ${chat.title}`}
          onClick={(e) => onToggleMenu(chat, e)}
        >
          <MoreHorizontal size={15} />
        </button>
      </div>
    </div>
  )
}

export default function Sidebar() {
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

  const navigate = useNavigate()
  const [openMenuId, setOpenMenuId] = useState(null)
  const [menuPosition, setMenuPosition] = useState(null)
  const [dialog, setDialog] = useState({ type: null, chat: null, value: '' })

  useEffect(() => {
    if (!openMenuId) return undefined
    const handleViewportChange = () => {
      setOpenMenuId(null)
      setMenuPosition(null)
    }
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
    setOpenMenuId(null)
    setMenuPosition(null)
    await newChat()
    navigate('/chat')
  }

  const handleRename = (chat) => {
    setOpenMenuId(null)
    setMenuPosition(null)
    setDialog({ type: 'rename', chat, value: chat.title })
  }

  const handleDelete = (chat) => {
    setOpenMenuId(null)
    setMenuPosition(null)
    setDialog({ type: 'delete', chat, value: '' })
  }

  const handlePin = (chat) => {
    setOpenMenuId(null)
    setMenuPosition(null)
    togglePinChat(chat.id)
  }

  const closeDialog = () => setDialog({ type: null, chat: null, value: '' })
  const closeMenu = () => { setOpenMenuId(null); setMenuPosition(null) }

  const toggleChatMenu = (chat, event) => {
    const triggerRect = event.currentTarget.getBoundingClientRect()
    const menuWidth = 172
    const menuHeight = 132
    const viewportWidth = window.innerWidth
    const viewportHeight = window.innerHeight
    const nextLeft = Math.max(12, Math.min(triggerRect.right - menuWidth, viewportWidth - menuWidth - 12))
    const enoughRoomBelow = triggerRect.bottom + menuHeight + 12 <= viewportHeight
    if (openMenuId === chat.id) { closeMenu(); return }
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
      if (!nextTitle || nextTitle === dialog.chat.title) { closeDialog(); return }
      await renameChat(dialog.chat.id, nextTitle)
    }
    if (dialog.type === 'delete') {
      await deleteChat(dialog.chat.id)
      navigate('/chat')
    }
    closeDialog()
  }

  const activeMenuChat = chats.find((c) => c.id === openMenuId)
  const activeMenuIsPinned = activeMenuChat ? pinnedChatIds.has(activeMenuChat.id) : false

  const renderChatList = (list) =>
    list.map((chat) => (
      <ChatItemRow
        key={chat.id}
        chat={chat}
        isActive={activeChatId === chat.id}
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
      {/* Collapsed rail for desktop */}
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
          className={({ isActive }) =>
            `sidebar-rail__btn ${isActive ? 'sidebar-rail__btn--active' : ''}`
          }
          title="Documents"
          aria-label="Documents"
        >
          <Library size={18} />
        </NavLink>

        <div className="sidebar-rail__spacer" />

        <NavLink
          to="/settings"
          className={({ isActive }) =>
            `sidebar-rail__btn ${isActive ? 'sidebar-rail__btn--active' : ''}`
          }
          title="Settings"
          aria-label="Settings"
        >
          <Settings size={18} />
        </NavLink>
      </aside>

      {/* Expanded sidebar */}
      <aside className="sidebar" data-open={sidebarOpen} data-collapsed={sidebarCollapsed}>

        {/* Brand — fixed, compact lockup: mark + name + tagline */}
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

        {/* New chat */}
        <div className="sidebar__new-chat-row">
          <button type="button" className="new-chat-action" onClick={handleNewChat}>
            <SquarePen size={16} />
            <span>New chat</span>
          </button>
        </div>

        {/* Documents — a permanent library, not a chat. Ingestion happens
            entirely on that page; nothing here spawns a conversation. */}
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
        </div>

        {/* Footer — Settings only */}
        <footer className="sidebar__footer">
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

      {/* Portal for chat menu */}
      {openMenuId && activeMenuChat ? createPortal(
        <div className="chat-menu-backdrop" role="presentation" onClick={closeMenu}>
          <div
            className="chat-menu"
            role="menu"
            aria-label="Chat actions"
            style={menuPosition ?? undefined}
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              className="chat-menu__item"
              onClick={() => handlePin(activeMenuChat)}
              role="menuitem"
            >
              {activeMenuIsPinned ? <PinOff size={14} /> : <Pin size={14} />}
              <span>{activeMenuIsPinned ? 'Unpin' : 'Pin'}</span>
            </button>
            <button
              type="button"
              className="chat-menu__item"
              onClick={() => handleRename(activeMenuChat)}
              role="menuitem"
            >
              <PencilLine size={14} /><span>Rename</span>
            </button>
            <button
              type="button"
              className="chat-menu__item chat-menu__item--danger"
              onClick={() => handleDelete(activeMenuChat)}
              role="menuitem"
            >
              <Trash2 size={14} /><span>Delete</span>
            </button>
          </div>
        </div>,
        document.body
      ) : null}

      {sidebarOpen ? (
        <button type="button" className="sidebar-backdrop" onClick={closeSidebar} aria-label="Close navigation" />
      ) : null}

      {dialog.type ? (
        <div className="dialog-backdrop" role="presentation" onClick={closeDialog}>
          <div className="dialog-card" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
            <p className="dialog-card__eyebrow">Chat action</p>
            <h3 className="dialog-card__title">
              {dialog.type === 'rename' ? 'Rename chat' : 'Delete chat'}
            </h3>
            <p className="dialog-card__text">
              {dialog.type === 'rename'
                ? 'Give this conversation a new name.'
                : `This will remove "${dialog.chat?.title}" from recent chats.`}
            </p>
            {dialog.type === 'rename' ? (
              <input
                autoFocus
                className="dialog-card__input"
                value={dialog.value}
                onChange={(e) => setDialog((c) => ({ ...c, value: e.target.value }))}
                placeholder="Chat title"
              />
            ) : null}
            <div className="dialog-card__actions">
              <button type="button" className="secondary-button" onClick={closeDialog}>Cancel</button>
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
