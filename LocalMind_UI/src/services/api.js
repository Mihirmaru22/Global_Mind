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

export async function sendMessage(chatId, message) {
  const response = await http.post(`/chats/${chatId}/messages`, { message })
  return response.data
}

export async function sendMessageStream(chatId, message, onChunk, signal) {
  const response = await fetch(`${http.defaults.baseURL}/chats/${chatId}/messages/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ message }),
    signal,
  })

  if (!response.ok) {
    throw new Error('Failed to start stream')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    
    // Keep the last incomplete line in the buffer
    buffer = lines.pop() || ''

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const data = JSON.parse(line.slice(6))
          onChunk(data)
        } catch (e) {
          console.error('Failed to parse SSE JSON:', e, line)
        }
      }
    }
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

export async function saveSettings(payload) {
  const response = await http.post('/settings', payload)
  return response.data
}

export async function getSettings() {
  const response = await http.get('/settings')
  return response.data
}
