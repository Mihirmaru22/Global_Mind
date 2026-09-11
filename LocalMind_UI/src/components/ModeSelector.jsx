import { useEffect, useRef, useState } from 'react'
import { Check, ChevronDown, ChevronUp, Database, FileText, Sparkles } from 'lucide-react'
import { AnimatePresence, motion } from 'framer-motion'
import { useAppStore } from '../store/store.js'

export const MODES = [
  {
    id: 'auto',
    name: 'Auto (Hybrid)',
    tag: 'Smart',
    speed: 'Auto',
    icon: Sparkles,
  },
  {
    id: 'sql',
    name: 'SQL Database',
    tag: 'Live ERP',
    speed: 'Fast',
    icon: Database,
  },
  {
    id: 'rag',
    name: 'Documents (RAG)',
    tag: 'Policies',
    speed: 'Docs',
    icon: FileText,
  },
]

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

export default function ModeSelector() {
  const searchMode = useAppStore((state) => state.searchMode) || 'auto'
  const setSearchMode = useAppStore((state) => state.setSearchMode)

  const [open, setOpen] = useState(false)
  const menuRef = useRef(null)

  useDismiss(menuRef, () => setOpen(false), open)

  const activeMode = MODES.find((m) => m.id === searchMode) || MODES[0]
  const ActiveIcon = activeMode.icon

  return (
    <div className="mode-selector" ref={menuRef}>
      <button
        type="button"
        className="mode-chip"
        onClick={() => setOpen((prev) => !prev)}
        aria-haspopup="menu"
        aria-expanded={open}
        title="Knowledge Source mode"
      >
        <ActiveIcon size={13} className="mode-chip__icon" />
        <span className="mode-chip__label">{activeMode.name}</span>
        {open ? (
          <ChevronUp size={12} className="mode-chip__caret" />
        ) : (
          <ChevronDown size={12} className="mode-chip__caret" />
        )}
      </button>

      <AnimatePresence>
        {open ? (
          <motion.div
            className="mode-pop"
            role="menu"
            initial={{ opacity: 0, y: 4, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 4, scale: 0.98 }}
            transition={{ duration: 0.12 }}
          >
            <div className="mode-pop__header">Knowledge Source</div>

            <div className="mode-pop__list">
              {MODES.map((mode) => {
                const active = mode.id === activeMode.id
                const Icon = mode.icon
                return (
                  <button
                    key={mode.id}
                    type="button"
                    role="menuitemradio"
                    aria-checked={active}
                    className={`mode-pop__row ${active ? 'mode-pop__row--active' : ''}`}
                    onClick={() => {
                      setSearchMode(mode.id)
                      setOpen(false)
                    }}
                  >
                    <div className="mode-pop__row-left">
                      <Icon size={14} className="mode-pop__row-icon" />
                      <span className="mode-pop__row-name">{mode.name}</span>
                      <span className="mode-pop__row-tag">{mode.tag}</span>
                    </div>

                    <div className="mode-pop__row-right">
                      <span className="mode-pop__row-speed">{mode.speed}</span>
                      {active ? (
                        <Check size={13} className="mode-pop__row-check" />
                      ) : (
                        <span className="mode-pop__row-spacer" />
                      )}
                    </div>
                  </button>
                )
              })}
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  )
}
