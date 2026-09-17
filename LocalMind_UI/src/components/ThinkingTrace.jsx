import { Brain, Check, ChevronDown, Loader2, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'

export default function ThinkingTrace({ steps = [], streaming = false }) {
  const [open, setOpen] = useState(streaming)

  useEffect(() => {
    setOpen(streaming)
  }, [streaming])

  if (!steps.length) return null

  return (
    <div className={`thinking ${streaming ? 'thinking--live' : ''}`}>
      <button
        type="button"
        className="thinking__header"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <Brain size={14} className="thinking__icon" />
        <span className="thinking__label">
          {streaming ? 'Thinking...' : 'Thought process...'}
        </span>
        <ChevronDown
          size={13}
          className={`thinking__chevron ${open ? 'thinking__chevron--open' : ''}`}
        />
      </button>

      <AnimatePresence>
        {open ? (
          <motion.ol
            className="thinking__steps"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.18 }}
          >
            {steps.map((step, index) => {
              const isLast = index === steps.length - 1
              const isFailed = step.status === 'error' || Boolean(step.error)
              const isProcessing = streaming && isLast && !isFailed
              return (
                <li
                  key={`${step.label}-${index}`}
                  className={`thinking__step ${
                    isFailed ? 'thinking__step--fail' : isProcessing ? 'thinking__step--active' : 'thinking__step--done'
                  }`}
                >
                  {isFailed ? (
                    <X
                      size={13}
                      strokeWidth={1.5}
                      className="thinking__step-marker thinking__step-marker--fail"
                      aria-hidden="true"
                    />
                  ) : isProcessing ? (
                    <Loader2
                      size={13}
                      strokeWidth={1.5}
                      className="thinking__step-marker thinking__step-marker--processing spin"
                      aria-hidden="true"
                    />
                  ) : (
                    <Check
                      size={13}
                      strokeWidth={1.5}
                      className="thinking__step-marker thinking__step-marker--done"
                      aria-hidden="true"
                    />
                  )}
                  <span className="thinking__step-label">{step.label}</span>
                  {step.detail ? (
                    <span className="thinking__step-detail">{step.detail}</span>
                  ) : null}
                </li>
              )
            })}
          </motion.ol>
        ) : null}
      </AnimatePresence>
    </div>
  )
}
