import { create } from 'zustand'
import {
  createChat,
  deleteChat as deleteChatApi,
  generateChatTitle,
  setMessageFeedbackApi,
  getChats,
  getDocuments,
  getMessages,
  getOverview,
  getProviders,
  getSettings,
  renameChat as renameChatApi,
  saveSettings,
  sendMessage,
  sendMessageStream,
  uploadDocument,
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

let requestSequence = 0

function readStoredBoolean(key, fallback = false) {
  try {
    const raw = localStorage.getItem(key)
    if (raw === null) return fallback
    return JSON.parse(raw)
  } catch {
    return fallback
  }
}

function writeStoredBoolean(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(Boolean(value)))
  } catch {
    // Ignore storage issues and keep the in-memory state working.
  }
}

function buildUntitledChatTitle(prompt) {
  const trimmed = prompt.trim()
  if (trimmed.length <= 48) return trimmed
  return `${trimmed.slice(0, 45).trimEnd()}...`
}

function touchChat(chats, chatId) {
  const updatedAt = new Date().toISOString()
  return chats.map((chat) => (chat.id === chatId ? { ...chat, updatedAt } : chat))
}

function createLoadingAssistantMessage(requestId) {
  return {
    id: `assistant-pending-${requestId}-${Date.now()}`,
    role: 'assistant',
    content: '',
    createdAt: new Date().toISOString(),
    status: 'loading',
  }
}

/**
 * Drives one assistant response via the real SSE stream, updating the
 * placeholder message in place as chunks arrive. This is what gives the
 * "live streamed tokens" experience — content grows incrementally as
 * `status: 'streaming'`, and the typewriter effect in Message.jsx is never
 * enabled for these messages (no `isNew` flag is set on the streamed
 * completion), since the text was already shown live, token by token.
 *
 * If the stream transport itself fails (not aborted by the user, a genuine
 * connection error), falls back to one plain non-streaming request. That
 * fallback response *does* get `isNew: true`, since it arrives as a single
 * complete blob — this is the one path where the typewriter effect actually
 * fires, exactly as intended: a fallback for non-streaming responses, never
 * a replacement for real streaming.
 */
async function streamAssistantResponse(set, get, chatId, requestId, prompt) {
  const controller = new AbortController()
  set((state) => ({
    activeRequest: state.activeRequest && { ...state.activeRequest, abortController: controller },
  }))

  const isStale = () => {
    const request = get().activeRequest
    return !request || request.id !== requestId
  }

  // Soft-pin provider for this request — the backend falls back to the rest of
  // each task's chain when the pinned provider is exhausted or down.
  const provider = get().settings?.provider

  try {
    await sendMessageStream(
      chatId,
      prompt,
      (chunkData) => {
        if (isStale()) return
        const request = get().activeRequest

        set((state) => {
          const chatMessages = state.messagesByChatId[chatId] || []
          return {
            messagesByChatId: {
              ...state.messagesByChatId,
              [chatId]: chatMessages.map((message) => {
                if (message.id !== request.placeholderId) return message
                if (chunkData.type === 'chunk') {
                  return { ...message, content: message.content + chunkData.text, status: 'streaming' }
                }
                if (chunkData.type === 'done') {
                  return { ...chunkData.message, status: 'done' }
                }
                if (chunkData.type === 'error') {
                  return { ...chunkData.message, status: 'error' }
                }
                return message
              }),
            },
          }
        })
      },
      controller.signal,
      provider,
    )

    if (isStale()) return
    set((state) => ({
      chats: touchChat(state.chats, chatId),
      activeRequest: null,
      loading: false,
    }))
  } catch (error) {
    if (error?.name === 'AbortError') {
      // User pressed stop. Leave whatever content already streamed in place
      // rather than discarding it — it's a real, if incomplete, answer.
      set((state) => {
        const request = state.activeRequest
        const chatMessages = state.messagesByChatId[chatId] || []
        return {
          messagesByChatId: {
            ...state.messagesByChatId,
            [chatId]: chatMessages.map((message) =>
              request && message.id === request.placeholderId
                ? { ...message, status: 'done' }
                : message,
            ),
          },
          activeRequest: null,
          loading: false,
        }
      })
      return
    }

    if (isStale()) return
    console.warn('Streaming request failed, falling back to a non-streaming request:', error)

    try {
      const assistantMessage = await sendMessage(chatId, prompt, provider)
      if (isStale()) return
      set((state) => {
        const request = state.activeRequest
        const chatMessages = state.messagesByChatId[chatId] || []
        return {
          messagesByChatId: {
            ...state.messagesByChatId,
            [chatId]: chatMessages.map((message) =>
              request && message.id === request.placeholderId
                ? { ...assistantMessage, status: 'done', isNew: true }
                : message,
            ),
          },
          chats: touchChat(state.chats, chatId),
          activeRequest: null,
          loading: false,
        }
      })
    } catch (fallbackError) {
      console.error('Non-streaming fallback also failed:', fallbackError)
      set((state) => {
        const request = state.activeRequest
        const chatMessages = state.messagesByChatId[chatId] || []
        return {
          messagesByChatId: {
            ...state.messagesByChatId,
            [chatId]: chatMessages.map((message) =>
              request && message.id === request.placeholderId
                ? {
                    ...message,
                    content: "Sorry, I wasn't able to reach the backend. Please try again.",
                    status: 'error',
                  }
                : message,
            ),
          },
          activeRequest: null,
          loading: false,
        }
      })
    }
  }
}

