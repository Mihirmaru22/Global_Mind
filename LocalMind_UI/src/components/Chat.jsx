import { AnimatePresence, motion } from 'framer-motion'
import { useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import { useAppStore } from '../store/store.js'
import InputBox from './InputBox.jsx'
import Loader from './Loader.jsx'
import Message from './Message.jsx'

export default function Chat() {
  const activeChatId = useAppStore((state) => state.activeChatId)
  const messagesByChatId = useAppStore((state) => state.messagesByChatId)
  const sendPrompt = useAppStore((state) => state.sendPrompt)
  const chats = useAppStore((state) => state.chats)
  const loading = useAppStore((state) => state.loading)
  const [value, setValue] = useState('')
  const inputRef = useRef(null)
  const bottomRef = useRef(null)

  const messages = useMemo(
    () => messagesByChatId[activeChatId] || [],
    [activeChatId, messagesByChatId],
  )
  const lastMessageId = messages[messages.length - 1]?.id

  useEffect(() => {
    if (!chats.length) {
      toast.info('Waiting for demo chat data.')
    }
  }, [chats.length])

  useEffect(() => {
    inputRef.current?.focus()
  }, [activeChatId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({
      behavior: 'smooth',
      block: 'end',
    })
  }, [activeChatId, lastMessageId, loading])

  return (
    <section className="chat-panel">
      <div className="message-stream">
        <AnimatePresence mode="popLayout">
          {messages.length ? (
            messages.map((message, index) => (
              <Message key={message.id} message={message} index={index} />
            ))
          ) : (
            <motion.div
              key="empty"
              className="hero"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
            >
              <p className="hero__eyebrow">Private local intelligence</p>
              <h2 className="hero__title">
                How can I help you <em>locally</em> today?
              </h2>
              <p className="hero__copy">
                Your data stays on your machine. This UI is showing static demo
                content for now, and the live API hook points are documented in
                the data layer for later.
              </p>
              <div className="feature-grid">
                <article className="feature-card">
                  <strong className="feature-card__title">Analyze PDF</strong>
                  <p className="feature-card__text">Upload local documents</p>
                </article>
                <article className="feature-card">
                  <strong className="feature-card__title">Refactor Code</strong>
                  <p className="feature-card__text">Local IDE integration</p>
                </article>
                <article className="feature-card">
                  <strong className="feature-card__title">Brainstorm</strong>
                  <p className="feature-card__text">Private idea mapping</p>
                </article>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {loading ? <Loader /> : null}
        <div ref={bottomRef} aria-hidden="true" />
      </div>

      <div className="composer">
        <InputBox
          ref={inputRef}
          value={value}
          onChange={setValue}
          onSubmit={async () => {
            const prompt = value.trim()
            if (!prompt) return
            setValue('')
            await sendPrompt(prompt)
            inputRef.current?.focus()
          }}
          disabled={loading}
        />
      </div>
    </section>
  )
}
