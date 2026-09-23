import { motion } from 'framer-motion'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import {
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Copy,
  Download,
  PencilLine,
  RefreshCw,
  ThumbsDown,
  ThumbsUp,
  X,
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import clsx from 'clsx'
import TextareaAutosize from 'react-textarea-autosize'
import { useAppStore, buildUntitledChatTitle } from '../store/store.js'
import { exportDatabasePdf } from '../utils/pdfExport.js'
import MarkdownTable from './MarkdownTable.jsx'
import MermaidDiagram from './MermaidDiagram.jsx'
import IngestionCard from './IngestionCard.jsx'
import ThinkingTrace from './ThinkingTrace.jsx'
import TokenUsage from './TokenUsage.jsx'
import rehypeCitations from './rehypeCitations.js'
import DatabaseResultCard from './DatabaseResultCard.jsx'
import CodeBlock from './CodeBlock.jsx'

/** Recursively flatten a react-markdown children tree back into plain text.
 * rehype-highlight can split code into nested <span> tokens, so a simple
 * String() is not enough — we walk the tree and concatenate the text. */
/** Recursively flatten a react-markdown children tree back into plain text. */
function nodeText(node) {
  if (node == null || node === false) return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(nodeText).join('')
  if (typeof node === 'object' && node.props) return nodeText(node.props.children)
  return ''
}

// First-line directives that unambiguously mark a Mermaid diagram, so we can
// still render when the model fences the block as ```xychart / plain ``` /
// anything other than ```mermaid.
const MERMAID_DIRECTIVE =
  /^(?:%%\{[^]*?\}%%\s*)?(?:xychart-beta|pie\b|flowchart\b|graph\b|sequenceDiagram\b|timeline\b|gantt\b|classDiagram\b|stateDiagram(?:-v2)?\b|erDiagram\b|journey\b|mindmap\b|quadrantChart\b)/

// When a model fences a block as ```xychart-beta (not ```mermaid), the language
// tag becomes the className — but the content body no longer has the directive on
// its first line, so MERMAID_DIRECTIVE can't catch it. This regex matches any
// mermaid chart-type language class so we can prepend the directive ourselves.
const MERMAID_LANG_RE =
  /^language-(xychart-beta|xychart|pie|flowchart|graph|sequenceDiagram|timeline|gantt|classDiagram|stateDiagram(?:-v2)?|erDiagram|journey|mindmap|quadrantChart)$/i

/**
 * Pull the source out of a fenced code block if it's a Mermaid diagram.
 * Handles three fence styles the model might produce:
 *   1. ```mermaid   — content already starts with the chart directive.
 *   2. ```xychart-beta (etc.) — directive is the language tag; we prepend it.
 *   3. ``` (unlabelled) — directive is the first line of content.
 */
function mermaidSource(children) {
  const child = Array.isArray(children) ? children[0] : children
  if (!child?.props) return null
  const className = child.props.className || ''
  const source = nodeText(child.props.children).replace(/\n$/, '')
  // Case 1: ```mermaid — content already contains the directive header.
  if (/\bmermaid\b/.test(className)) return source
  // Case 2: ```xychart-beta etc. — language tag IS the directive; prepend it.
  const lang = className.match(MERMAID_LANG_RE)?.[1]
  if (lang) return `${lang}\n${source}`
  // Case 3: unlabelled/mis-labelled fence whose content starts with a directive.
  if (MERMAID_DIRECTIVE.test(source.trimStart())) return source
  return null
}

// CommonMark requires closing code fences to have only spaces after the
// backticks. LLMs often append citation markers ([1]) directly after the
// closing backticks, which prevents the fence from closing the block and leaks
// the fence line into the code content. Move those citations to the next line
// so the parser sees a valid closing fence.
function normalizeClosingFences(text) {
  let normalized = text.replace(/^(`{3,}|~{3,})[ \t]*(\[\d+(?:[,\s]*\d+)*\])/gm, '$1\n$2')
  // Ensure multiline SQL Query Executed inline-backticks don't break CommonMark into accidental indented blocks
  normalized = normalized.replace(/SQL Query Executed:\s*`([\s\S]+?)`/g, (match, sql) => {
    const cleanSql = sql
      .split('\n')
      .map((l) => l.replace(/--.*$/, '').trim())
      .filter(Boolean)
      .join(' ')
    return `SQL Query Executed: \`${cleanSql}\``
  })
  return normalized
}

function splitMessageContent(rawText, sqlPayload) {
  if (!rawText) {
    return { mainText: '', dbPayload: sqlPayload || null, referencesText: '' }
  }

  let text = rawText
  let dbPayload = sqlPayload || null
  let referencesText = ''

  // 1. Separate **References** if present
  const refMatch = text.match(/\n\n(?:\*{2}|#{1,4}\s*)References(?:\*{2})?[\s\S]*$/i)
  if (refMatch) {
    referencesText = refMatch[0].trim()
    text = text.slice(0, refMatch.index).trim()
  }

  // 2. Extract SQL Block if present: SQL Query Executed: `...`
  const sqlMatch = text.match(/SQL Query Executed:\s*`([\s\S]+?)`([\s\S]*)$/)
  if (sqlMatch) {
    const rawSql = sqlMatch[1].trim()
    const tableSection = sqlMatch[2].trim()

    if (!dbPayload) {
      // Parse markdown table rows into structured data as fallback
      const lines = tableSection
        .split('\n')
        .map((l) => l.trim())
        .filter((l) => l.startsWith('|'))

      let columns = []
      let rows = []
      if (lines.length >= 2) {
        columns = lines[0]
          .slice(1, -1)
          .split('|')
          .map((c) => c.trim())
        for (let i = 2; i < lines.length; i++) {
          const vals = lines[i]
            .slice(1, -1)
            .split('|')
            .map((v) => v.trim())
          if (vals.length === columns.length) {
            const row = {}
            columns.forEach((col, idx) => {
              row[col] = vals[idx] === 'NULL' ? null : vals[idx]
            })
            rows.push(row)
          }
        }
      }

      dbPayload = {
        query: rawSql,
        columns,
        rows,
        row_count: rows.length,
      }
    }

    // Strip the raw SQL block from the main text so it doesn't render twice!
    text = text.slice(0, sqlMatch.index).trim()
  } else if (dbPayload) {
    // If structured payload was attached, remove any trailing markdown table or SQL text from mainText
    text = text.replace(/SQL Query Executed:\s*`[\s\S]+?`[\s\S]*$/, '').trim()
  }

  return { mainText: text, dbPayload, referencesText }
}

// Custom renderers for assistant markdown: mermaid code blocks become diagrams,
// code blocks become styled CodeBlock with tabs and Copy button,
// tables become MarkdownTable.
const markdownComponents = {
  pre(props) {
    const { children, ...rest } = props
    const source = mermaidSource(children)
    if (source !== null) return <MermaidDiagram code={source} />
    return <CodeBlock {...rest}>{children}</CodeBlock>
  },
  table(props) {
    return <MarkdownTable {...props} />
  },
}

function useTypewriterText(text, enabled) {
  const [displayedText, setDisplayedText] = useState(enabled ? '' : text)

  useEffect(() => {
    if (!enabled) {
      // This hook intentionally syncs local animation state with incoming props.
      setDisplayedText(text)
      return undefined
    }

    const reducedMotion =
      typeof window !== 'undefined' &&
      window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches

    if (reducedMotion) {
      // This hook intentionally syncs local animation state with incoming props.
      setDisplayedText(text)
      return undefined
    }

    setDisplayedText('')

    let index = 0
    const interval = window.setInterval(() => {
      index += 1
      setDisplayedText(text.slice(0, index))

      if (index >= text.length) {
        window.clearInterval(interval)
      }
    }, 18)

    return () => window.clearInterval(interval)
  }, [enabled, text])

  return displayedText
}

export default function Message({
  message,
  index = 0,
  chatId,
  isLast = false,
  hasLaterUserMessage = false,
  sourceQuery = '',
}) {
  const markMessageAsSeen = useAppStore((state) => state.markMessageAsSeen)
  const setMessageFeedback = useAppStore((state) => state.setMessageFeedback)
  const regenerateMessage = useAppStore((state) => state.regenerateMessage)
  const setMessageVersion = useAppStore((state) => state.setMessageVersion)
  const editMessage = useAppStore((state) => state.editMessage)
  const loading = useAppStore((state) => state.loading)
  const isAssistant = message.role === 'assistant'
  const isLoading = message.status === 'loading'
  const isStreaming = message.status === 'streaming'
  const [copied, setCopied] = useState(false)
  const [isEditing, setIsEditing] = useState(false)
  const [draft, setDraft] = useState(message.content || '')
  const [expanded, setExpanded] = useState(false)
  const [canExpand, setCanExpand] = useState(false)
  const bubbleRef = useRef(null)
  

  const submitFeedbackComment = useAppStore((state) => state.submitFeedbackComment)
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  const [feedbackText, setFeedbackText] = useState('')
  const [feedbackOtherOpen, setFeedbackOtherOpen] = useState(false)
  const [feedbackKind, setFeedbackKind] = useState(null)
  const [pdfDialogOpen, setPdfDialogOpen] = useState(false)
  const [recordCountInput, setRecordCountInput] = useState('')

  const editRef = useRef(null)
  const copyTimerRef = useRef(null)
  const typedContent = useTypewriterText(
    message.content || '',
    isAssistant && !isLoading && !!message.isNew,
  )
  const { mainText, dbPayload, referencesText } = useMemo(() => {
    return splitMessageContent(typedContent, message.sqlPayload)
  }, [typedContent, message.sqlPayload])

  const dbRows = dbPayload?.rows || []
  const canDownloadPdf = dbRows.length > 0
  const totalRecords = dbPayload?.row_count ?? dbRows.length
  const parsedRecordCount = Number(recordCountInput)
  const isRecordCountValid =
    recordCountInput.trim() !== '' &&
    Number.isInteger(parsedRecordCount) &&
    parsedRecordCount >= 1 &&
    parsedRecordCount <= totalRecords

  // Show the blinking cursor both while the typewriter fallback is actively
  // typing AND while real tokens are streaming in live from the backend —
  // the latter never touches useTypewriterText's animation path (isNew is
  // never set for streamed completions), so it needs its own indicator.

  const isTyping =
    (isAssistant && !isLoading && typedContent.length < (message.content || '').length) || isStreaming
  const feedback = message.feedback || null
  const canRegenerate = isAssistant && !isLoading && !isStreaming && isLast
  const canEdit = !isAssistant && !loading && !hasLaterUserMessage
  const versions = message.versions || []
  const activeVersion = message.activeVersion ?? Math.max(0, versions.length - 1)
  const hasVersions = versions.length > 1 && !isLoading && !isStreaming

  useEffect(() => {
    if (!isEditing) {
      setDraft(message.content || '')
    }
  }, [isEditing, message.content])

  useEffect(() => {
    if (!isEditing) return undefined
    const frame = window.requestAnimationFrame(() => {
      editRef.current?.focus()
      editRef.current?.setSelectionRange?.(draft.length, draft.length)
    })

    return () => window.cancelAnimationFrame(frame)
  }, [draft.length, isEditing])

  useEffect(
    () => () => {
      if (copyTimerRef.current) window.clearTimeout(copyTimerRef.current)
    },
    [],
  )

  useLayoutEffect(() => {
    if (isAssistant || isEditing) return
    const node = bubbleRef.current
    if (!node) return
    setExpanded(false)
    const frame = window.requestAnimationFrame(() => {
      setCanExpand(node.scrollHeight - node.clientHeight > 4)
    })
    return () => window.cancelAnimationFrame(frame)
  }, [isAssistant, isEditing, message.content])

  useEffect(() => {
    if (!chatId || !message.isNew || isTyping) return
    markMessageAsSeen(chatId, message.id)
  }, [chatId, isTyping, markMessageAsSeen, message.id, message.isNew])

  const handleCopy = async () => {
    if (!message.content) return

    try {
      await navigator.clipboard.writeText(message.content)
      setCopied(true)
      if (copyTimerRef.current) window.clearTimeout(copyTimerRef.current)
      copyTimerRef.current = window.setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard access can fail outside a secure context.
    }
  }

  const handleFeedback = (value) => {
    setMessageFeedback(chatId, message.id, value)
    setFeedbackOpen(true)
    setFeedbackText('')
    setFeedbackOtherOpen(false)
    setFeedbackKind(value)
  }

  const handleFeedbackSubmit = () => {
    if (feedbackText.trim()) {
      submitFeedbackComment(chatId, message.id, feedbackText.trim())
    }
    setFeedbackOpen(false)
    setFeedbackText('')
    setFeedbackOtherOpen(false)
    setFeedbackKind(null)
  }

  const handleOpenPdfDialog = () => {
    setRecordCountInput(String(totalRecords))
    setPdfDialogOpen(true)
  }

  const handleConfirmDownloadPdf = async () => {
    if (!isRecordCountValid) return

    const exportColumns = dbPayload.columns?.length ? dbPayload.columns : Object.keys(dbRows[0] || {})
    const reportTitle = buildUntitledChatTitle(sourceQuery) || 'Database Results'

    setPdfDialogOpen(false)
    await exportDatabasePdf({
      title: reportTitle,
      columns: exportColumns,
      rows: dbRows.slice(0, parsedRecordCount),
      recordCount: parsedRecordCount,
    })
  }

  const handleSaveEdit = async () => {
    if (!canEdit || !chatId) return

    const nextContent = draft.trim()
    if (!nextContent || nextContent === (message.content || '').trim()) {
      setIsEditing(false)
      setDraft(message.content || '')
      return
    }

    setIsEditing(false)
    await editMessage(chatId, message.id, nextContent)
  }

  const handleCancelEdit = () => {
    setDraft(message.content || '')
    setIsEditing(false)
  }

  if (message.kind === 'ingestion') {
    return (
      <motion.div
        className="message message--assistant message--ingestion"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.2, delay: index * 0.03 }}
      >
        <IngestionCard message={message} />
      </motion.div>
    )
  }

  return (
    <motion.div
      className={clsx('message', `message--${message.role}`, {
        'message--loading': isLoading,
      })}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, delay: index * 0.03 }}
    >
      {isLoading ? (
        <div className="message__assistant-body message__assistant-body--loading" aria-live="polite">
          {message.thinking?.length ? (
            <ThinkingTrace steps={message.thinking} streaming />
          ) : (
            <span className="message__typing">
              <span className="loader__dot" />
              <span className="loader__dot" />
              <span className="loader__dot" />
            </span>
          )}
        </div>
      ) : isAssistant ? (
        <div className="message__content">
          {/* Source evidence badge for hybrid answers */}
          {(dbPayload && referencesText) ? (
            <div className="message__source-badge">
              <span className="message__source-tag message__source-tag--sql">Database</span>
              <span className="message__source-divider">·</span>
              <span className="message__source-tag message__source-tag--doc">Document</span>
            </div>
          ) : null}

          {message.thinking?.length ? (
            <ThinkingTrace steps={message.thinking} streaming={isStreaming} />
          ) : null}

          {/* Open content — no card border */}
          <div className="message__assistant-body markdown">
            {dbPayload || referencesText ? (
              <>
                {mainText ? (
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    rehypePlugins={[[rehypeHighlight, { ignoreMissing: true }], rehypeCitations]}
                    components={markdownComponents}
                  >
                    {normalizeClosingFences(mainText)}
                  </ReactMarkdown>
                ) : null}

                {dbPayload ? (
                  <DatabaseResultCard
                    payload={dbPayload}
                    reportTitle={sourceQuery ? buildUntitledChatTitle(sourceQuery) : 'Database Results'}
                  />
                ) : null}

                {referencesText ? (
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    rehypePlugins={[[rehypeHighlight, { ignoreMissing: true }], rehypeCitations]}
                    components={markdownComponents}
                  >
                    {normalizeClosingFences(referencesText)}
                  </ReactMarkdown>
                ) : null}
              </>
            ) : (
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[[rehypeHighlight, { ignoreMissing: true }], rehypeCitations]}
                components={markdownComponents}
              >
                {normalizeClosingFences(typedContent)}
              </ReactMarkdown>
            )}
            {isTyping ? <span className="typing-cursor" aria-hidden="true" /> : null}
          </div>

          {hasVersions ? (
            <div className="message__versions" role="group" aria-label="Answer versions">
              <button
                type="button"
                className="message__version-nav"
                onClick={() => setMessageVersion(chatId, message.id, activeVersion - 1)}
                disabled={activeVersion <= 0}
                aria-label="Previous version"
              >
                <ChevronLeft size={14} />
              </button>
              <span className="message__version-count" aria-live="polite">
                {activeVersion + 1}/{versions.length}
              </span>
              <button
                type="button"
                className="message__version-nav"
                onClick={() => setMessageVersion(chatId, message.id, activeVersion + 1)}
                disabled={activeVersion >= versions.length - 1}
                aria-label="Next version"
              >
                <ChevronRight size={14} />
              </button>
            </div>
          ) : null}

          {/* Token usage — part of the same response card, below the answer */}
          {!isStreaming ? <TokenUsage usage={message.usage} /> : null}

          {/* Answer actions — four icon-only actions, left side, shown on hover */}
          <div className="message__bottom-bar">
            <div className="message__actions" aria-label="Answer actions">
              <button
                type="button"
                className={clsx('message__action', copied && 'message__action--active')}
                onClick={handleCopy}
                aria-label="Copy message"
                title="Copy"
              >
                {copied ? <Check size={15} /> : <Copy size={15} />}
              </button>
              <button
                type="button"
                className={clsx('message__action', feedback === 'up' && 'message__action--active')}
                onClick={() => handleFeedback('up')}
                aria-label="Good response"
                title="Good response"
              >
                <ThumbsUp size={15} />
              </button>
              <button
                type="button"
                className={clsx('message__action', feedback === 'down' && 'message__action--active')}
                onClick={() => handleFeedback('down')}
                aria-label="Bad response"
                title="Bad response"
              >
                <ThumbsDown size={15} />
              </button>
              {canRegenerate ? (
                <button
                  type="button"
                  className="message__action"
                  onClick={() => regenerateMessage(chatId, message.id)}
                  aria-label="Regenerate response"
                  title="Regenerate"
                  disabled={loading}
                >
                  <RefreshCw size={15} className={loading ? 'spin' : ''} />
                </button>
              ) : null}
              {canDownloadPdf ? (
                <button
                  type="button"
                  className="message__action"
                  onClick={handleOpenPdfDialog}
                  aria-label="Download PDF"
                  title="Download PDF"
                >
                  <Download size={15} />
                </button>
              ) : null}
            </div>
          </div>

          {pdfDialogOpen ? (
            <div
              className="pdf-export-dialog-backdrop"
              role="presentation"
              onClick={() => setPdfDialogOpen(false)}
            >
              <div
                className="pdf-export-dialog"
                role="dialog"
                aria-modal="true"
                aria-labelledby="pdf-export-dialog-title"
                onClick={(event) => event.stopPropagation()}
              >
                <h3 id="pdf-export-dialog-title" className="pdf-export-dialog__title">
                  Download data as PDF
                </h3>
                <p className="pdf-export-dialog__label">How many records do you want to export?</p>
                <input
                  type="number"
                  className="pdf-export-dialog__input"
                  min={1}
                  max={totalRecords}
                  value={recordCountInput}
                  onChange={(event) => setRecordCountInput(event.target.value)}
                  autoFocus
                />
                <p className="pdf-export-dialog__meta">Available records: {totalRecords}</p>
                <div className="pdf-export-dialog__actions">
                  <button type="button" className="secondary-button" onClick={() => setPdfDialogOpen(false)}>
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="primary-button"
                    onClick={handleConfirmDownloadPdf}
                    disabled={!isRecordCountValid}
                  >
                    Download PDF
                  </button>
                </div>
              </div>
            </div>
          ) : null}
          

          {feedbackOpen && (
            <motion.div
              className="message__feedback-popover"
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.12 }}
            >
              {feedbackKind === 'down' ? (
                <>
                  <div className="message__feedback-popover-title">What wasn't helpful?</div>

                  <div className="message__feedback-options">
                    {['Incorrect information', 'Not relevant', 'Incomplete answer', 'Poor formatting'].map(
                      (reason) => (
                        <button
                          key={reason}
                          type="button"
                          className={clsx(
                            'message__feedback-option',
                            feedbackText === reason && 'message__feedback-option--active',
                          )}
                          onClick={() => {
                            setFeedbackText(reason)
                            setFeedbackOtherOpen(false)
                          }}
                        >
                          {reason}
                        </button>
                      ),
                    )}

                    <button
                      type="button"
                      className={clsx('message__feedback-option', feedbackOtherOpen && 'message__feedback-option--active')}
                      onClick={() => {
                        setFeedbackOtherOpen(true)
                        setFeedbackText('')
                      }}
                    >
                      Other
                    </button>
                  </div>

                  {feedbackOtherOpen ? (
                    <input
                      className="message__feedback-other"
                      placeholder="Tell us what went wrong..."
                      value={feedbackText}
                      onChange={(event) => setFeedbackText(event.target.value)}
                      autoFocus
                    />
                  ) : null}
                </>
              ) : (
                <>
                  <div className="message__feedback-popover-title">Anything you'd like to add? (optional)</div>
                  <input
                    className="message__feedback-other"
                    placeholder="Tell us what you liked..."
                    value={feedbackText}
                    onChange={(event) => setFeedbackText(event.target.value)}
                    onKeyDown={(event) => event.key === 'Enter' && handleFeedbackSubmit()}
                    autoFocus
                  />
                </>
              )}

              <div className="message__feedback-popover-actions">
                <button
                  type="button"
                  className="message__feedback-cancel"
                  onClick={() => {
                    setFeedbackOpen(false)
                    setFeedbackText('')
                    setFeedbackOtherOpen(false)
                    setFeedbackKind(null)
                  }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="message__feedback-submit"
                  onClick={handleFeedbackSubmit}
                  disabled={feedbackKind === 'down' && !feedbackText.trim()}
                >
                  Submit
                </button>
              </div>
            </motion.div>
          )}
        </div>
      ) : (
        /* User message */
        <div className="message__content">
          {isEditing ? (
            <div className="message__edit-shell">
              <TextareaAutosize
                ref={editRef}
                className="message__edit"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Escape') {
                    event.preventDefault()
                    handleCancelEdit()
                    return
                  }

                  if (event.key !== 'Enter' || event.shiftKey) return
                  event.preventDefault()
                  handleSaveEdit()
                }}
                minRows={3}
                maxRows={10}
              />
              <div className="message__edit-actions">
                <button type="button" className="secondary-button" onClick={handleCancelEdit}>
                  <X size={14} />
                  <span>Cancel</span>
                </button>
                <button
                  type="button"
                  className="primary-button"
                  onClick={handleSaveEdit}
                  disabled={!draft.trim() || draft.trim() === (message.content || '').trim()}
                >
                  <PencilLine size={14} />
                  <span>Save</span>
                </button>
              </div>
            </div>
          ) : (
            <>
              <div
                ref={bubbleRef}
                className={clsx('message__bubble', 'markdown', !expanded && canExpand && 'message__bubble--clamped')}
              >
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  rehypePlugins={[[rehypeHighlight, { ignoreMissing: true }], rehypeCitations]}
                >
                  {message.content}
                </ReactMarkdown>
              </div>
              {canExpand ? (
                <button
                  type="button"
                  className="message__show-more"
                  onClick={() => setExpanded((value) => !value)}
                >
                  <span>{expanded ? 'Show less' : 'Show more'}</span>
                  {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                </button>
              ) : null}
              <div className="message__actions message__actions--user">
                <button
                  type="button"
                  className={clsx('message__action', copied && 'message__action--active')}
                  onClick={handleCopy}
                  aria-label="Copy message"
                  title="Copy"
                >
                  {copied ? <Check size={14} /> : <Copy size={14} />}
                </button>
                {canEdit ? (
                  <button
                    type="button"
                    className="message__action"
                    onClick={() => setIsEditing(true)}
                    aria-label="Edit message"
                    title="Edit"
                  >
                    <PencilLine size={14} />
                  </button>
                ) : null}
              </div>
            </>
          )}
        </div>
      )}
    </motion.div>
  )
}
