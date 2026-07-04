import { useEffect, useRef } from 'react'
import { Outlet } from 'react-router-dom'
import Header from './Header.jsx'
import Sidebar from './Sidebar.jsx'
import { useAppStore } from '../store/store.js'
import { useResolvedTheme } from '../utils/theme.js'

export function Layout() {
  const initApp = useAppStore((state) => state.initApp)
  const theme = useAppStore((state) => state.settings?.theme)
  const appliedTheme = useResolvedTheme(theme)
  const initialized = useRef(false)

  useEffect(() => {
    if (initialized.current) return
    initialized.current = true
    initApp()
  }, [initApp])

  useEffect(() => {
    if (typeof document === 'undefined') return
    document.documentElement.dataset.theme = appliedTheme
    document.documentElement.style.colorScheme = appliedTheme
  }, [appliedTheme])

  return (
    <div className="app-shell">
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
