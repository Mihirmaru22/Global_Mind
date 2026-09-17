import { useState, useRef } from 'react'
import { Check, Copy } from 'lucide-react'

function flattenNodeText(node) {
  if (node == null || node === false) return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(flattenNodeText).join('')
  if (typeof node === 'object' && node.props) return flattenNodeText(node.props.children)
  return ''
}

export default function CodeBlock({ children, ...props }) {
  const [copied, setCopied] = useState(false)
  const timerRef = useRef(null)

  // Extract language from code element className (e.g. "hljs language-javascript")
  const child = Array.isArray(children) ? children[0] : children
  const className = child?.props?.className || ''
  const langMatch = className.match(/language-([a-zA-Z0-9_-]+)/)
  const rawLang = langMatch ? langMatch[1].toLowerCase() : ''

  const displayLang = {
    js: 'JS',
    javascript: 'JS',
    ts: 'TS',
    typescript: 'TS',
    py: 'PYTHON',
    python: 'PYTHON',
    sql: 'SQL',
    html: 'HTML',
    css: 'CSS',
    json: 'JSON',
    bash: 'BASH',
    sh: 'SHELL',
    md: 'MARKDOWN',
  }[rawLang] || (rawLang ? rawLang.toUpperCase() : 'CODE')

  const handleCopy = async () => {
    const rawCode = flattenNodeText(child?.props?.children ?? children).replace(/\n$/, '')
    if (!rawCode) return

    try {
      await navigator.clipboard.writeText(rawCode)
      setCopied(true)
      if (timerRef.current) clearTimeout(timerRef.current)
      timerRef.current = setTimeout(() => setCopied(false), 2000)
    } catch {
      // Fallback or ignore
    }
  }

  return (
    <div className="code-card">
      <div className="code-card__header">
        <div className="code-card__tabs">
          <span className="code-card__tab code-card__tab--active">{displayLang}</span>
        </div>
        <button
          type="button"
          className="code-card__copy-btn"
          onClick={handleCopy}
          aria-label="Copy code to clipboard"
        >
          {copied ? <Check size={14} /> : <Copy size={14} />}
          <span>{copied ? 'Copied' : 'Copy code'}</span>
        </button>
      </div>
      <pre className="code-card__body" {...props}>
        {children}
      </pre>
    </div>
  )
}

