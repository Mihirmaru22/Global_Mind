import { useRef, useState } from 'react'
import dayjs from 'dayjs'
import { Check, Sparkles, Database, RefreshCw, RotateCcw, Trash2, Upload, Loader2 } from 'lucide-react'
import { motion } from 'framer-motion'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import Button from '../components/Button.jsx'
import Loader from '../components/Loader.jsx'
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

function formatBytes(bytes) {
  const value = Number(bytes)
  if (!value || value < 0) return '—'
  const units = ['B', 'KB', 'MB', 'GB']
  let size = value
  let unit = 0
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024
    unit += 1
  }
  return `${size < 10 && unit > 0 ? size.toFixed(1) : Math.round(size)} ${units[unit]}`
}

function fileExtension(name) {
  const dot = (name || '').lastIndexOf('.')
  return dot > 0 ? name.slice(dot + 1).toUpperCase() : 'FILE'
}

export default function Settings() {
  // Settings state
  const settings = useAppStore((state) => state.settings)
  const updateSettings = useAppStore((state) => state.updateSettings)
  const runSchemaSync = useAppStore((state) => state.runSchemaSync)

  // Documents state
  const documents = useAppStore((state) => state.documents)
  const refreshDocuments = useAppStore((state) => state.refreshDocuments)
  const replaceDocument = useAppStore((state) => state.replaceDocument)
  const deleteDocument = useAppStore((state) => state.deleteDocument)
  const ingestDocument = useAppStore((state) => state.ingestDocument)
  const loading = useAppStore((state) => state.loading)

  const navigate = useNavigate()
  const replaceInputRef = useRef(null)
  const replaceTargetRef = useRef(null)
  const uploadInputRef = useRef(null)
  const [busyId, setBusyId] = useState(null)
  const [isUploading, setIsUploading] = useState(false)

  const current = settings || {
    endpoint: '/api',
    model: 'Mistral 7B Instruct',
    streamResponses: true,
    autoSync: true,
    theme: 'dark',
  }

  const setSetting = (patch) => {
    updateSettings(patch)
  }

  const handleUploadClick = () => {
    uploadInputRef.current?.click()
  }

  const handleUploadFileChosen = async (event) => {
    const file = event.target.files?.[0]
    if (!file) return

    try {
      setIsUploading(true)
      navigate('/chat')
      await ingestDocument(file)
    } catch (error) {
      console.error(error)
      toast.error(`Upload failed. Check server logs.`)
    } finally {
      setIsUploading(false)
      if (uploadInputRef.current) {
        uploadInputRef.current.value = ''
      }
    }
  }

  const openReplacePicker = (docId) => {
    replaceTargetRef.current = docId
    if (replaceInputRef.current) {
      replaceInputRef.current.value = ''
      replaceInputRef.current.click()
    }
  }

  const onReplaceFileChosen = async (event) => {
    const file = event.target.files?.[0]
    const targetId = replaceTargetRef.current
    if (!file || !targetId) return
    setBusyId(targetId)
    try {
      navigate('/chat')
      await replaceDocument(targetId, file)
    } finally {
      setBusyId(null)
      replaceTargetRef.current = null
    }
  }

  const onDelete = async (doc) => {
    if (!window.confirm(`Delete "${doc.name}"? This removes it from the knowledge base.`)) {
      return
    }
    setBusyId(doc.id)
    try {
      await deleteDocument(doc.id)
    } finally {
      setBusyId(null)
    }
  }

  return (
    <section className="page settings-page">
      <div className="section__header settings-page__header">
        <div>
          <h2 className="section__title">Settings</h2>
        </div>
      </div>

      {/* --- Documents --- */}
      <motion.section
        className="settings-panel"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div className="settings-panel__heading">
          <div className="settings-panel__title-wrap">
            <h3 className="settings-panel__title">Documents</h3>
          </div>
          <span className="settings-panel__rule" />
          <div className="section__header-actions">
            <Button
              variant="secondary"
              className="section__header-btn"
              disabled={isUploading}
              onClick={handleUploadClick}
            >
              {isUploading ? <Loader2 size={16} className="spin" /> : <Upload size={16} />}
              <span>{isUploading ? 'Ingesting...' : 'Upload'}</span>
            </Button>
            <Button variant="secondary" className="section__header-btn" onClick={refreshDocuments}>
              <RefreshCw size={16} />
              <span>Refresh</span>
            </Button>
          </div>
        </div>

        {loading ? <Loader /> : null}

        <input
          ref={uploadInputRef}
          type="file"
          style={{ display: 'none' }}
          onChange={handleUploadFileChosen}
        />
        <input
          ref={replaceInputRef}
          type="file"
          style={{ display: 'none' }}
          onChange={onReplaceFileChosen}
        />

        <div className="doc-list">
          {documents.length === 0 && !loading ? (
            <p className="section__subtitle">
              No documents yet. Upload a file to ingest it.
            </p>
          ) : null}

          {documents.map((doc, index) => (
            <motion.article
              key={doc.id}
              className="doc-row"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.03 }}
            >
              <div>
                <p className="doc-row__title">
                  {doc.name}
                  {doc.versionCount > 1 ? (
                    <span className="doc-row__badge"> · v{doc.versionCount}</span>
                  ) : null}
                </p>
                <p className="doc-row__meta">
                  {fileExtension(doc.name)} · {formatBytes(doc.sizeBytes)} · {doc.chunks ?? 0} chunks
                  {doc.ingestedAt ? ` · Added ${dayjs(doc.ingestedAt).format('MMM D, HH:mm')}` : ''}
                </p>
              </div>
              <div className="doc-row__actions">
                <Button
                  variant="secondary"
                  disabled={busyId === doc.id}
                  onClick={() => openReplacePicker(doc.id)}
                >
                  <RotateCcw size={16} />
                  <span>Replace</span>
                </Button>
                <Button
                  variant="danger"
                  disabled={busyId === doc.id}
                  onClick={() => onDelete(doc)}
                >
                  <Trash2 size={16} />
                  <span>Delete</span>
                </Button>
              </div>
            </motion.article>
          ))}
        </div>
      </motion.section>

      {/* --- Data Management --- */}
      <motion.section
        className="settings-panel"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.06 }}
      >
        <div className="settings-panel__heading">
          <div className="settings-panel__title-wrap">
            <Database size={16} />
            <h3 className="settings-panel__title">Data Management</h3>
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

      {/* --- Appearance --- */}
      <motion.section
        className="settings-panel"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.12 }}
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
