import { Check, Database, Sparkles } from 'lucide-react'
import { motion } from 'framer-motion'
import Button from '../components/Button.jsx'
import { useAppStore } from '../store/store.js'

const THEME_OPTIONS = [
  { value: 'dark', label: 'Dark' },
  { value: 'light', label: 'Light' },
  { value: 'system', label: 'System' },
]

export default function Settings() {
  const settings = useAppStore((state) => state.settings)
  const updateSettings = useAppStore((state) => state.updateSettings)
  const runSchemaSync = useAppStore((state) => state.runSchemaSync)

  const current = settings || { theme: 'light' }
  const setSetting = (patch) => updateSettings(patch)

  return (
    <section className="page settings-page">
      <div className="section__header settings-page__header">
        <div>
          <h2 className="section__title">Settings</h2>
        </div>
      </div>

      {/* --- Appearance --- */}
      <motion.section
        className="settings-panel"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div className="settings-panel__heading">
          <div className="settings-panel__title-wrap">
            <Sparkles size={16} />
            <h3 className="settings-panel__title">Appearance</h3>
          </div>
          <span className="settings-panel__rule" />
        </div>

        <div className="setting-row">
          <label>Theme</label>
          <div className="theme-picker" role="radiogroup" aria-label="Theme">
            {THEME_OPTIONS.map((option) => {
              const selected = current.theme === option.value
              return (
                <button
                  key={option.value}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  className={`theme-option ${selected ? 'theme-option--selected' : ''}`}
                  onClick={() => setSetting({ theme: option.value })}
                >
                  {option.value === 'system' ? (
                    <span className="theme-option__preview theme-option__preview--system">
                      <span className="theme-option__preview-rail" />
                      <span className="theme-option__preview-system theme-option__preview-system--dark">
                        <span className="theme-option__preview-bar theme-option__preview-bar--accent" />
                        <span className="theme-option__preview-bar" />
                        <span className="theme-option__preview-bar" />
                      </span>
                      <span className="theme-option__preview-system theme-option__preview-system--light">
                        <span className="theme-option__preview-bar theme-option__preview-bar--accent" />
                        <span className="theme-option__preview-bar" />
                        <span className="theme-option__preview-bar" />
                      </span>
                      {selected ? (
                        <span className="theme-option__check"><Check size={11} strokeWidth={3} /></span>
                      ) : null}
                    </span>
                  ) : (
                    <span className={`theme-option__preview theme-option__preview--${option.value}`}>
                      <span className="theme-option__preview-rail" />
                      <span className="theme-option__preview-body">
                        <span className="theme-option__preview-bar theme-option__preview-bar--accent" />
                        <span className="theme-option__preview-bar" />
                        <span className="theme-option__preview-bar" />
                      </span>
                      {selected ? (
                        <span className="theme-option__check"><Check size={11} strokeWidth={3} /></span>
                      ) : null}
                    </span>
                  )}
                  <span className="theme-option__label">{option.label}</span>
                </button>
              )
            })}
          </div>
        </div>
      </motion.section>

      {/* --- Data Sync --- */}
      <motion.section
        className="settings-panel"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.06 }}
      >
        <div className="settings-panel__heading">
          <div className="settings-panel__title-wrap">
            <Database size={16} />
            <h3 className="settings-panel__title">Data Sync</h3>
          </div>
          <span className="settings-panel__rule" />
        </div>

        <div className="setting-row">
          <label>Database Schema Sync</label>
          <p className="setting-help">
            Fetches your live database tables, chunks them, and embeds them into the vector store.
            Run this whenever you add, alter, or drop tables in your database so the AI knows about them.
          </p>
          <div style={{ marginTop: '1rem' }}>
            <Button variant="primary" onClick={() => runSchemaSync()}>
              Sync Database Schema
            </Button>
          </div>
        </div>
      </motion.section>
    </section>
  )
}
