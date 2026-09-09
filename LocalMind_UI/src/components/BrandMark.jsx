// Small mesh network converging on one center point — your documents
// feeding one local brain. Hand-tuned at this size (not scaled down from a
// larger version): stroke weight and node size are proportioned to stay
// legible at 16-32px, where thin multi-node marks tend to blur into a blob.
export default function BrandMark({ size = 20, className }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden="true"
    >
      <g transform="translate(16,16)" stroke="currentColor" strokeLinecap="round">
        <line x1="0" y1="0" x2="0" y2="-8.5" strokeWidth="2.1" opacity="0.75" />
        <line x1="0" y1="0" x2="8" y2="2.5" strokeWidth="2.1" opacity="0.75" />
        <line x1="0" y1="0" x2="-5" y2="6.8" strokeWidth="2.1" opacity="0.75" />
        <line x1="0" y1="0" x2="-6.7" y2="-4.3" strokeWidth="2.1" opacity="0.75" />
      </g>
      <g transform="translate(16,16)" fill="currentColor">
        <circle cx="0" cy="-8.5" r="2.3" />
        <circle cx="8" cy="2.5" r="2.3" />
        <circle cx="-5" cy="6.8" r="2.3" />
        <circle cx="-6.7" cy="-4.3" r="2.3" />
        <circle cx="0" cy="0" r="3.1" />
      </g>
    </svg>
  )
}
