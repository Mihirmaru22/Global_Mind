export function resolveTheme(theme) {
  return theme || 'dark'
}

import { useEffect, useState } from 'react'

export function useResolvedTheme(theme) {
  const [resolvedTheme, setResolvedTheme] = useState(() => resolveTheme(theme))

  useEffect(() => {
    setResolvedTheme(resolveTheme(theme))
  }, [theme])

  return resolvedTheme
}
