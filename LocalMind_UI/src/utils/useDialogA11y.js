import { useEffect, useRef } from 'react'

const FOCUSABLE_SELECTOR =
  'button, a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])'

/**
 * Standard modal-dialog accessibility behavior for the dialog-card pattern
 * used across Sidebar and Documents:
 * - Focuses a chosen control when the dialog opens.
 * - Traps Tab/Shift+Tab focus inside the dialog while it is open.
 * - Closes the dialog on Escape.
 * - Returns focus to whatever triggered the dialog once it closes.
 *
 * This only manages focus and key handling. It does not touch any store
 * action or confirmation logic.
 */
export function useDialogA11y({ isOpen, onClose, containerRef, initialFocusRef }) {
  const previouslyFocusedRef = useRef(null)

  useEffect(() => {
    if (!isOpen) return undefined

    previouslyFocusedRef.current = document.activeElement

    const focusTimer = window.setTimeout(() => {
      const target = initialFocusRef?.current || containerRef?.current
      target?.focus()
    }, 0)

    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose?.()
        return
      }
      if (event.key !== 'Tab') return

      const container = containerRef?.current
      if (!container) return

      const focusable = Array.from(container.querySelectorAll(FOCUSABLE_SELECTOR)).filter(
        (el) => !el.disabled && el.getAttribute('aria-hidden') !== 'true',
      )
      if (focusable.length === 0) return

      const first = focusable[0]
      const last = focusable[focusable.length - 1]

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)

    return () => {
      window.clearTimeout(focusTimer)
      document.removeEventListener('keydown', handleKeyDown)
      previouslyFocusedRef.current?.focus?.()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen])
}
