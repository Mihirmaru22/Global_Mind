import dayjs from 'dayjs'
import { jsPDF } from 'jspdf'

function safeFilename(title) {
  const cleaned = (title || 'chat')
    .trim()
    .split('')
    .filter((char) => {
      const code = char.charCodeAt(0)
      return code >= 32 && !'<>:"/\\|?*'.includes(char)
    })
    .join('')
    .replace(/\s+/g, ' ')
    .slice(0, 80)

  return cleaned || 'chat'
}

function ensurePageSpace(pdf, y, minSpace, pageHeight, margin) {
  if (y + minSpace <= pageHeight - margin) return y
  pdf.addPage()
  return margin
}

export function exportChatPdf(chat, messages = []) {
  const pdf = new jsPDF({
    unit: 'pt',
    format: 'a4',
    compress: true,
  })

  const pageWidth = pdf.internal.pageSize.getWidth()
  const pageHeight = pdf.internal.pageSize.getHeight()
  const margin = 48
  const contentWidth = pageWidth - margin * 2
  const lineHeight = 14

  let y = margin

  pdf.setFont('helvetica', 'bold')
  pdf.setFontSize(18)
  pdf.text(chat?.title || 'Chat', margin, y)
  y += 24

  pdf.setFont('helvetica', 'normal')
  pdf.setFontSize(10)
  pdf.setTextColor(102)
  pdf.text(
    `Exported ${dayjs().format('MMM D, YYYY h:mm A')}`,
    margin,
    y,
  )
  y += 18

  pdf.setTextColor(25)

  const printableMessages = messages.filter((message) => message.status !== 'loading')

  if (!printableMessages.length) {
    pdf.setFontSize(11)
    pdf.text('No messages to export.', margin, y)
  }

  printableMessages.forEach((message) => {
    const label = message.role === 'user' ? 'You' : 'Assistant'
    const timestamp = message.createdAt
      ? dayjs(message.createdAt).format('MMM D, YYYY h:mm A')
      : ''

    const header = timestamp ? `${label} - ${timestamp}` : label
    const headerLines = pdf.splitTextToSize(header, contentWidth)
    const bodyLines = pdf.splitTextToSize(message.content || '', contentWidth)
    const headerHeight = headerLines.length * lineHeight + 8
    y = ensurePageSpace(pdf, y, headerHeight, pageHeight, margin)

    pdf.setFont('helvetica', 'bold')
    pdf.setFontSize(11)
    pdf.text(headerLines, margin, y)
    y += headerLines.length * lineHeight + 8

    pdf.setFont('helvetica', 'normal')
    pdf.setFontSize(10.5)
    if (!bodyLines.length) {
      y = ensurePageSpace(pdf, y, lineHeight + 18, pageHeight, margin)
      y += lineHeight + 18
      return
    }

    bodyLines.forEach((line) => {
      y = ensurePageSpace(pdf, y, lineHeight, pageHeight, margin)
      pdf.text(line, margin, y)
      y += lineHeight
    })

    y += 18
  })

  const filename = `${safeFilename(chat?.title)}.pdf`
  pdf.save(filename)
}
