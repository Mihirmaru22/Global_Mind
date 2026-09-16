import { useEffect, useRef, useState } from 'react'
import { Activity, Check, ChevronDown, Gauge, RotateCw, Sparkles, Zap } from 'lucide-react'
import { AnimatePresence, motion } from 'framer-motion'
import { useAppStore } from '../store/store.js'

// Format integer into a clean, human-readable compact representation:
// 1200 -> "1.2k", 200000 -> "200k", 1000000 -> "1M"
function formatCompact(num) {
  const n = Number(num) || 0
  if (n >= 1_000_000) {
    const val = (n / 1_000_000).toFixed(1)
    return `${val.endsWith('.0') ? val.slice(0, -2) : val}M`
  }
  if (n >= 10_000) {
    return `${Math.round(n / 1_000)}k`
  }
  if (n >= 1_000) {
    const val = (n / 1_000).toFixed(1)
    return `${val.endsWith('.0') ? val.slice(0, -2) : val}k`
  }
  return n.toLocaleString()
}

// Clamp a used/limit pair into a 0–100% width and severity tier
function meter(used, limit) {
  const capacity = Number(limit) || 0
  const consumed = Number(used) || 0
  const pct = capacity > 0 ? Math.min(100, Math.round((consumed / capacity) * 100)) : 0
  const level = pct >= 90 ? 'crit' : pct >= 70 ? 'warn' : 'ok'
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

// Collapse every provider's meters into a system-level health status
function summarize(usage) {
  let level = 'ok'
  let cooling = false
  let highest = null

  for (const p of usage || []) {
    if (Number(p.backoffSeconds) > 0) cooling = true
    const bm = calculateBottleneck(p)
    if (!highest || bm.pct > highest.pct) {
      highest = { ...bm, provider: p.label || p.id }
    }
    if (bm.level === 'crit') level = 'crit'
    else if (bm.level === 'warn' && level !== 'crit') level = 'warn'
  }
  return { level, cooling, highest }
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
  const [usageOpen, setUsageOpen] = useState(false)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const pickerRef = useRef(null)
  const usageRef = useRef(null)

  useDismiss(pickerRef, () => setPickerOpen(false), pickerOpen)
  useDismiss(usageRef, () => setUsageOpen(false), usageOpen)

  // Pull fresh quota numbers whenever the usage popover is opened
  useEffect(() => {
    if (usageOpen) refreshProviderUsage()
  }, [usageOpen, refreshProviderUsage])

  const options = providers?.length ? providers : fallbackProviders
  const activeId = settings?.provider || 'auto'
  const activeLabel =
    options.find((o) => o.id === activeId)?.label ||
    (activeId === 'auto' ? 'Auto' : activeId)

  const visibleUsage =
    activeId === 'auto'
      ? providerUsage || []
      : (providerUsage || []).filter((p) => p.id === activeId)

  const { level, cooling, highest } = summarize(visibleUsage)

  const handleRefresh = async () => {
    if (isRefreshing) return
    setIsRefreshing(true)
    try {
      await refreshProviderUsage()
    } finally {
      setTimeout(() => setIsRefreshing(false), 500)
    }
  }

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
          onClick={() => {
            setPickerOpen((v) => !v)
            setUsageOpen(false)
          }}
          aria-haspopup="menu"
          aria-expanded={pickerOpen}
          title="Change provider"
        >
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
                return (
                  <button
                    key={option.id}
                    type="button"
                    role="menuitemradio"
                    aria-checked={active}
                    className={`provider-pop__item ${active ? 'provider-pop__item--active' : ''}`}
                    onClick={() => selectProvider(option.id)}
                  >
                    <span>{option.label}</span>
                    {active ? <Check size={13} /> : null}
                  </button>
                )
              })}
            </motion.div>
          ) : null}
        </AnimatePresence>
      </div>

      {/* Quota dot — click to reveal live telemetry & bottleneck smart cards. */}
      <div className="provider-status__usage" ref={usageRef}>
        <button
          type="button"
          className={`provider-status__dot provider-status__dot--${level} ${
            cooling ? 'provider-status__dot--cooling' : ''
          }`}
          onClick={() => {
            setUsageOpen((v) => !v)
            setPickerOpen(false)
          }}
          aria-haspopup="dialog"
          aria-expanded={usageOpen}
          aria-label="Show provider telemetry"
          title="Provider Telemetry & Bottlenecks"
        >
          <span className="provider-status__dot-core" />
        </button>

        <AnimatePresence>
          {usageOpen ? (
            <motion.div
              className="provider-pop provider-pop--usage"
              role="dialog"
              aria-label="Provider telemetry"
              initial={{ opacity: 0, y: 6, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 6, scale: 0.98 }}
              transition={{ duration: 0.14 }}
            >
              {/* Telemetry Header */}
              <div className="provider-pop__head">
                <div className="provider-pop__title-group">
                  <span className="provider-pop__title">
                    <Gauge size={14} className="provider-pop__title-icon" />
                    Provider Telemetry
                  </span>
                  {/* System Health Badge */}
                  <span className={`telemetry-health-chip telemetry-health-chip--${level}`}>
                    {cooling ? (
                      'Cooling Down'
                    ) : highest && highest.pct >= 70 ? (
                      `${highest.provider} (${highest.pct}%)`
                    ) : (
                      `${visibleUsage.length} Providers Healthy`
                    )}
                  </span>
                </div>

                <button
                  type="button"
                  className={`usage-refresh ${isRefreshing ? 'usage-refresh--spinning' : ''}`}
                  onClick={handleRefresh}
                  aria-label="Refresh telemetry"
                  title="Refresh live telemetry"
                >
                  <RotateCw size={12} />
                </button>
              </div>

              {visibleUsage.length ? (
                <div className="provider-pop__list">
                  {visibleUsage.map((p) => {
                    const bottleneck = calculateBottleneck(p)
                    const isCooling = Number(p.backoffSeconds) > 0

                    return (
                      <div
                        key={p.id}
                        className={`smart-card smart-card--${bottleneck.level} ${
                          isCooling ? 'smart-card--cooling' : ''
                        }`}
                      >
                        {/* Top: Provider Name, Model Pill, & Status Badge */}
                        <div className="smart-card__header">
                          <div className="smart-card__title-row">
                            <span className="smart-card__name">{p.label}</span>
                            {p.model ? (
                              <span className="smart-card__model-badge" title={`Model: ${p.model}`}>
                                {p.model}
                              </span>
                            ) : null}
                          </div>

                          <div className="smart-card__status-row">
                            {isCooling ? (
                              <span className="status-pill status-pill--cooling">
                                Cooling {Math.ceil(p.backoffSeconds)}s
                              </span>
                            ) : bottleneck.pct >= 90 ? (
                              <span className="status-pill status-pill--crit">
                                ⚠️ {bottleneck.pct}% {bottleneck.label}
                              </span>
                            ) : bottleneck.pct >= 70 ? (
                              <span className="status-pill status-pill--warn">
                                {bottleneck.pct}% Load
                              </span>
                            ) : (
                              <span className="status-pill status-pill--ok">
                                <span className="status-pill__dot" />
                                Active
                              </span>
                            )}
                          </div>
                        </div>

                        {/* Subtitle: Functional Role */}
                        {p.role ? (
                          <div className="smart-card__role">{p.role}</div>
                        ) : null}

                        {/* Primary Bottleneck Gauge */}
                        <div className="smart-bottleneck">
                          <div className="smart-bottleneck__meta">
                            <span className="smart-bottleneck__label">
                              Limiting Quota: <strong>{bottleneck.label}</strong>
                            </span>
                            <span className="smart-bottleneck__count">
                              {formatCompact(bottleneck.consumed)} / {formatCompact(bottleneck.capacity)}{' '}
                              <span className="smart-bottleneck__pct">({bottleneck.pct}%)</span>
                            </span>
                          </div>

                          <div className="smart-track">
                            <div
                              className={`smart-fill smart-fill--${bottleneck.level}`}
                              style={{ width: `${Math.max(bottleneck.pct, 2)}%` }}
                            />
                          </div>
                        </div>

                        {/* Dual-Pill Matrix: Requests & Tokens */}
                        <div className="smart-matrix">
                          <div className="smart-pill">
                            <span className="smart-pill__icon" title="Requests">
                              <Zap size={11} />
                            </span>
                            <div className="smart-pill__data">
                              <span className="smart-pill__title">Requests</span>
                              <span className="smart-pill__values">
                                {p.rpmUsed}/{p.rpmLimit}m · {formatCompact(p.rpdUsed)}/{formatCompact(p.rpdLimit)}d
                              </span>
                            </div>
                          </div>

                          <div className="smart-pill">
                            <span className="smart-pill__icon" title="Tokens">
                              <Sparkles size={11} />
                            </span>
                            <div className="smart-pill__data">
                              <span className="smart-pill__title">Tokens</span>
                              <span className="smart-pill__values">
                                {formatCompact(p.tpmUsed)}/{formatCompact(p.tpmLimit)}m · {formatCompact(p.tpdUsed)}/{formatCompact(p.tpdLimit)}d
                              </span>
                            </div>
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              ) : (
                <p className="usage-empty">
                  {activeId === 'auto'
                    ? "Usage isn't available yet."
                    : `No usage data for ${activeLabel} yet.`}
                </p>
              )}
            </motion.div>
          ) : null}
        </AnimatePresence>
      </div>
    </div>
  )
}
