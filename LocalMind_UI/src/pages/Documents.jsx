import dayjs from 'dayjs'
import { motion } from 'framer-motion'
import { FileUp, RefreshCw } from 'lucide-react'
import Button from '../components/Button.jsx'
import Card from '../components/Card.jsx'
import Loader from '../components/Loader.jsx'
import { useAppStore } from '../store/store.js'

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
                {doc.type} · {doc.size} · Updated {dayjs(doc.updatedAt).format('MMM D, HH:mm')}
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