export const useAppStore = create((set, get) => ({
  chats: demoChats,
  activeChatId: demoChats[0].id,
  messagesByChatId: {},
  documents: [],
  overview: null,
  settings: null,
  providers: [],
  loading: false,
  sidebarOpen: false,
  sidebarCollapsed: readStoredBoolean('localmind-sidebar-collapsed', false),
  selectedDocId: null,
  activeRequest: null,

  initApp: async () => {
    set({ loading: true })
    try {
      const [overview, chats, settings, documents, providerInfo] = await Promise.all([
        getOverview(),
        getChats(),
        getSettings(),
        getDocuments(),
        getProviders().catch(() => ({ providers: [], default: 'auto' })),
      ])

      const providerOptions = normalizeList(providerInfo?.providers, [])
      const defaultProvider = providerInfo?.default || 'auto'

      const mergedSettings = {
        endpoint: '/api',
        model: 'Mistral 7B Instruct',
        streamResponses: true,
        autoSync: true,
        theme: 'dark',
        provider: defaultProvider,
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

      // Guard against a stale saved provider that's no longer offered (e.g. its
      // API key was removed) — fall back to the server's default.
      const offered = new Set(providerOptions.map((p) => p.id))
      if (offered.size && !offered.has(mergedSettings.provider)) {
        mergedSettings.provider = defaultProvider
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
        providers: providerOptions,
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
  toggleSidebarCollapse: () =>
    set((state) => {
      const nextValue = !state.sidebarCollapsed
      writeStoredBoolean('localmind-sidebar-collapsed', nextValue)
      return { sidebarCollapsed: nextValue }
    }),

  newChat: async () => {
    const chat = await createChat('New Chat')
    set((state) => ({
      chats: [{ ...chat, title: 'New Chat', isUntitled: true }, ...normalizeList(state.chats, demoChats)],
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
          ? { ...chat, title: nextTitle, isUntitled: false, updatedAt: new Date().toISOString() }
          : chat,
      ),
    }))

    try {
      await renameChatApi(chatId, nextTitle)
    } catch (error) {
      console.error('renameChat failed to persist:', error)
    }
  },

  finalizeChatTitle: async (chatId) => {
    const chat = get().chats.find((entry) => entry.id === chatId)
    // Only auto-title once, and never override a name the user set manually.
    if (!chat || !chat.isUntitled) return

    // Clear the flag up front so concurrent completions don't double-fire.
    set((state) => ({
      chats: state.chats.map((entry) =>
        entry.id === chatId ? { ...entry, isUntitled: false } : entry,
      ),
    }))

    try {
      const { title } = await generateChatTitle(chatId)
      const clean = (title || '').trim()
      if (clean) {
        set((state) => ({
          chats: state.chats.map((entry) =>
            entry.id === chatId ? { ...entry, title: clean } : entry,
          ),
        }))
      }
    } catch (error) {
      // Keep the optimistic placeholder title on failure.
      console.warn('Chat title generation failed:', error)
    }
  },

  deleteChat: async (chatId) => {
    if (!chatId) return

    const state = get()
    const remainingChats = state.chats.filter((chat) => chat.id !== chatId)
    const restMessages = { ...state.messagesByChatId }
    delete restMessages[chatId]

    try {
      await deleteChatApi(chatId)
    } catch (error) {
      console.error('deleteChat failed to persist:', error)
    }

    if (!remainingChats.length) {
      const chat = await createChat('New Chat')
      set({
        chats: [{ ...chat, title: 'New Chat', isUntitled: true }],
        activeChatId: chat.id,
        messagesByChatId: { [chat.id]: [] },
        sidebarOpen: false,
      })
      return
    }

    set({
      chats: remainingChats,
      activeChatId: state.activeChatId === chatId ? remainingChats[0].id : state.activeChatId,
      messagesByChatId: restMessages,
      sidebarOpen: false,
    })
  },

  sendPrompt: async (content) => {
    const { activeChatId } = get()
    if (!activeChatId || !content.trim() || get().activeRequest) return

    const prompt = content.trim()
    const activeChat = get().chats.find((chat) => chat.id === activeChatId)

    const requestId = ++requestSequence
    const placeholder = createLoadingAssistantMessage(requestId)

    const userMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: prompt,
      createdAt: new Date().toISOString(),
    }

    set((state) => ({
      messagesByChatId: {
        ...state.messagesByChatId,
        [activeChatId]: [...(state.messagesByChatId[activeChatId] || []), userMessage, placeholder],
      },
      activeRequest: { id: requestId, chatId: activeChatId, placeholderId: placeholder.id },
      loading: true,
    }))

    // Optimistically show a trimmed placeholder so the sidebar isn't stuck on
    // "New Chat" during the response. isUntitled stays true so the real
    // topic-aware title (generated from the first exchange) replaces it once
    // the answer lands — see finalizeChatTitle.
    if (activeChat?.isUntitled) {
      set((state) => ({
        chats: state.chats.map((chat) =>
          chat.id === activeChatId ? { ...chat, title: buildUntitledChatTitle(prompt) } : chat,
        ),
      }))
    }

    await streamAssistantResponse(set, get, activeChatId, requestId, prompt)
    get().finalizeChatTitle(activeChatId)
  },

  stopGeneration: () => {
    const request = get().activeRequest
    if (!request?.abortController) return
    request.abortController.abort()
    // streamAssistantResponse's catch(AbortError) branch handles the resulting state update.
  },

  setMessageFeedback: (chatId, messageId, value) => {
    if (!chatId || !messageId) return

    let nextFeedback = null
    set((state) => ({
      messagesByChatId: {
        ...state.messagesByChatId,
        [chatId]: (state.messagesByChatId[chatId] || []).map((message) => {
          if (message.id !== messageId) return message
          nextFeedback = message.feedback === value ? null : value
          return { ...message, feedback: nextFeedback }
        }),
      },
    }))
    // Persist server-side (fire-and-forget) so the rating survives a reload.
    // The UI already updated optimistically above.
    setMessageFeedbackApi(chatId, messageId, nextFeedback).catch((error) => {
      console.warn('Failed to persist message feedback:', error)
    })
  },

  regenerateMessage: async (chatId, messageId) => {
    if (!chatId || !messageId || get().activeRequest) return

    const state = get()
    const messages = state.messagesByChatId[chatId] || []
    const messageIndex = messages.findIndex((message) => message.id === messageId)
    const message = messages[messageIndex]
    if (!message || message.role !== 'assistant' || message.status === 'loading' || message.status === 'streaming') return
    if (messageIndex !== messages.length - 1) return

    const previousUserMessage = [...messages.slice(0, messageIndex)]
      .reverse()
      .find((entry) => entry.role === 'user')
    if (!previousUserMessage) return

    const requestId = ++requestSequence
    const placeholder = createLoadingAssistantMessage(requestId)

    set((currentState) => ({
      messagesByChatId: {
        ...currentState.messagesByChatId,
        [chatId]: [...messages.slice(0, messageIndex), placeholder],
      },
      activeRequest: { id: requestId, chatId, placeholderId: placeholder.id },
      chats: touchChat(currentState.chats, chatId),
      loading: true,
    }))

    // Note: Global_Mind's /messages/stream endpoint always persists whatever
    // prompt it's given as a new user turn server-side. There's no
    // regenerate-without-resending endpoint, so this does create a second
    // persisted copy of the question server-side even though the UI only
    // shows one. Documented as a known limitation, not fixed here since it
    // would require a backend change out of scope for this migration.
    await streamAssistantResponse(set, get, chatId, requestId, previousUserMessage.content)
  },

  editMessage: async (chatId, messageId, newContent) => {
    if (!chatId || !messageId || get().activeRequest) return

    const nextContent = newContent.trim()
    if (!nextContent) return

    const state = get()
    const messages = state.messagesByChatId[chatId] || []
    const messageIndex = messages.findIndex((message) => message.id === messageId)
    const message = messages[messageIndex]
    if (!message || message.role !== 'user') return

    const requestId = ++requestSequence
    const placeholder = createLoadingAssistantMessage(requestId)
    const updatedUserMessage = { ...message, content: nextContent, editedAt: new Date().toISOString() }

    set((currentState) => ({
      messagesByChatId: {
        ...currentState.messagesByChatId,
        [chatId]: [...messages.slice(0, messageIndex), updatedUserMessage, placeholder],
      },
      activeRequest: { id: requestId, chatId, placeholderId: placeholder.id },
      chats: touchChat(currentState.chats, chatId),
      loading: true,
    }))

    // Same caveat as regenerateMessage: the backend will persist this as a
    // new user turn rather than truly replacing the original message.
    await streamAssistantResponse(set, get, chatId, requestId, nextContent)
  },

  markMessageAsSeen: (chatId, messageId) => {
    if (!chatId || !messageId) return

    set((state) => ({
      messagesByChatId: {
        ...state.messagesByChatId,
        [chatId]: (state.messagesByChatId[chatId] || []).map((message) =>
          message.id === messageId ? { ...message, isNew: false } : message,
        ),
      },
    }))
  },

  uploadDocument: async (file) => {
    const uploaded = await uploadDocument(file)
    await get().refreshDocuments()
    return uploaded
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
