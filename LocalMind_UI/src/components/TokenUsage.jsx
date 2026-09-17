import { ChevronDown, Coins } from 'lucide-react'
import { useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'

const fmt = (value) => (value ?? 0).toLocaleString()

export default function TokenUsage({ usage }) {
  const [open, setOpen] = useState(false)
  if (!usage) return null

  const input = usage.input_tokens || 0
  const output = usage.output_tokens || 0
  const thinking = usage.thinking_tokens || 0
  const total = usage.total_tokens ?? input + output + thinking
  if (total <= 0) return null

  const segments = [
    { key: 'input', label: 'Input', hint: 'context + prompt', value: input },
    { key: 'output', label: 'Output', hint: 'the answer', value: output },
    ...(thinking > 0
      ? [{ key: 'thinking', label: 'Thinking', hint: 'hidden reasoning', value: thinking }]
      : []),
  ]

  const pct = (value) => (total ? `${(value / total) * 100}%` : '0%')
  const callsText = usage.calls ? ` - ${usage.calls} LLM call${usage.calls === 1 ? '' : 's'}` : ''

  const bar = (
    <span className="token__bar" aria-hidden="true">
      {segments.map((segment) => (
        <span
          key={segment.key}
          className={`token__seg token__seg--${segment.key}`}
          style={{ width: pct(segment.value) }}
          title={`${segment.label}: ${fmt(segment.value)}`}
        />
      ))}
    </span>
  )

  return (
    <div className={`token ${open ? 'token--open' : ''}`}>
      <button
        type="button"
        className="token__header"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <Coins size={13} className="token__icon" />
        <span className="token__summary">
          {fmt(total)} tokens{callsText}
        </span>
        <span className="token__bar-wrap token__bar-wrap--mini">{bar}</span>
        <ChevronDown
          size={12}
          className={`token__chevron ${open ? 'token__chevron--open' : ''}`}
        />
      </button>

      <AnimatePresence>
        {open ? (
          <motion.div
            className="token__details"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.18 }}
          >
            <div className="token__bar-wrap">{bar}</div>
            <ul className="token__rows">
              {segments.map((segment) => (
                <li key={segment.key} className="token__row">
                  <span className={`token__dot token__seg--${segment.key}`} />
                  <span className="token__row-label">{segment.label}</span>
                  <span className="token__row-hint">{segment.hint}</span>
                  <span className="token__row-value">{fmt(segment.value)}</span>
                </li>
              ))}
              <li className="token__row token__row--total">
                <span className="token__row-label">Total</span>
                <span className="token__row-value">{fmt(total)}</span>
              </li>
            </ul>

            {(usage.model || usage.calls) ? (
              <div className="token__meta">
                {usage.model ? (
                  <span className="token__meta-item">
                    {usage.provider ? `${usage.provider} - ` : ''}
                    {usage.model}
                  </span>
                ) : null}
                {usage.calls ? (
                  <span className="token__meta-item">
                    {usage.calls} LLM call{usage.calls === 1 ? '' : 's'}
                  </span>
                ) : null}
              </div>
            ) : null}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  )
}
