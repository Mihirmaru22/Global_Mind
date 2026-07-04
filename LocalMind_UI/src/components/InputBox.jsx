import { forwardRef } from 'react'
import { Send } from 'lucide-react'
import Button from './Button.jsx'

const InputBox = forwardRef(function InputBox(
  {
    value,
    onChange,
    onSubmit,
    disabled = false,
    placeholder = 'Type a message ...',
  },
  ref,
) {
  const canSubmit = value.trim().length > 0 && !disabled

  return (
    <form
      className="composer__shell"
      onSubmit={(event) => {
        event.preventDefault()
        if (canSubmit) onSubmit?.()
      }}
    >
      <textarea
        ref={ref}
        className="composer__input"
        placeholder={placeholder}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key !== 'Enter') return
          if (event.shiftKey) return
          event.preventDefault()
          if (canSubmit) {
            onSubmit?.()
          }
        }}
      />
      <Button type="submit" disabled={!canSubmit} className="composer__send" aria-label="Send message">
        <Send size={18} />
      </Button>
    </form>
  )
})

export default InputBox
