import { Check, Server, SlidersHorizontal, Sparkles } from 'lucide-react'
import { motion } from 'framer-motion'
import { useAppStore } from '../store/store.js'

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

const contextOptions = ['2048 tokens', '4096 tokens', '8192 tokens']
const topPOptions = ['0.7', '0.8', '0.9 (Standard)', '1.0']

const fallbackProviders = [
  { id: 'auto', label: 'Auto (recommended)' },
  { id: 'openrouter', label: 'OpenRouter' },
]

export default function Settings() {
  const settings = useAppStore((state) => state.settings)
  const updateSettings = useAppStore((state) => state.updateSettings)
  const providers = useAppStore((state) => state.providers)

  const current = settings || {
    endpoint: '/api',
    model: 'Mistral 7B Instruct',
    temperature: 0.4,
    topP: '0.9',
    contextLength: '4096',
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

        <div className="slider-row">
          <div>
            <label htmlFor="temperature">Temperature</label>
            <p className="setting-help">
              Higher values make output more creative, lower values more focused.
            </p>
          </div>
          <div className="value-chip">{Number(current.temperature).toFixed(1)}</div>
        </div>
        <input
          id="temperature"
          className="range-input"
          type="range"
          min="0"
          max="1"
          step="0.1"
          value={current.temperature}
          onChange={(event) => setSetting({ temperature: Number(event.target.value) })}
        />

        <div className="settings-grid">
          <div className="setting-row">
            <label htmlFor="topP">Top-P Sampling</label>
            <select
              id="topP"
              className="select-input"
              value={current.topP}
              onChange={(event) => setSetting({ topP: event.target.value })}
            >
              {topPOptions.map((option) => (
                <option key={option} value={option.split(' ')[0]}>
                  {option}
                </option>
              ))}
            </select>
          </div>

          <div className="setting-row">
            <label htmlFor="contextLength">Context Length</label>
            <select
              id="contextLength"
              className="select-input"
              value={current.contextLength}
              onChange={(event) => setSetting({ contextLength: event.target.value })}
            >
              {contextOptions.map((option) => (
                <option key={option} value={option.replace(' tokens', '')}>
                  {option}
                </option>
              ))}
            </select>
          </div>
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
