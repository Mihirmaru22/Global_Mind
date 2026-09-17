export default function BrandMark({ size = 34, className }) {
  return (
    <img
      src="/localmind-logo.png"
      width={size}
      height={size}
      className={className}
      alt=""
      aria-hidden="true"
      draggable="false"
    />
  )
}
