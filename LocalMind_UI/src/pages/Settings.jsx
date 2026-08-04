import { useEffect } from 'react'
import { Check, Gauge, RotateCw, Server, SlidersHorizontal, Sparkles } from 'lucide-react'
import { motion } from 'framer-motion'
import { useAppStore } from '../store/store.js'

// Clamp a used/limit pair into a 0–100% width and a severity band so the meter
// fill shifts from calm → warning → critical as a free-tier window fills up.
function meter(used, limit) {
  const capacity = Number(limit) || 0
  const consumed = Number(used) || 0
  const pct = capacity > 0 ? Math.min(100, Math.round((consumed / capacity) * 100)) : 0
  const level = pct >= 90 ? 'crit' : pct >= 70 ? 'warn' : 'ok'
  return { pct, level }
}

const themeOptions = [
  {
    id: 'dark',
    name: 'Espresso Noir',
    label: 'Warm Dark',
    mode: 'dark',
    previewClass: 'theme-preview theme-preview--dark',
    previewType: 'bars',
  },
  {
    id: 'light',
    name: 'Parchment',
    label: 'Soft Light',
    mode: 'light',
    previewClass: 'theme-preview theme-preview--light',
    previewType: 'bars',
  },
  {
    id: 'academic-dark',
    name: 'Midnight',
    label: 'Focus Dark',
    mode: 'academic-dark',
    previewClass: 'theme-preview theme-preview--academic-dark',
    previewType: 'bars',
  },
  {
    id: 'academic-light',
    name: 'Day Light',
    label: 'Clear Light',
    mode: 'academic-light',
    previewClass: 'theme-preview theme-preview--academic-light',
    previewType: 'bars',
  },
  {
    id: 'aurora-dark',
    name: 'Jade Horizon',
    label: 'Aurora Dark',
    mode: 'aurora-dark',
    previewClass: 'theme-preview theme-preview--aurora-dark',
    previewType: 'aurora',
  },
  {
    id: 'sonoct-light',
    name: 'Sea Glass',
    label: 'Coastal Light',
    mode: 'sonoct-light',
    previewClass: 'theme-preview theme-preview--sonoct-light',
    previewType: 'command',
  },
]

const fallbackProviders = [
  { id: 'auto', label: 'Auto (recommended)' },
  { id: 'openrouter', label: 'OpenRouter' },
]

