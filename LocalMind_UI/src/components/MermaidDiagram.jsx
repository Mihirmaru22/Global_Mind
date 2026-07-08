import { useEffect, useId, useState } from 'react'
import mermaid from 'mermaid'

/**
 * Renders a Mermaid code block as an inline SVG diagram.
 *
 * Designed to survive streaming: while tokens are still arriving the fenced
 * block is incomplete and Mermaid.render throws, so we fall back to showing the
 * raw source until the syntax becomes valid. This keeps the chat from ever
 * crashing on a half-written diagram.
 */
function currentTheme() {
  const attr = document.documentElement.getAttribute('data-theme')
  if (attr === 'light') return 'default'
  if (attr === 'dark') return 'dark'
  // Fall back to the OS preference when the app hasn't stamped a theme yet.
  return window.matchMedia?.('(prefers-color-scheme: dark)')?.matches ? 'dark' : 'default'
}

export default function MermaidDiagram({ code }) {
  const [svg, setSvg] = useState('')
  const [failed, setFailed] = useState(false)
  // A stable, render-pure id that is also a valid CSS identifier for Mermaid.
  const renderId = `mermaid-${useId().replace(/[^a-zA-Z0-9]/g, '')}`

  useEffect(() => {
    let cancelled = false
    const source = (code || '').trim()
    if (!source) return undefined

    mermaid.initialize({
      startOnLoad: false,
      theme: currentTheme(),
      securityLevel: 'strict',
      fontFamily: 'inherit',
    })

    mermaid
      .render(renderId, source)
      .then(({ svg: rendered }) => {
        if (cancelled) return
        setSvg(rendered)
        setFailed(false)
      })
      .catch(() => {
        // Invalid or still-streaming syntax — fall back to the raw source.
        if (cancelled) return
        setFailed(true)
      })

    return () => {
      cancelled = true
    }
  }, [code, renderId])

  const hasSource = Boolean((code || '').trim())

  if (hasSource && svg && !failed) {
    return (
      <div
        className="mermaid-diagram"
        role="img"
        // Mermaid output is sanitized (securityLevel: 'strict').
        dangerouslySetInnerHTML={{ __html: svg }}
      />
    )
  }

  if (!hasSource) return null

  return (
    <pre className="mermaid-fallback">
      <code>{code}</code>
    </pre>
  )
}
