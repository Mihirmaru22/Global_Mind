import { useState, useMemo, useRef, useEffect } from 'react'
import { Database, ChevronDown, ChevronRight, Copy, Check, Table2 } from 'lucide-react'
import clsx from 'clsx'
import hljs from 'highlight.js'
import { toast } from 'sonner'

const PAGE_SIZE = 5

function formatHeader(key) {
  if (!key) return ''
  if (key.toLowerCase() === 'id') return 'ID'
  return key
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

function formatSql(query) {
  if (!query) return ''
  // Clean multiline query and format common SQL clauses onto distinct lines for readability
  let cleaned = query
    .split('\n')
    .map((l) => l.replace(/--.*$/, '').trim())
    .filter(Boolean)
    .join(' ')

  const keywords = ['SELECT', 'FROM', 'JOIN', 'LEFT JOIN', 'RIGHT JOIN', 'INNER JOIN', 'WHERE', 'GROUP BY', 'HAVING', 'ORDER BY', 'LIMIT']
  for (const kw of keywords) {
    const re = new RegExp(`\\b${kw}\\b`, 'gi')
    cleaned = cleaned.replace(re, (match) => `\n${match.toUpperCase()}`)
  }
  return cleaned.trim()
}

export default function DatabaseResultCard({ payload }) {
  const [sqlOpen, setSqlOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const [visibleRows, setVisibleRows] = useState(PAGE_SIZE)
  const copyTimeoutRef = useRef(null)

  const query = payload?.query || ''
  const rows = payload?.rows || []
  const columns = useMemo(() => {
    if (payload?.columns && payload.columns.length > 0) {
      return payload.columns
    }
    if (rows.length > 0) {
      return Object.keys(rows[0])
    }
    return []
  }, [payload?.columns, rows])

  const totalRows = payload?.row_count ?? rows.length
  const highlightedSql = useMemo(() => {
    const formatted = formatSql(query)
    try {
      return hljs.highlight(formatted, { language: 'sql', ignoreIllegals: true }).value
    } catch {
      return formatted
    }
  }, [query])

  useEffect(() => {
    return () => {
      if (copyTimeoutRef.current) clearTimeout(copyTimeoutRef.current)
    }
  }, [])

  const handleCopySql = async (e) => {
    e.stopPropagation()
    if (!query) return
    try {
      await navigator.clipboard.writeText(query)
      setCopied(true)
      toast.success('SQL query copied to clipboard')
      if (copyTimeoutRef.current) clearTimeout(copyTimeoutRef.current)
      copyTimeoutRef.current = setTimeout(() => setCopied(false), 2000)
    } catch {
      toast.error('Failed to copy SQL query')
    }
  }

  const displayedRows = rows.slice(0, visibleRows)
  const hasMore = visibleRows < rows.length

  return (
    <div className="db-result-card" role="region" aria-label="Live Database Results">
      {/* Header Bar */}
      <div className="db-result-card__header">
        <div className="db-result-card__title">
          <Database size={15} className="db-result-card__icon" />
          <span>Live Database Results</span>
        </div>
        <div className="db-result-card__badge">
          {rows.length > 0 ? (
            <span>
              {totalRows} record{totalRows === 1 ? '' : 's'}
            </span>
          ) : (
            <span className="db-result-card__badge--empty">0 records</span>
          )}
        </div>
      </div>

      {/* Table Body or Empty State */}
      {rows.length === 0 ? (
        <div className="db-result-card__empty">
          <Table2 size={20} className="db-result-card__empty-icon" />
          <p className="db-result-card__empty-text">No matching records found in the database.</p>
        </div>
      ) : (
        <div className="db-result-card__table-wrapper">
          <table className="db-result-card__table">
            <thead>
              <tr>
                {columns.map((col) => (
                  <th
                    key={col}
                    className={clsx({ 'db-result-card__th--id': col.toLowerCase() === 'id' })}
                  >
                    {formatHeader(col)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {displayedRows.map((row, rIdx) => (
                <tr key={rIdx}>
                  {columns.map((col) => {
                    const val = row[col]
                    const isId = col.toLowerCase() === 'id'
                    const displayVal = val === null || val === undefined ? 'NULL' : String(val)

                    return (
                      <td
                        key={col}
                        className={clsx({
                          'db-result-card__td--null': val === null || val === undefined,
                          'db-result-card__td--id': isId,
                        })}
                      >
                        {isId && val !== null && val !== undefined ? (
                          <span className="db-result-card__id-tag">#{displayVal}</span>
                        ) : (
                          displayVal
                        )}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>

          {hasMore ? (
            <div className="db-result-card__pagination">
              <button
                type="button"
                className="db-result-card__more-btn"
                onClick={() => setVisibleRows((count) => Math.min(count + PAGE_SIZE, rows.length))}
              >
                Show more records ({rows.length - visibleRows} remaining)
              </button>
            </div>
          ) : null}
        </div>
      )}

      {/* Collapsible SQL Query Inspector */}
      {query ? (
        <div className="db-result-card__sql-accordion">
          <button
            type="button"
            className="db-result-card__sql-toggle"
            onClick={() => setSqlOpen((prev) => !prev)}
            aria-expanded={sqlOpen}
          >
            {sqlOpen ? (
              <ChevronDown size={14} className="db-result-card__chevron" />
            ) : (
              <ChevronRight size={14} className="db-result-card__chevron" />
            )}
            <span className="db-result-card__toggle-label">
              {sqlOpen ? 'Hide executed SQL query' : 'View executed SQL query'}
            </span>
          </button>

          {sqlOpen ? (
            <div className="db-result-card__sql-body">
              <div className="db-result-card__sql-actions">
                <span className="db-result-card__sql-lang">SQL</span>
                <button
                  type="button"
                  className={clsx('db-result-card__copy-btn', copied && 'db-result-card__copy-btn--copied')}
                  onClick={handleCopySql}
                  aria-label="Copy SQL Query"
                >
                  {copied ? <Check size={13} /> : <Copy size={13} />}
                  <span>{copied ? 'Copied' : 'Copy SQL'}</span>
                </button>
              </div>
              <pre className="db-result-card__code">
                <code
                  className="hljs language-sql"
                  dangerouslySetInnerHTML={{ __html: highlightedSql }}
                />
              </pre>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
