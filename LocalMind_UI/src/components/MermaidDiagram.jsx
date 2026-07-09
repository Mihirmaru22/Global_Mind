import { useEffect, useId, useState } from 'react'
import mermaid from 'mermaid'

/**
 * Renders a Mermaid code block as an inline SVG diagram.
 *
 * Designed to survive streaming: while tokens are still arriving the fenced
 * block is incomplete and Mermaid.render throws, so we fall back to showing the
 * raw source until the syntax becomes valid. This keeps the chat from ever
 * crashing on a half-written diagram.
 *
 * Charts are sized and coloured from the app's own CSS theme variables so they
 * stay readable and follow light/dark theme switches, and xy-charts widen with
 * the number of categories (then scroll) so axis labels never collapse into an
 * unreadable blur.
 */
function cssVar(name, fallback) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

function isDarkTheme() {
  const attr = document.documentElement.getAttribute('data-theme')
  if (attr === 'light') return false
  if (attr === 'dark') return true
  return Boolean(window.matchMedia?.('(prefers-color-scheme: dark)')?.matches)
}

// Mid-luminance categorical palette that reads well on both light and dark
// backgrounds. The app accent leads so single-series charts match the brand.
const BASE_PALETTE = [
  '#4c78a8', '#59a14f', '#e1a54b', '#8a6bbf',
  '#d1495b', '#43938a', '#b07aa1', '#6b8e23',
]

// Count the x-axis categories in an xychart-beta block so we can give each one
// enough horizontal room. Matches:  x-axis [Jan, Feb, Mar]  or  x-axis "T" [..]
function xAxisCategoryCount(source) {
  const match = source.match(/x-axis[^\n[]*\[([^\]]*)\]/i)
  if (!match) return 0
  return match[1].split(',').filter((s) => s.trim().length > 0).length
}

function buildConfig(source) {
  const dark = isDarkTheme()
  const text = cssVar('--text-primary', dark ? '#ededed' : '#1a1a1a')
  const muted = cssVar('--text-muted', dark ? '#8e8e8e' : '#767676')
  const line = cssVar('--panel-border-strong', dark ? '#3a3a3a' : '#bdbdbd')
  const accent = cssVar('--accent-strong', '#d97757')
  const palette = [accent, ...BASE_PALETTE].join(', ')

  const isXY = /^xychart-beta/i.test(source.trimStart())
  const categories = isXY ? xAxisCategoryCount(source) : 0
  // Give every category ~72px so 13 GPU models don't overlap; the container
  // scrolls horizontally when the natural width exceeds the bubble.
  const width = isXY ? Math.max(720, categories * 72) : undefined

  return {
    isXY,
    config: {
      startOnLoad: false,
      securityLevel: 'strict',
      fontFamily: 'inherit',
      theme: 'base',
      themeVariables: {
        fontSize: '15px',
        xyChart: {
          backgroundColor: 'transparent',
          titleColor: text,
          xAxisLabelColor: muted,
          xAxisTitleColor: text,
          xAxisTickColor: line,
          xAxisLineColor: line,
          yAxisLabelColor: muted,
          yAxisTitleColor: text,
          yAxisTickColor: line,
          yAxisLineColor: line,
          plotColorPalette: palette,
        },
      },
      xyChart: {
        width,
        height: 460,
        titleFontSize: 18,
        xAxis: { labelFontSize: 14, titleFontSize: 14, labelPadding: 6 },
        yAxis: { labelFontSize: 13, titleFontSize: 14 },
        plotReservedSpacePercent: 55,
      },
    },
  }
}

export default function MermaidDiagram({ code }) {
  const [svg, setSvg] = useState('')
  const [failed, setFailed] = useState(false)
  const [wide, setWide] = useState(false)
  // A stable, render-pure id that is also a valid CSS identifier for Mermaid.
  const renderId = `mermaid-${useId().replace(/[^a-zA-Z0-9]/g, '')}`

  useEffect(() => {
    let cancelled = false
    const source = (code || '').trim()
    if (!source) return undefined

    const { isXY, config } = buildConfig(source)
    mermaid.initialize(config)

    mermaid
      .render(renderId, source)
      .then(({ svg: rendered }) => {
        if (cancelled) return
        setSvg(rendered)
        setWide(isXY)
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
        className={wide ? 'mermaid-diagram mermaid-diagram--wide' : 'mermaid-diagram'}
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
