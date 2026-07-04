import clsx from 'clsx'

export default function Button({
  as: Component = 'button',
  className,
  variant = 'primary',
  type = 'button',
  ...props
}) {
  return (
    <Component
      type={Component === 'button' ? type : undefined}
      className={clsx(
        variant === 'primary' ? 'primary-button' : 'secondary-button',
        className,
      )}
      {...props}
    />
  )
}
