export default function Loader({ label = 'Loading your workspace' }) {
  return (
    <div className="loader" role="status" aria-live="polite">
      <span className="loader__dot" />
      <span className="loader__dot" />
      <span className="loader__dot" />
      <span className="loader__label">{label}</span>
    </div>
  )
}
