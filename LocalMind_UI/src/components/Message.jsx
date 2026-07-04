import { useState, useEffect } from 'react'
import dayjs from 'dayjs'
import { motion, AnimatePresence } from 'framer-motion'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import clsx from 'clsx'

const THINKING_MESSAGES = [
  "Searching database...",
  "Retrieving context...",
  "Reranking documents...",
  "Applying reasoning...",
  "Generating answer..."
]

function DynamicThinkingLabel() {
  const [index, setIndex] = useState(0)

  useEffect(() => {
    const interval = setInterval(() => {
      setIndex((i) => Math.min(i + 1, THINKING_MESSAGES.length - 1))
    }, 2000)
    return () => clearInterval(interval)
  }, [])

  return (
    <span className="message__typing-label" style={{ position: 'relative', display: 'inline-flex' }}>
      <AnimatePresence mode="wait">
        <motion.span
          key={index}
          initial={{ opacity: 0, y: 5 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -5 }}
          transition={{ duration: 0.2 }}
        >
          {THINKING_MESSAGES[index]}
        </motion.span>
      </AnimatePresence>
    </span>
  )
}

export default function Message({ message, index = 0 }) {
  const isAssistant = message.role === 'assistant'
  const isLoading = message.status === 'loading'

  return (
    <motion.div
      className={clsx('message', `message--${message.role}`, {
        'message--loading': isLoading,
      })}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.24, delay: index * 0.03 }}
    >
      <div className="message__meta">
        <strong>{isAssistant ? 'Local Mind' : 'You'}</strong>
        <span>
          {isLoading ? 'Generating response' : dayjs(message.createdAt).format('MMM D, HH:mm')}
        </span>
      </div>
      {isLoading ? (
        <div className="message__assistant message__assistant--loading" aria-live="polite">
          <span className="message__typing">
            <span className="loader__dot" />
            <span className="loader__dot" />
            <span className="loader__dot" />
            <DynamicThinkingLabel />
          </span>
        </div>
      ) : isAssistant ? (
        <div className="message__assistant markdown">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeHighlight]}
          >
            {message.content}
          </ReactMarkdown>
        </div>
      ) : (
        <div className="message__bubble markdown">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeHighlight]}
          >
            {message.content}
          </ReactMarkdown>
        </div>
      )}
    </motion.div>
  )
}

