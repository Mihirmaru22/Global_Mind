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
  const windowRef = useRef(null)
  const titleRef = useRef(null)
  const [marquee, setMarquee] = useState(null)

  // Only start the marquee when the title is really cut off, and never for reduced motion.
  const startMarquee = () => {
    const viewport = windowRef.current
    const title = titleRef.current
    if (!viewport || !title) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const distance = Math.ceil(title.scrollWidth - viewport.clientWidth)
    if (distance <= 1) return
    setMarquee({ distance, duration: Math.max(1.5, distance / 40) })
  }

  const stopMarquee = () => setMarquee(null)

  return (
    <div
      className={`chat-item ${isActive ? 'chat-item--active' : ''} ${isMenuOpen ? 'chat-item--menu-open' : ''} ${marquee ? 'chat-item--marquee' : ''}`}
      style={marquee ? { '--marquee-distance': `${marquee.distance}px`, '--marquee-duration': `${marquee.duration}s` } : undefined}
      onMouseEnter={startMarquee}
      onMouseLeave={stopMarquee}
    >
      <button type="button" className="chat-item__main" onClick={onSelect}>
        <MessageSquare size={14} className="chat-item__icon" aria-hidden="true" />
        <span className="chat-item__title-window" ref={windowRef}>
          <span className="chat-item__title" ref={titleRef}>{chat.title}</span>
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
  const [profileMenu, setProfileMenu] = useState(null)
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

  const closeProfileMenu = () => setProfileMenu(null)

  const toggleProfileMenu = (event, placement) => {
    if (profileMenu) {
      closeProfileMenu()
      return
    }
    const rect = event.currentTarget.getBoundingClientRect()
    setProfileMenu(
      placement === 'rail'
        ? { left: rect.right + 8, bottom: window.innerHeight - rect.bottom }
        : { left: rect.left, bottom: window.innerHeight - rect.top + 8 },
    )
  }

  const handleLogout = () => {
    closeProfileMenu()
    logoutUser()
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
      <aside className="sidebar" data-open={sidebarOpen} data-collapsed={sidebarCollapsed}>
        <div className="brand">
          <div className="brand__row">
            <div className="brand__type sidebar__label">
              <h1 className="brand__title">Local Mind</h1>
              <p className="brand__subtitle">Private data intelligence</p>
            </div>
            <button
              type="button"
              className="sidebar__toggle desktop-toggle"
              onClick={toggleSidebarCollapse}
              title={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
              aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            >
              <PanelLeftClose size={18} className="sidebar__toggle-close" />
              <PanelLeftOpen size={18} className="sidebar__toggle-open" />
            </button>
          </div>
        </div>

        <div className="sidebar__inner">
        <div className="sidebar__documents-row">
          <button type="button" className="nav-item" onClick={handleNewChat} title="New chat">
            <SquarePen size={16} />
            <span className="sidebar__label">New chat</span>
          </button>
        </div>

        <nav className="sidebar__documents-row">
          <NavLink
            to="/documents"
            className={({ isActive }) => `nav-item nav-item--documents ${isActive ? 'nav-item--active' : ''}`}
            onClick={closeSidebar}
            title="Documents"
          >
            <Library size={16} />
            <span className="sidebar__label">Documents</span>
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

        <footer className="sidebar__footer">
          <div className="profile-row">
            {currentUser && (
              <button
                type="button"
                className="profile-row__main"
                onClick={(event) => toggleProfileMenu(event, sidebarCollapsed && window.innerWidth > 768 ? 'rail' : 'sidebar')}
                aria-label={`Profile menu for ${currentUser}`}
                aria-haspopup="menu"
              >
                <span className="profile-avatar">{currentUser.slice(0, 1)}</span>
                <span className="profile-row__name">{currentUser}</span>
              </button>
            )}
            <NavLink
              to="/settings"
              className={({ isActive }) => `profile-row__settings ${isActive ? 'profile-row__settings--active' : ''}`}
              title="Settings"
              aria-label="Settings"
              onClick={closeSidebar}
            >
              <Settings size={18} />
            </NavLink>
          </div>
        </footer>
        </div>
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

      {profileMenu ? createPortal(
        <div className="chat-menu-backdrop" role="presentation" onClick={closeProfileMenu}>
          <div
            className="chat-menu"
            role="menu"
            aria-label="Profile actions"
            style={profileMenu}
            onClick={(event) => event.stopPropagation()}
          >
            <button type="button" className="chat-menu__item chat-menu__item--danger" onClick={handleLogout} role="menuitem">
              <LogOut size={14} />
              <span>Log out</span>
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
