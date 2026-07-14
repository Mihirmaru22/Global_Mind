import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Outlet } from 'react-router-dom'
import Header from './Header.jsx'
import Sidebar from './Sidebar.jsx'
import { useAppStore } from '../store/store.js'
import { http } from '../services/http.js'
import { useResolvedTheme } from '../utils/theme.js'

export function Layout() {
  const initApp = useAppStore((state) => state.initApp)
  const theme = useAppStore((state) => state.settings?.theme)
  const sidebarCollapsed = useAppStore((state) => state.sidebarCollapsed)
  const appliedTheme = useResolvedTheme(theme)
  const initialized = useRef(false)
  const [directoryNotice, setDirectoryNotice] = useState(null)

  useEffect(() => {
    if (initialized.current) return
    initialized.current = true
    initApp()
  }, [initApp])

  useEffect(() => {
    if (typeof document === 'undefined') return
    document.documentElement.dataset.theme = appliedTheme.value
    document.documentElement.dataset.themeMode = appliedTheme.mode
    document.documentElement.style.colorScheme = appliedTheme.mode
  }, [appliedTheme])

  useEffect(() => {
    if (typeof window === 'undefined') return undefined

    const root = document.documentElement
    let timerId = null

    const markScrolling = () => {
      root.dataset.scrolling = 'true'
      window.clearTimeout(timerId)
      timerId = window.setTimeout(() => {
        delete root.dataset.scrolling
      }, 700)
    }

    window.addEventListener('scroll', markScrolling, true)
    return () => {
      window.removeEventListener('scroll', markScrolling, true)
      window.clearTimeout(timerId)
      delete root.dataset.scrolling
    }
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined' || typeof EventSource === 'undefined') return undefined

    const source = new EventSource(`${http.defaults.baseURL}/events/stream`)

    source.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data)
        if (payload?.type === 'NO_DOCUMENTS_IN_DIRECTORY') {
          setDirectoryNotice({
            title: 'No Documents Found',
            message:
              payload.message ||
              'No documents were found in the uploads directory. Please add documents to data/uploads before proceeding.',
            path: payload.path || 'data/uploads',
          })
          return
        }

        if (payload?.type === 'DOCUMENTS_RESTORED') {
          setDirectoryNotice(null)
        }
      } catch (error) {
        console.error('Failed to parse directory notification:', error)
      }
    }

    source.onerror = () => {
      // EventSource retries automatically.
    }

    return () => {
      source.close()
    }
  }, [])

  return (
    <div className="app-shell" data-sidebar-collapsed={sidebarCollapsed ? 'true' : 'false'}>
      <Sidebar />
      <main className="content">
        <Header />
        <div className="main-scroll">
          <div className="surface">
            <Outlet />
          </div>
        </div>
      </main>
      {directoryNotice
        ? createPortal(
            <div
              className="dialog-backdrop"
              role="presentation"
              onClick={() => setDirectoryNotice(null)}
            >
              <div
                className="dialog-card"
                role="dialog"
                aria-modal="true"
                aria-labelledby="uploads-dialog-title"
                aria-describedby="uploads-dialog-description"
                onClick={(event) => event.stopPropagation()}
              >
                <p className="dialog-card__eyebrow">Directory notice</p>
                <h3 id="uploads-dialog-title" className="dialog-card__title">
                  {directoryNotice.title}
                </h3>
                <p id="uploads-dialog-description" className="dialog-card__text">
                  {directoryNotice.message}
                </p>
                <div className="dialog-card__actions">
                  <button
                    type="button"
                    className="secondary-button"
                    onClick={() => setDirectoryNotice(null)}
                  >
                    Close
                  </button>
                </div>
              </div>
            </div>,
            document.body,
          )
        : null}
    </div>
  )
}