export default function Settings() {
  const settings = useAppStore((state) => state.settings)
  const updateSettings = useAppStore((state) => state.updateSettings)
  const providers = useAppStore((state) => state.providers)
  const providerUsage = useAppStore((state) => state.providerUsage)
  const refreshProviderUsage = useAppStore((state) => state.refreshProviderUsage)

  // Refresh the quota meters whenever the Settings page is opened, so the
  // numbers reflect the current window rather than whatever was loaded at boot.
  useEffect(() => {
    refreshProviderUsage()
  }, [refreshProviderUsage])

  const current = settings || {
    endpoint: '/api',
    model: 'Mistral 7B Instruct',
    streamResponses: true,
    autoSync: true,
    theme: 'dark',
    provider: 'openrouter',
  }

  const providerOptions = providers?.length ? providers : fallbackProviders
  const activeProvider = current.provider || 'auto'

  const setSetting = (patch) => {
    updateSettings(patch)
  }

  return (
    <section className="page settings-page">
      <div className="section__header settings-page__header">
        <div>
          <h2 className="section__title">Settings</h2>
          <p className="section__subtitle">
            Model behavior and appearance. Changes are saved automatically.
          </p>
        </div>
      </div>

      <motion.section
        className="settings-panel"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div className="settings-panel__heading">
          <div className="settings-panel__title-wrap">
            <SlidersHorizontal size={16} />
            <h3 className="settings-panel__title">Model Configuration</h3>
          </div>
          <span className="settings-panel__rule" />
        </div>

        <div className="setting-row provider-row">
          <div className="provider-row__head">
            <div className="settings-panel__title-wrap">
              <Server size={15} />
              <label>Model Provider</label>
            </div>
            <p className="setting-help">
              Preferred provider for answering. It's a soft preference — if it's
              rate-limited or down, the pipeline automatically falls back to the
              others. <strong>Auto</strong> uses the best provider per task.
            </p>
          </div>
          <div className="provider-grid">
            {providerOptions.map((option) => {
              const active = activeProvider === option.id
              return (
                <button
                  key={option.id}
                  type="button"
                  className={`provider-chip ${active ? 'provider-chip--active' : ''}`}
                  onClick={() => setSetting({ provider: option.id })}
                >
                  <span className="provider-chip__label">{option.label}</span>
                  {active ? (
                    <span className="provider-chip__check">
                      <Check size={12} />
                    </span>
                  ) : null}
                </button>
              )
            })}
          </div>
        </div>
      </motion.section>

      <motion.section
        className="settings-panel"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.05 }}
      >
        <div className="settings-panel__heading">
          <div className="settings-panel__title-wrap">
            <Gauge size={16} />
            <h3 className="settings-panel__title">Provider Usage</h3>
          </div>
          <button
            type="button"
            className="usage-refresh"
            onClick={() => refreshProviderUsage()}
            aria-label="Refresh usage"
            title="Refresh usage"
          >
            <RotateCw size={13} />
          </button>
          <span className="settings-panel__rule" />
        </div>

        <div className="setting-row">
          <p className="setting-help">
            Live free-tier consumption per provider, tracked across every request
            in this session. Each provider falls back automatically when its
            per-minute or per-day window fills up.
          </p>

          {providerUsage?.length ? (
            <div className="usage-list">
              {providerUsage.map((p) => {
                const rpm = meter(p.rpmUsed, p.rpmLimit)
                const rpd = meter(p.rpdUsed, p.rpdLimit)
                const cooling = Number(p.backoffSeconds) > 0
                return (
                  <div key={p.id} className="usage-card">
                    <div className="usage-card__head">
                      <span className="usage-card__name">{p.label}</span>
                      {cooling ? (
                        <span className="usage-card__cooldown">
                          cooling down {Math.ceil(p.backoffSeconds)}s
                        </span>
                      ) : null}
                    </div>

                    <div className="usage-meter">
                      <div className="usage-meter__label">
                        <span>Per minute</span>
                        <span className="usage-meter__count">
                          {p.rpmUsed} / {p.rpmLimit}
                        </span>
                      </div>
                      <div className="usage-track">
                        <div
                          className={`usage-fill usage-fill--${rpm.level}`}
                          style={{ width: `${rpm.pct}%` }}
                        />
                      </div>
                    </div>

                    <div className="usage-meter">
                      <div className="usage-meter__label">
                        <span>Per day</span>
                        <span className="usage-meter__count">
                          {p.rpdUsed} / {p.rpdLimit}
                        </span>
                      </div>
                      <div className="usage-track">
                        <div
                          className={`usage-fill usage-fill--${rpd.level}`}
                          style={{ width: `${rpd.pct}%` }}
                        />
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          ) : (
            <p className="usage-empty">
              No providers configured, or usage isn't available yet.
            </p>
          )}
        </div>
      </motion.section>

      <motion.section
        className="settings-panel"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.06 }}
      >
        <div className="settings-panel__heading">
          <div className="settings-panel__title-wrap">
            <Sparkles size={16} />
            <h3 className="settings-panel__title">Appearance</h3>
          </div>
          <span className="settings-panel__rule" />
        </div>

        <div className="setting-row">
          <label>Theme Selection</label>
          <div className="theme-grid">
            {themeOptions.map((theme) => {
              const active = current.theme === theme.mode
              return (
                <button
                  key={theme.id}
                  type="button"
                  className={`theme-card ${active ? 'theme-card--active' : ''}`}
                  onClick={() => setSetting({ theme: theme.mode })}
                >
                  <div className={theme.previewClass}>
                    {theme.previewType === 'command' ? (
                      <>
                        <div className="theme-preview__command-bar" />
                        <div className="theme-preview__command-shell">
                          <div className="theme-preview__command-rail">
                            <span className="theme-preview__command-badge" />
                            <span className="theme-preview__command-line" />
                            <span className="theme-preview__command-line theme-preview__command-line--short" />
                          </div>
                          <div className="theme-preview__command-panel">
                            <span className="theme-preview__command-title" />
                            <span className="theme-preview__command-copy" />
                            <div className="theme-preview__command-card" />
                          </div>
                        </div>
                      </>
                    ) : theme.previewType === 'aurora' ? (
                      <>
                        <div className="theme-preview__aurora-glow" />
                        <div className="theme-preview__bar theme-preview__bar--primary" />
                        <div className="theme-preview__bar" />
                        <div className="theme-preview__bar theme-preview__bar--secondary" />
                      </>
                    ) : (
                      <>
                        <div className="theme-preview__bar theme-preview__bar--primary" />
                        <div className="theme-preview__bar" />
                        <div className="theme-preview__bar theme-preview__bar--secondary" />
                      </>
                    )}
                    {active ? (
                      <span className="theme-card__check">
                        <Check size={12} />
                      </span>
                    ) : null}
                  </div>
                  <div className="theme-card__meta">
                    <strong className="theme-card__name">{theme.name}</strong>
                    <span className="theme-card__label">{theme.label}</span>
                  </div>
                </button>
              )
            })}
          </div>
        </div>
      </motion.section>
    </section>
  )
}
