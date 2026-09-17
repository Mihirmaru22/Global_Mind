import { useEffect, useRef, useState } from 'react'
import { ChevronDown, Sparkles } from 'lucide-react'
import { AnimatePresence, motion } from 'framer-motion'
import { useAppStore } from '../store/store.js'

// Clamp a used/limit pair into a 0–100% width and severity tier
function meter(used, limit) {
  const capacity = Number(limit) || 0
  const consumed = Number(used) || 0
  const pct = capacity > 0 ? Math.min(100, Math.round((consumed / capacity) * 100)) : 0
  const level = capacity <= 0 ? 'none' : pct >= 90 ? 'crit' : pct >= 60 ? 'warn' : 'ok'
  return { pct, level, consumed, capacity }
}

// Evaluate RPM, RPD, TPM, TPD to identify the primary limiting resource
function calculateBottleneck(p) {
  const metrics = [
    { key: 'tpd', label: 'Daily Tokens', ...meter(p.tpdUsed, p.tpdLimit) },
    { key: 'tpm', label: 'Min Tokens', ...meter(p.tpmUsed, p.tpmLimit) },
    { key: 'rpm', label: 'Min Requests', ...meter(p.rpmUsed, p.rpmLimit) },
    { key: 'rpd', label: 'Daily Requests', ...meter(p.rpdUsed, p.rpdLimit) },
  ]
  // Primary bottleneck is the one with highest capacity consumption
  metrics.sort((a, b) => b.pct - a.pct)
  return metrics[0]
}

// Small circular usage ring — mirrors Claude's own quota indicator. Colour only,
// no number: green while healthy, yellow from 60%, red from 90%, and a plain
// gray ring when there's no usage data for the provider yet.
function UsageRing({ pct, level, size = 16 }) {
  const strokeWidth = 2.5
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const dash = Math.max(0, Math.min(100, pct)) / 100 * circumference

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      className={`usage-ring usage-ring--${level}`}
      aria-hidden="true"
    >
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke="currentColor"
        strokeOpacity="0.25"
        strokeWidth={strokeWidth}
      />
      {level !== 'none' ? (
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference - dash}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      ) : null}
    </svg>
  )
}

const fallbackProviders = [
  { id: 'auto', label: 'Auto' },
  { id: 'openrouter', label: 'OpenRouter' },
]

// Close a popover when the user clicks anywhere outside it or presses Escape.
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

export default function ProviderStatus() {
  const settings = useAppStore((state) => state.settings)
  const providers = useAppStore((state) => state.providers)
  const providerUsage = useAppStore((state) => state.providerUsage)
  const refreshProviderUsage = useAppStore((state) => state.refreshProviderUsage)
  const updateSettings = useAppStore((state) => state.updateSettings)

  const [pickerOpen, setPickerOpen] = useState(false)
  const pickerRef = useRef(null)

  useDismiss(pickerRef, () => setPickerOpen(false), pickerOpen)

  // Pull fresh quota numbers whenever the picker opens, so each row's ring is current
  useEffect(() => {
    if (pickerOpen) refreshProviderUsage()
  }, [pickerOpen, refreshProviderUsage])

  const options = providers?.length ? providers : fallbackProviders
  const activeId = settings?.provider || 'auto'
  const activeLabel =
    options.find((o) => o.id === activeId)?.label ||
    (activeId === 'auto' ? 'Auto' : activeId)

  const selectProvider = (id) => {
    updateSettings({ provider: id })
    setPickerOpen(false)
  }

  return (
    <div className="provider-status">
      {/* Current provider — click to switch, mirrors Claude's model selector. */}
      <div className="provider-status__picker" ref={pickerRef}>
        <button
          type="button"
          className="provider-status__chip"
          onClick={() => setPickerOpen((v) => !v)}
          aria-haspopup="menu"
          aria-expanded={pickerOpen}
          title="Change provider"
        >
          <Sparkles size={13} className="provider-status__chip-icon" />
          <span className="provider-status__name">{activeLabel}</span>
          <ChevronDown size={13} className="provider-status__caret" />
        </button>

        <AnimatePresence>
          {pickerOpen ? (
            <motion.div
              className="provider-pop provider-pop--picker"
              role="menu"
              initial={{ opacity: 0, y: 6, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 6, scale: 0.98 }}
              transition={{ duration: 0.14 }}
            >
              {options.map((option) => {
                const active = option.id === activeId
                const ownUsage = (providerUsage || []).find((p) => p.id === option.id)
                const ownBottleneck = ownUsage ? calculateBottleneck(ownUsage) : { pct: 0, level: 'none' }
                return (
                  <button
                    key={option.id}
                    type="button"
                    role="menuitemradio"
                    aria-checked={active}
                    className={`provider-pop__item ${active ? 'provider-pop__item--active' : ''}`}
                    onClick={() => selectProvider(option.id)}
                  >
                    <span className="provider-pop__item-label">
                      <span>{option.label}</span>
                    </span>
                    <UsageRing pct={ownBottleneck.pct} level={ownBottleneck.level} size={14} />
                  </button>
                )
              })}
            </motion.div>
          ) : null}
        </AnimatePresence>
      </div>
    </div>
  )
}
