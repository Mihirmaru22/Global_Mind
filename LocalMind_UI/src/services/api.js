import { http } from './http'

export async function getOverview() {
  const response = await http.get('/overview')
  return response.data
}

export async function getChats() {
  const response = await http.get('/chats')
  return response.data
}

export async function getMessages(chatId) {
  const response = await http.get(`/chats/${chatId}/messages`)
  return response.data
}

export async function sendMessage(chatId, message, provider) {
  const response = await http.post(`/chats/${chatId}/messages`, { message, provider })
  return response.data
}

export async function sendMessageStream(chatId, message, onChunk, signal, provider) {
  const response = await fetch(`${http.defaults.baseURL}/chats/${chatId}/messages/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ message, provider }),
    signal,
  })

  if (!response.ok) {
    throw new Error('Failed to start stream')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const dispatch = (line) => {
    if (!line.startsWith('data: ')) return
    try {
      onChunk(JSON.parse(line.slice(6)))
    } catch (e) {
      console.error('Failed to parse SSE JSON:', e, line)
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')

    // Keep the last incomplete line in the buffer
    buffer = lines.pop() || ''

    for (const line of lines) {
      dispatch(line)
    }
  }

  // Flush anything left in the buffer once the stream closes. The final SSE
  // event (the `done` frame that carries the complete answer and replaces the
  // streamed text) can arrive without a trailing newline; without this flush
  // it would be dropped and the UI would freeze on the last partial chunk.
  buffer += decoder.decode()
  for (const line of buffer.split('\n')) {
    dispatch(line)
  }
}

export async function createChat(title = 'New Chat') {
  const response = await http.post('/chats', { title })
  return response.data
}

export async function renameChat(chatId, title) {
  const response = await http.patch(`/chats/${chatId}`, { title })
  return response.data
}

export async function generateChatTitle(chatId) {
  const response = await http.post(`/chats/${chatId}/title`)
  return response.data
}

export async function generateChatDocument(chatId) {
  const response = await http.post(`/chats/${chatId}/document`)
  return response.data
}

export async function setMessageFeedbackApi(chatId, messageId, feedback) {
  const response = await http.post(
    `/chats/${chatId}/messages/${messageId}/feedback`,
    { feedback },
  )
  return response.data
}

export async function deleteChat(chatId) {
  const response = await http.delete(`/chats/${chatId}`)
  return response.data
}

export async function uploadDocument(file) {
  const formData = new FormData()
  formData.append('file', file)

  // Use the native fetch API or configure axios to send FormData
  // Since http.js handles standard JSON well, for FormData we must pass headers correctly
  const response = await http.post('/upload', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
  return response.data
}

export async function getDocuments() {
  const response = await http.get('/documents')
  return response.data
}

export async function uploadDocumentStream(file, onEvent, signal) {
  const formData = new FormData()
  formData.append('file', file)

  const response = await fetch(`${http.defaults.baseURL}/upload/stream`, {
    method: 'POST',
    body: formData,
    signal,
  })

  if (!response.ok || !response.body) {
    throw new Error('Failed to start ingestion stream')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const dispatch = (line) => {
    if (!line.startsWith('data: ')) return
    try {
      onEvent(JSON.parse(line.slice(6)))
    } catch (e) {
      console.error('Failed to parse ingestion SSE JSON:', e, line)
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    for (const line of lines) dispatch(line)
  }
  buffer += decoder.decode()
  for (const line of buffer.split('\n')) dispatch(line)
}

export async function persistIngestionCard(chatId, card) {
  const response = await http.post(`/chats/${chatId}/messages/ingestion`, card)
  return response.data
}

export async function saveSettings(payload) {
  const response = await http.post('/settings', payload)
  return response.data
}

export async function getSettings() {
  const response = await http.get('/settings')
  return response.data
}

export async function getProviders() {
  const response = await http.get('/providers')
  return response.data
}

// Scan the server's watched drop-folder (data/inbox) and ingest any new files.
// Idempotent — already-ingested files are reported as duplicates, not re-ingested.
// Returns { scanned, ingested, skipped, failed, message, ... }.
export async function scanIngestFolder() {
  const response = await http.post('/ingest/folder')
  return response.data
}
