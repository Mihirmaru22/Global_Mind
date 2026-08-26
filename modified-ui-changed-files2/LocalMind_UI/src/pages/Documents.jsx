import { useRef, useState } from 'react'
import dayjs from 'dayjs'
import {
  Check,
  FileText,
  Library,
  Loader2,
  Minus,
  RotateCcw,
  Trash2,
  Upload,
  X,
} from 'lucide-react'
import { toast } from 'sonner'
import { useAppStore } from '../store/store.js'

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

function StepIcon({ status }) {
  if (status === 'done') return <Check size={13} className="ingest-step__icon ingest-step__icon--done" />
  if (status === 'error') return <X size={13} className="ingest-step__icon ingest-step__icon--error" />
  if (status === 'skipped') return <Minus size={13} className="ingest-step__icon ingest-step__icon--skipped" />
  if (status === 'running')
    return <Loader2 size={13} className="ingest-step__icon ingest-step__icon--running" />
  return <span className="ingest-step__dot" aria-hidden="true" />
}

export default function Documents() {
  const documents = useAppStore((state) => state.documents)
  const selectedDocId = useAppStore((state) => state.selectedDocId)
  const selectDocument = useAppStore((state) => state.selectDocument)
  const ingestDocument = useAppStore((state) => state.ingestDocument)
  const replaceDocument = useAppStore((state) => state.replaceDocument)
  const deleteDocument = useAppStore((state) => state.deleteDocument)
  const ingestionProgress = useAppStore((state) => state.ingestionProgress)
  const clearIngestionProgress = useAppStore((state) => state.clearIngestionProgress)

  const uploadInputRef = useRef(null)
  const replaceInputRef = useRef(null)
  const replaceTargetRef = useRef(null)
  const [isUploading, setIsUploading] = useState(false)
  const [busyId, setBusyId] = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null)

  const handleUploadClick = () => uploadInputRef.current?.click()

  const handleUploadFileChosen = async (event) => {
    const file = event.target.files?.[0]
    if (!file) return
    try {
      setIsUploading(true)
      selectDocument(null)
      await ingestDocument(file)
    } catch (error) {
      console.error(error)
      toast.error('Upload failed. Check server logs.')
    } finally {
      setIsUploading(false)
      if (uploadInputRef.current) uploadInputRef.current.value = ''
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
      selectDocument(null)
      await replaceDocument(targetId, file)
    } finally {
      setBusyId(null)
      replaceTargetRef.current = null
    }
  }

  const confirmDelete = async () => {
    if (!deleteTarget) return
    setBusyId(deleteTarget.id)
    try {
      await deleteDocument(deleteTarget.id)
      if (selectedDocId === deleteTarget.id) selectDocument(null)
    } finally {
      setBusyId(null)
      setDeleteTarget(null)
    }
  }

  const selectedDoc = documents.find((d) => d.id === selectedDocId) || null
  // Live progress always wins the panel — if something's actively ingesting,
  // that's what you came here to watch.
  const showingLive = Boolean(ingestionProgress)

  const handleSelectRow = (doc) => {
    if (ingestionProgress) clearIngestionProgress()
    selectDocument(selectedDocId === doc.id ? null : doc.id)
  }

  return (
    <section className="page documents-page">
      <div className="section__header settings-page__header">
        <div>
          <h2 className="section__title">Documents</h2>
          <p className="section__subtitle">
            Upload files to your knowledge base. Ingestion happens here — no chat is created.
          </p>
        </div>
        <div className="section__header-actions">
          <button type="button" className="primary-button" disabled={isUploading} onClick={handleUploadClick}>
            {isUploading ? <Loader2 size={16} className="spin" /> : <Upload size={16} />}
            <span>{isUploading ? 'Ingesting…' : 'Upload'}</span>
          </button>
        </div>
      </div>

      <input ref={uploadInputRef} type="file" style={{ display: 'none' }} onChange={handleUploadFileChosen} />
      <input ref={replaceInputRef} type="file" style={{ display: 'none' }} onChange={onReplaceFileChosen} />

      <div className="documents-layout">
        <div className="documents-layout__list">
          {documents.length === 0 ? (
            <div className="documents-empty">
              <Library size={22} className="documents-empty__icon" />
              <p>No documents yet.</p>
              <p className="documents-empty__hint">Upload a file to add it to the knowledge base.</p>
            </div>
          ) : (
            <div className="doc-list">
              {documents.map((doc) => (
                <button
                  key={doc.id}
                  type="button"
                  className={`doc-row doc-row--selectable ${selectedDocId === doc.id && !showingLive ? 'doc-row--active' : ''}`}
                  onClick={() => handleSelectRow(doc)}
                >
                  <FileText size={16} className="doc-row__icon" />
                  <div className="doc-row__body">
                    <p className="doc-row__title">
                      {doc.name}
                      {doc.versionCount > 1 ? <span className="doc-row__badge"> · v{doc.versionCount}</span> : null}
                    </p>
                    <p className="doc-row__meta">
                      {fileExtension(doc.name)} · {formatBytes(doc.sizeBytes)} · {doc.chunks ?? 0} chunks
                      {doc.ingestedAt ? ` · Added ${dayjs(doc.ingestedAt).format('MMM D, HH:mm')}` : ''}
                    </p>
                  </div>
                  <div className="doc-row__actions">
                    <button
                      type="button"
                      className="icon-button"
                      title="Reupload / replace"
                      disabled={busyId === doc.id}
                      onClick={(e) => { e.stopPropagation(); openReplacePicker(doc.id) }}
                    >
                      <RotateCcw size={15} />
                    </button>
                    <button
                      type="button"
                      className="icon-button icon-button--danger"
                      title="Delete"
                      disabled={busyId === doc.id}
                      onClick={(e) => { e.stopPropagation(); setDeleteTarget(doc) }}
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="documents-layout__stages">
          <div className="ingestion-panel">
            <h3 className="ingestion-panel__title">Ingestion Stages</h3>

            {showingLive ? (
              <>
                <div className="ingestion-panel__file">
                  <FileText size={15} />
                  <span>{ingestionProgress.fileName}</span>
                </div>
                <ol className="ingest-card__steps">
                  {ingestionProgress.steps.map((step) => (
                    <li key={step.stage} className={`ingest-step ingest-step--${step.status}`}>
                      <StepIcon status={step.status} />
                      <span className="ingest-step__label">{step.label}</span>
                      {step.detail ? <span className="ingest-step__detail">{step.detail}</span> : null}
                    </li>
                  ))}
                </ol>
                {ingestionProgress.content && ingestionProgress.status !== 'running' ? (
                  <p className="ingest-card__summary">{ingestionProgress.content}</p>
                ) : null}
              </>
            ) : selectedDoc ? (
              <>
                <div className="ingestion-panel__file">
                  <FileText size={15} />
                  <span>{selectedDoc.name}</span>
                </div>
                {/* The backend only stores aggregate metadata for a document
                    that finished ingesting in a past session — not the
                    original stage-by-stage trace. So a previously-ingested
                    document gets an honest summary, not a fabricated replay
                    of steps that weren't actually recorded. */}
                <div className="ingestion-panel__summary-grid">
                  <div>
                    <span className="ingestion-panel__summary-label">Chunks</span>
                    <span className="ingestion-panel__summary-value">{selectedDoc.chunks ?? 0}</span>
                  </div>
                  <div>
                    <span className="ingestion-panel__summary-label">Size</span>
                    <span className="ingestion-panel__summary-value">{formatBytes(selectedDoc.sizeBytes)}</span>
                  </div>
                  <div>
                    <span className="ingestion-panel__summary-label">Added</span>
                    <span className="ingestion-panel__summary-value">
                      {selectedDoc.ingestedAt ? dayjs(selectedDoc.ingestedAt).format('MMM D, YYYY') : '—'}
                    </span>
                  </div>
                  <div>
                    <span className="ingestion-panel__summary-label">Versions</span>
                    <span className="ingestion-panel__summary-value">{selectedDoc.versionCount ?? 1}</span>
                  </div>
                </div>
                <p className="ingestion-panel__note">
                  Already ingested — live per-stage detail is only available while a document is actively processing.
                  Reupload to watch it run again.
                </p>
              </>
            ) : (
              <div className="ingestion-panel__empty">
                <p>Select a document to see its details, or upload a new one to watch it ingest live.</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {deleteTarget ? (
        <div className="dialog-backdrop" role="presentation" onClick={() => setDeleteTarget(null)}>
          <div className="dialog-card" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
            <p className="dialog-card__eyebrow">Document</p>
            <h3 className="dialog-card__title">Delete document</h3>
            <p className="dialog-card__text">
              This removes "{deleteTarget.name}" from the knowledge base. This can't be undone.
            </p>
            <div className="dialog-card__actions">
              <button type="button" className="secondary-button" onClick={() => setDeleteTarget(null)}>Cancel</button>
              <button type="button" className="primary-button primary-button--danger" onClick={confirmDelete}>
                Delete
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  )
}
