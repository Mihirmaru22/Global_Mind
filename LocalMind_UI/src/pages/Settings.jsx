import { useState } from 'react'
import { Check, CheckCircle2, Database, Loader2, Palette } from 'lucide-react'
import { AnimatePresence, motion } from 'framer-motion'
import { useAppStore } from '../store/store.js'

const THEME_OPTIONS = [
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
  { value: 'system', label: 'System' },
]

function ThemePreview({ mode }) {
  return (
    <span className={`theme-preview theme-preview--${mode}`} aria-hidden="true">
      <span className="theme-preview__sidebar">
        <span className="theme-preview__brand" />
        <span className="theme-preview__nav-item" />
        <span className="theme-preview__nav-item" />
        <span className="theme-preview__nav-item" />
      </span>
      <span className="theme-preview__main">
        <span className="theme-preview__topbar" />
        <span className="theme-preview__messages">
          <span className="theme-preview__msg theme-preview__msg--assistant" />
          <span className="theme-preview__msg theme-preview__msg--user" />
          <span className="theme-preview__msg theme-preview__msg--assistant theme-preview__msg--short" />
        </span>
        <span className="theme-preview__composer" />
      </span>
    </span>
  )
}

export default function Settings() {
  const settings = useAppStore((state) => state.settings)
  const updateSettings = useAppStore((state) => state.updateSettings)
  const runSchemaSync = useAppStore((state) => state.runSchemaSync)
  const [schemaStatus, setSchemaStatus] = useState('idle')
  const [syncResult, setSyncResult] = useState(null)

  const current = settings || { theme: 'light' }
  const setSetting = (patch) => updateSettings(patch)

  const handleSchemaSync = async () => {
    setSchemaStatus('syncing')
    setSyncResult(null)

    const result = await runSchemaSync()
    if (result?.ok === false) {
      setSchemaStatus('failed')
      setSyncResult(null)
      return
    }

    setSchemaStatus('complete')
    setSyncResult(result)
  }

  return (
    <section className="page settings-page">
      <div className="settings-page__header">
        <h2 className="settings-page__title">Settings</h2>
        <p className="settings-page__subtitle">Appearance and data preferences.</p>
      </div>

      <motion.section
        className="settings-card"
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div className="settings-card__heading">
          <Palette size={15} />
          <h3 className="settings-card__title">Appearance</h3>
        </div>
        <p className="settings-card__desc">Choose how LocalMind looks.</p>

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
                <ThemePreview mode={option.value} />
                <span className="theme-option__label">
                  {option.label}
                  {selected ? <Check size={12} strokeWidth={3} className="theme-option__check" /> : null}
                </span>
              </button>
            )
          })}
        </div>
      </motion.section>

      <motion.section
        className="settings-card"
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.06 }}
      >
        <div className="settings-card__heading">
          <Database size={15} />
          <h3 className="settings-card__title">Database Sync</h3>
        </div>
        <p className="settings-card__desc">
          Keep LocalMind's understanding of your database up to date.
        </p>

        <div className="sync-card">
          <div className="sync-card__meta">
            <div className="sync-card__row">
              <span className="sync-card__label">Last sync</span>
              <span className="sync-card__value">
                {syncResult?.last_synced ? new Date(syncResult.last_synced).toLocaleString() : '-'}
              </span>
            </div>
            {syncResult?.table_count != null ? (
              <div className="sync-card__row">
                <span className="sync-card__label">Tables</span>
                <span className="sync-card__value">{syncResult.table_count}</span>
              </div>
            ) : null}
            <div className="sync-card__row">
              <span className="sync-card__label">Status</span>
              <span className={`sync-card__status sync-card__status--${schemaStatus === 'failed' ? 'error' : 'ok'}`}>
                {schemaStatus === 'idle'
                  ? 'Ready'
                  : schemaStatus === 'syncing'
                    ? 'Syncing...'
                    : schemaStatus === 'complete'
                      ? 'Connected'
                      : 'Failed'}
              </span>
            </div>
          </div>

          <button
            type="button"
            className="sync-card__btn"
            onClick={handleSchemaSync}
            disabled={schemaStatus === 'syncing'}
          >
            {schemaStatus === 'syncing' ? (
              <>
                <Loader2 size={14} className="spin" />
                <span>Syncing schema...</span>
              </>
            ) : (
              <span>Sync database schema</span>
            )}
          </button>

          <AnimatePresence>
            {schemaStatus === 'complete' ? (
              <motion.p
                className="sync-card__result sync-card__result--success"
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
              >
                <CheckCircle2 size={14} />
                Schema synchronized
                {syncResult?.tables_updated != null ? ` - ${syncResult.tables_updated} tables updated` : ''}
              </motion.p>
            ) : schemaStatus === 'failed' ? (
              <motion.p
                className="sync-card__result sync-card__result--error"
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
              >
                Sync failed. Try again.
              </motion.p>
            ) : null}
          </AnimatePresence>
        </div>
      </motion.section>
    </section>
  )
}
