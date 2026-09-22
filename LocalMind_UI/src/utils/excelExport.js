import * as XLSX from 'xlsx'

function safeFilename(title) {
  const cleaned = (title || 'database_results')
    .trim()
    .split('')
    .filter((char) => char.charCodeAt(0) >= 32 && !'<>:"/\\|?*'.includes(char))
    .join('')
    .replace(/\s+/g, '_')
    .slice(0, 80)
  return cleaned || 'database_results'
}

/**
 * Export database query results as an Excel (.xlsx) file.
 * @param {Object} options
 * @param {string} options.title - Document title / query description used for sheet name and filename.
 * @param {Array<string>} options.columns - Ordered array of column names.
 * @param {Array<Object>} options.rows - Array of row objects.
 */
export function exportDatabaseExcel({ title = 'Database Results', columns = [], rows = [] }) {
  if (!rows || !rows.length) return

  const exportCols = columns && columns.length ? columns : Object.keys(rows[0] || {})

  // Map rows to match column order
  const data = rows.map((row) => {
    const item = {}
    for (const col of exportCols) {
      item[col] = row[col] ?? ''
    }
    return item
  })

  const worksheet = XLSX.utils.json_to_sheet(data, { header: exportCols })

  // Calculate suitable column widths
  const colWidths = exportCols.map((col) => {
    let maxLength = String(col).length
    for (const row of rows) {
      const val = row[col]
      if (val !== null && val !== undefined) {
        const len = String(val).length
        if (len > maxLength) maxLength = len
      }
    }
    return { wch: Math.min(Math.max(maxLength + 3, 10), 50) }
  })
  worksheet['!cols'] = colWidths

  const workbook = XLSX.utils.book_new()
  const sheetName = (title || 'Results')
    .replace(/[\\/?*[\]:]/g, '')
    .trim()
    .slice(0, 31) || 'Results'

  XLSX.utils.book_append_sheet(workbook, worksheet, sheetName)

  const filename = `${safeFilename(title)}.xlsx`
  XLSX.writeFile(workbook, filename)
}

