import { Check, SlidersHorizontal, Sparkles } from 'lucide-react'
import { motion } from 'framer-motion'
import { useAppStore } from '../store/store.js'

const themeOptions = [
  {
    id: 'dark',
    name: 'Obsidian Hearth',
    label: 'Active',
    mode: 'dark',
    previewClass: 'theme-preview theme-preview--dark',
  },
  {
    id: 'light',
    name: 'Warm Minimalist',
    label: 'Light mode',
    mode: 'light',
    previewClass: 'theme-preview theme-preview--light',
  },
]

const contextOptions = ['2048 tokens', '4096 tokens', '8192 tokens']
const topPOptions = ['0.7', '0.8', '0.9 (Standard)', '1.0']

export default function Settings() {
  const settings = useAppStore((state) => state.settings)
  const updateSettings = useAppStore((state) => state.updateSettings)

  const current = settings || {
    endpoint: '/api',
    model: 'Mistral 7B Instruct',
    temperature: 0.4,
    topP: '0.9',
    contextLength: '4096',
    streamResponses: true,
    autoSync: true,
    theme: 'dark',
  }

  const setSetting = (patch) => {
    updateSettings(patch)
  }

  return (
    <section className="page settings-page">
      <div className="section__header settings-page__header">
        <div>
          <h2 className="section__title">Settings</h2>
          <p className="section__subtitle">
            Minimal controls for model behavior and appearance. Demo values are
            shown now, with API-backed settings ready later.
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
                    <div className="theme-preview__bar theme-preview__bar--primary" />
                    <div className="theme-preview__bar" />
                    <div className="theme-preview__bar theme-preview__bar--secondary" />
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

        {/* <div className="settings-actions">
          <Button onClick={() => updateSettings(current)}>Save Settings</Button>
        </div> */}
      </motion.section>
    </section>
  )
}
