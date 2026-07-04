import { create } from 'zustand'
import {
  createChat,
  getChats,
  getDocuments,
  getMessages,
  getOverview,
  getSettings,
  saveSettings,
  sendMessage,
  sendMessageStream,
} from '../services/api.js'

function normalizeList(value, fallback = []) {
  if (Array.isArray(value)) return value
  if (Array.isArray(value?.data)) return value.data
  if (Array.isArray(value?.items)) return value.items
  if (Array.isArray(value?.chats)) return value.chats
  if (Array.isArray(value?.documents)) return value.documents
  return fallback
}

const demoChats = [
  { id: 'chat-1', title: 'Project summary', updatedAt: new Date().toISOString() },
  { id: 'chat-2', title: 'Document Q&A', updatedAt: new Date().toISOString() },
]

export const useAppStore = create((set, get) => ({
  chats: demoChats,
  activeChatId: demoChats[0].id,
  messagesByChatId: {},
  documents: [],
  overview: null,
  settings: null,
  loading: false,
  sidebarOpen: false,
  selectedDocId: null,

  initApp: async () => {
    set({ loading: true })
    try {
      const [overview, chats, settings, documents] = await Promise.all([
        getOverview(),
        getChats(),
        getSettings(),
        getDocuments(),
      ])

      const mergedSettings = {
        endpoint: '/api',
        model: 'Mistral 7B Instruct',
        temperature: 0.4,
        topP: '0.9',
        contextLength: '4096',
        streamResponses: true,
        autoSync: true,
        theme: 'dark',
        ...settings,
      }

      try {
        const savedSettings = localStorage.getItem('localmind-settings')
        if (savedSettings) {
          Object.assign(mergedSettings, JSON.parse(savedSettings))
        }
      } catch {
        // Ignore storage issues and fall back to demo defaults.
      }

      const normalizedChats = normalizeList(chats, demoChats)
      const normalizedDocuments = normalizeList(documents, [])
      const activeChatId = normalizedChats?.[0]?.id || get().activeChatId
      const messages = activeChatId ? await getMessages(activeChatId) : []

      set({
        overview,
        chats: normalizedChats.length ? normalizedChats : demoChats,
        activeChatId,
        messagesByChatId: { [activeChatId]: messages || [] },
        settings: mergedSettings,
        documents: normalizedDocuments,
      })
    } finally {
      set({ loading: false })
    }
  },

  selectChat: async (chatId) => {
    set({ activeChatId: chatId, sidebarOpen: false })
    const { messagesByChatId } = get()
    if (messagesByChatId[chatId]) return
    const messages = await getMessages(chatId)
    set((state) => ({
      messagesByChatId: { ...state.messagesByChatId, [chatId]: messages || [] },
    }))
  },

  toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
  closeSidebar: () => set({ sidebarOpen: false }),

  newChat: async () => {
    const chat = await createChat(`New Chat ${get().chats.length + 1}`)
    set((state) => ({
      chats: [chat, ...normalizeList(state.chats, demoChats)],
      activeChatId: chat.id,
      sidebarOpen: false,
      messagesByChatId: { ...state.messagesByChatId, [chat.id]: [] },
    }))
  },

  renameChat: async (chatId, title) => {
    const nextTitle = title.trim()
    if (!chatId || !nextTitle) return

    set((state) => ({
      chats: state.chats.map((chat) =>
        chat.id === chatId
          ? { ...chat, title: nextTitle, updatedAt: new Date().toISOString() }
          : chat,
      ),
    }))
  },

  deleteChat: async (chatId) => {
    if (!chatId) return

    const state = get()
    const remainingChats = state.chats.filter((chat) => chat.id !== chatId)
    const restMessages = { ...state.messagesByChatId }
    delete restMessages[chatId]

    if (!remainingChats.length) {
      const chat = await createChat('New Chat 1')
      set({
        chats: [chat],
        activeChatId: chat.id,
        messagesByChatId: { [chat.id]: [] },
        sidebarOpen: false,
      })
      return
    }

    set({
      chats: remainingChats,
      activeChatId:
        state.activeChatId === chatId ? remainingChats[0].id : state.activeChatId,
      messagesByChatId: restMessages,
      sidebarOpen: false,
    })
  },

  sendPrompt: async (content) => {
    const { activeChatId } = get()
    if (!activeChatId || !content.trim()) return

    const placeholderId = `assistant-pending-${Date.now()}`

    const userMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: content.trim(),
      createdAt: new Date().toISOString(),
    }

    set((state) => ({
      messagesByChatId: {
        ...state.messagesByChatId,
        [activeChatId]: [...(state.messagesByChatId[activeChatId] || []), userMessage],
      },
    }))

    set((state) => ({
      messagesByChatId: {
        ...state.messagesByChatId,
        [activeChatId]: [
          ...(state.messagesByChatId[activeChatId] || []),
          {
            id: placeholderId,
            role: 'assistant',
            content: '',
            createdAt: new Date().toISOString(),
            status: 'loading',
          },
        ],
      },
    }))

    try {
      await sendMessageStream(activeChatId, content, (chunkData) => {
        set((state) => {
          const chatMessages = state.messagesByChatId[activeChatId] || []
          return {
            messagesByChatId: {
              ...state.messagesByChatId,
              [activeChatId]: chatMessages.map((message) => {
                if (message.id === placeholderId) {
                  if (chunkData.type === 'chunk') {
                    // Turn off loading once we get the first chunk
                    return { ...message, content: message.content + chunkData.text, status: 'streaming' }
                  } else if (chunkData.type === 'done') {
                    // Replace with the final formatted message
                    return { ...chunkData.message, status: 'done' }
                  } else if (chunkData.type === 'error') {
                    return { ...chunkData.message, status: 'error' }
                  }
                }
                return message
              }),
            },
          }
        })
      })
    } catch (e) {
      console.error('Stream failed:', e)
      // On failure, remove placeholder or mark error (simple fallback)
      set((state) => ({
        messagesByChatId: {
          ...state.messagesByChatId,
          [activeChatId]: (state.messagesByChatId[activeChatId] || []).map((message) =>
            message.id === placeholderId 
              ? { ...message, content: 'Error connecting to the stream.', status: 'error' } 
              : message
          ),
        },
      }))
    }
  },

  refreshDocuments: async () => {
    const documents = await getDocuments()
    set({ documents: normalizeList(documents, []) })
  },

  updateSettings: async (patch) => {
    const settings = { ...(get().settings || {}), ...patch }
    set({ settings })
    try {
      localStorage.setItem('localmind-settings', JSON.stringify(settings))
    } catch {
      // Ignore storage write errors; the local demo state still updates.
    }
    await saveSettings(settings)
  },

  selectDocument: (docId) => set({ selectedDocId: docId }),
}))
