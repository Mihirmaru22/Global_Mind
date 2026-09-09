import { useEffect, useMemo, useRef, useState } from 'react'
import clsx from 'clsx'

const PAGE_SIZE = 5

function toArray(children) {
  return Array.isArray(children) ? children : [children]
}

export default function MarkdownTable(props) {
  const { children, className, ...rest } = props
  const [visibleRows, setVisibleRows] = useState(PAGE_SIZE)
  const sentinelRef = useRef(null)
  const wrapperRef = useRef(null)

  const { head, bodyRows, foot } = useMemo(() => {
    const rows = []
    let head = null
    let foot = null

    for (const child of toArray(children)) {
      if (!child) continue
      if (child.type === 'thead') {
        head = child
        continue
      }
      if (child.type === 'tfoot') {
        foot = child
        continue
      }
      if (child.type === 'tbody') {
        rows.push(...toArray(child.props?.children).filter(Boolean))
        continue
      }
      rows.push(child)
    }

    return { head, bodyRows: rows, foot }
  }, [children])

  useEffect(() => {
    setVisibleRows(PAGE_SIZE)
  }, [bodyRows.length])

  useEffect(() => {
    const root = wrapperRef.current
    const target = sentinelRef.current
    if (!root || !target || visibleRows >= bodyRows.length) return undefined

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setVisibleRows((count) => Math.min(count + PAGE_SIZE, bodyRows.length))
        }
      },
      { root, threshold: 1 },
    )

    observer.observe(target)
    return () => observer.disconnect()
  }, [bodyRows.length, visibleRows])

  const rowsToShow = bodyRows.slice(0, visibleRows)
  const hasMoreRows = visibleRows < bodyRows.length

  return (
    <div className="markdown-table-wrapper" ref={wrapperRef}>
      <table {...rest} className={clsx(className, 'markdown-table')}>
        {head}
        <tbody>
          {rowsToShow}
          {hasMoreRows ? (
            <tr aria-hidden="true" className="markdown-table__sentinel-row">
              <td colSpan={999}>
                <div ref={sentinelRef} className="markdown-table__sentinel" />
              </td>
            </tr>
          ) : null}
        </tbody>
        {foot}
      </table>
      {hasMoreRows ? (
        <button
          type="button"
          className="markdown-table__more"
          onClick={() => setVisibleRows((count) => Math.min(count + PAGE_SIZE, bodyRows.length))}
        >
          Show more rows
        </button>
      ) : null}
    </div>
  )
}
