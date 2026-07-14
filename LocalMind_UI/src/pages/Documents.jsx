import dayjs from 'dayjs'
import { motion } from 'framer-motion'
import { FileUp, RefreshCw } from 'lucide-react'
import Button from '../components/Button.jsx'
import Card from '../components/Card.jsx'
import Loader from '../components/Loader.jsx'
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

export default function Documents() {
  const documents = useAppStore((state) => state.documents)
  const refreshDocuments = useAppStore((state) => state.refreshDocuments)
  const loading = useAppStore((state) => state.loading)

  return (
    <section className="page section">
      <div className="section__header">
        <div>
          <h2 className="section__title">Documents</h2>
          <p className="section__subtitle">
            This view is using static demo documents for now.
          </p>
        </div>
        <Button variant="secondary" onClick={refreshDocuments}>
          <RefreshCw size={16} />
          <span>Refresh</span>
        </Button>
      </div>

      <div className="grid">
        <Card label="Upload" title="Add local files">
          Connect your upload endpoint here when the API is ready.
        </Card>
        <Card label="Sync" title="Backend-ready list">
          Document rows below will render directly from your API response later.
        </Card>
      </div>

      {loading ? <Loader /> : null}

      <div className="doc-list">
        {documents.map((doc, index) => (
          <motion.article
            key={doc.id}
            className="doc-row"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.03 }}
          >
            <div>
              <p className="doc-row__title">{doc.name}</p>
              <p className="doc-row__meta">
                {fileExtension(doc.name)} · {formatBytes(doc.sizeBytes)} · {doc.chunks ?? 0} chunks
                {doc.ingestedAt ? ` · Ingested ${dayjs(doc.ingestedAt).format('MMM D, HH:mm')}` : ''}
              </p>
            </div>
            <Button variant="secondary">
              <FileUp size={16} />
              <span>Open</span>
            </Button>
          </motion.article>
        ))}
      </div>
    </section>
  )
}
