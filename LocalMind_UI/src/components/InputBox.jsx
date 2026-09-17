import { forwardRef } from 'react'
import { ArrowUp, Square } from 'lucide-react'
import TextareaAutosize from 'react-textarea-autosize'

const InputBox = forwardRef(function InputBox(
  {
    value,
    onChange,
    onSubmit,
    onStop,
    disabled = false,
    loading = false,
    cooldown = 0,
    placeholder = 'Ask about your documents or connected data...',
    footer = null,
    modeSlot = null,
  },
  ref,
) {
  const isBlocked = disabled || loading || cooldown > 0
  const canSubmit = value.trim().length > 0 && !isBlocked

  const currentPlaceholder = cooldown > 0
    ? `Rate protection: ready in ${cooldown}s...`
    : placeholder

  return (
    <form
      className="composer__shell"
      onSubmit={(event) => {
        event.preventDefault()
        if (canSubmit) onSubmit?.()
      }}
    >
      <TextareaAutosize
        ref={ref}
        className="composer__input"
        placeholder={currentPlaceholder}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key !== 'Enter') return
          if (event.shiftKey) return
          event.preventDefault()
          if (canSubmit) onSubmit?.()
        }}
        minRows={2}
        maxRows={2}
        disabled={isBlocked}
      />
      <div className="composer__footer">
        <div className="composer__footer-left">{footer}</div>
        <div className="composer__actions">
          {modeSlot}
          {loading ? (
            <button
              type="button"
              className="composer__stop"
              onClick={onStop}
              aria-label="Stop generating"
            >
              <Square size={14} fill="currentColor" />
            </button>
          ) : cooldown > 0 ? (
            <div
              className="composer__cooldown"
              title={`Rate protection: ready in ${cooldown}s`}
            >
              {cooldown}s
            </div>
          ) : (
            <button
              type="submit"
              className="composer__send"
              disabled={!canSubmit}
              aria-label="Send message"
            >
              <ArrowUp size={18} strokeWidth={2.5} />
            </button>
          )}
        </div>
      </div>
    </form>
  )
})

export default InputBox
