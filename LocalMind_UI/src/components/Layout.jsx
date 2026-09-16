import { useEffect, useRef } from 'react'
import { Outlet } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import Header from './Header.jsx'
import Sidebar from './Sidebar.jsx'
import Login from '../pages/Login.jsx'
import { useAppStore } from '../store/store.js'
import { useResolvedTheme } from '../utils/theme.js'

export function Layout() {
  const checkAuth = useAppStore((state) => state.checkAuth)
  const currentUser = useAppStore((state) => state.currentUser)
  const isAuthChecking = useAppStore((state) => state.isAuthChecking)
  const theme = useAppStore((state) => state.settings?.theme)
  const sidebarCollapsed = useAppStore((state) => state.sidebarCollapsed)
  const appliedTheme = useResolvedTheme(theme)
  const initialized = useRef(false)

  useEffect(() => {
    if (initialized.current) return
    initialized.current = true
    checkAuth()
  }, [checkAuth])

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

  if (isAuthChecking) {
    return (
      <div
        style={{
          minHeight: '100vh',
          width: '100vw',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'var(--bg)',
          gap: '12px',
          color: 'var(--text-secondary)',
        }}
      >
        <Loader2 className="animate-spin" size={32} style={{ color: 'var(--primary)' }} />
        <span style={{ fontSize: '14px' }}>Loading workspace…</span>
      </div>
    )
  }

  if (!currentUser) {
    return <Login />
  }

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
    </div>
  )
}
