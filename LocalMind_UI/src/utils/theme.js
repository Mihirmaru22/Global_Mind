import { useSyncExternalStore } from 'react'

const themeMap = {
  dark: { value: 'dark', mode: 'dark' },
  light: { value: 'light', mode: 'light' },
}

export function resolveTheme(theme) {
  return themeMap[theme] || themeMap.light
}

const DARK_QUERY = '(prefers-color-scheme: dark)'

function subscribeToSystemTheme(callback) {
  if (typeof window === 'undefined' || !window.matchMedia) return () => {}
  const mql = window.matchMedia(DARK_QUERY)
  mql.addEventListener('change', callback)
  return () => mql.removeEventListener('change', callback)
}

function getSystemPrefersDarkSnapshot() {
  if (typeof window === 'undefined' || !window.matchMedia) return true
  return window.matchMedia(DARK_QUERY).matches
}

// 'system' isn't a theme of its own — it's resolved live from the OS
// preference via useSyncExternalStore, so switching the OS theme while the
// app is open updates it immediately (and correctly re-syncs if the setting
// switches to 'system' after the OS preference already changed elsewhere).
export function useResolvedTheme(theme) {
  const systemPrefersDark = useSyncExternalStore(
    subscribeToSystemTheme,
    getSystemPrefersDarkSnapshot,
    () => true,
  )

  if (theme === 'system') {
    return systemPrefersDark ? themeMap.dark : themeMap.light
  }
  return resolveTheme(theme)
}
