import { useEffect, useRef, useState, type ButtonHTMLAttributes, type KeyboardEvent, type ReactNode } from 'react'
import { cx } from '../lib/styles'
import { IconAlert, IconInbox } from './Icons'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'

const variantCls: Record<Variant, string> = {
  primary: 'bg-accent-solid text-on-accent hover:brightness-110 active:brightness-95',
  secondary: 'border border-line bg-bg text-fg hover:bg-hover',
  ghost: 'text-fg hover:bg-hover',
  danger: 'border border-line bg-bg text-danger hover:bg-danger-soft',
}

export function Button({
  variant = 'secondary',
  size = 'md',
  loading,
  className,
  children,
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant
  size?: 'md' | 'lg' | 'icon'
  loading?: boolean
}) {
  return (
    <button
      type="button"
      disabled={disabled || loading}
      className={cx(
        'inline-flex items-center justify-center gap-2 rounded-lg font-medium transition select-none',
        'disabled:opacity-50',
        size === 'md' && 'min-h-11 px-4 text-sm',
        size === 'lg' && 'min-h-14 px-5 text-base',
        size === 'icon' && 'size-11 shrink-0',
        variantCls[variant],
        className,
      )}
      {...rest}
    >
      {loading && <Spinner />}
      {children}
    </button>
  )
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      role="status"
      aria-label="불러오는 중"
      className={cx('inline-block size-4 animate-spin rounded-full border-2 border-current border-r-transparent', className)}
    />
  )
}

export function Field({
  label,
  htmlFor,
  hint,
  badge,
  children,
}: {
  label: string
  htmlFor?: string
  hint?: ReactNode
  badge?: ReactNode
  children: ReactNode
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2">
        <label htmlFor={htmlFor} className="text-sm font-medium text-fg">
          {label}
        </label>
        {badge}
      </div>
      {children}
      {hint && <div className="text-xs text-muted">{hint}</div>}
    </div>
  )
}

export function Chip({
  active,
  children,
  className,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { active?: boolean }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      className={cx(
        'inline-flex min-h-11 shrink-0 items-center gap-1 rounded-full border px-3.5 text-sm whitespace-nowrap transition lg:min-h-9',
        active
          ? 'border-accent bg-accent-soft font-medium text-accent'
          : 'border-line bg-bg text-muted hover:bg-hover hover:text-fg',
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  )
}

export function ErrorState({ message, onRetry, action }: { message: string; onRetry?: () => void; action?: ReactNode }) {
  return (
    <div role="alert" className="flex flex-col items-center gap-3 px-6 py-16 text-center">
      <IconAlert size={32} className="text-danger" />
      <p className="text-sm text-fg">{message}</p>
      {onRetry && <Button onClick={onRetry}>다시 시도</Button>}
      {action}
    </div>
  )
}

export function EmptyState({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-16 text-center">
      <IconInbox size={36} className="text-muted" />
      <p className="font-medium text-fg">{title}</p>
      {description && <p className="text-sm text-muted">{description}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  )
}

export function ListSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <ul aria-label="불러오는 중" className="divide-y divide-line">
      {Array.from({ length: rows }, (_, i) => (
        <li key={i} className="animate-pulse space-y-2 px-4 py-4">
          <div className="h-4 w-3/4 rounded bg-hover" />
          <div className="h-3 w-1/2 rounded bg-hover" />
        </li>
      ))}
    </ul>
  )
}

export function Notice({ tone = 'info', children }: { tone?: 'info' | 'warn' | 'danger' | 'ok'; children: ReactNode }) {
  const cls = {
    info: 'bg-accent-soft text-fg border-accent/30',
    warn: 'bg-warn-soft text-fg border-warn/30',
    danger: 'bg-danger-soft text-danger border-danger/30',
    ok: 'bg-ok-soft text-fg border-ok/30',
  }[tone]
  return (
    <div role={tone === 'danger' ? 'alert' : 'status'} className={cx('rounded-lg border px-3 py-2.5 text-sm', cls)}>
      {children}
    </div>
  )
}

/** 한 번 누르면 확인 버튼으로 바뀌는 위험 작업 버튼 */
export function ConfirmButton({
  label,
  confirmLabel,
  onConfirm,
  loading,
  icon,
}: {
  label: string
  confirmLabel: string
  onConfirm: () => void
  loading?: boolean
  icon?: ReactNode
}) {
  const [asking, setAsking] = useState(false)
  if (!asking)
    return (
      <Button variant="danger" onClick={() => setAsking(true)}>
        {icon}
        {label}
      </Button>
    )
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <Button
        variant="primary"
        className="bg-danger! text-bg!"
        loading={loading}
        onClick={() => {
          onConfirm()
        }}
      >
        {confirmLabel}
      </Button>
      <Button variant="ghost" onClick={() => setAsking(false)}>
        취소
      </Button>
    </span>
  )
}

export function Badge({ tone, children }: { tone: 'warn' | 'danger' | 'muted' | 'accent'; children: ReactNode }) {
  const cls = {
    warn: 'bg-warn-soft text-warn',
    danger: 'bg-danger-soft text-danger',
    muted: 'bg-hover text-muted',
    accent: 'bg-accent-soft text-accent',
  }[tone]
  return (
    <span className={cx('inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium whitespace-nowrap', cls)}>
      {children}
    </span>
  )
}

/** 작성 중 이탈 확인 (useLeaveGuard의 blocker와 함께 쓴다). onLeave가 없으면 "나가기" 버튼을 숨긴다 */
export function LeaveDialog(props: {
  open: boolean
  title?: string
  message?: ReactNode
  stayLabel?: string
  leaveLabel?: string
  onStay: () => void
  onLeave?: () => void
}) {
  if (!props.open) return null
  return <LeaveDialogBody {...props} />
}

function LeaveDialogBody({
  title = '작성 중인 내용이 있어요',
  message = '이 화면을 나가면 저장하지 않은 내용이 사라져요.',
  stayLabel = '계속 작성',
  leaveLabel = '나가기',
  onStay,
  onLeave,
}: {
  title?: string
  message?: ReactNode
  stayLabel?: string
  leaveLabel?: string
  onStay: () => void
  onLeave?: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)

  // 열려 있는 동안 포커스를 대화상자 안에 두고, 닫히면 열기 전 위치로 돌려준다
  // (autoFocus가 포커스를 옮기기 전에 기억해야 하므로 처음 렌더 때 읽는다)
  const [prevFocus] = useState(() => (document.activeElement instanceof HTMLElement ? document.activeElement : null))
  useEffect(() => {
    const node = ref.current
    return () => {
      // 실제로 닫혀 화면에서 빠졌을 때만 돌려준다 (개발 모드의 effect 재실행에서는 그대로 둔다)
      if (!node?.isConnected && prevFocus?.isConnected) prevFocus.focus()
    }
  }, [prevFocus])

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Escape') {
      e.preventDefault()
      onStay()
      return
    }
    if (e.key !== 'Tab') return
    const items = ref.current ? [...ref.current.querySelectorAll<HTMLElement>('button:not([disabled])')] : []
    if (!items.length) return
    const first = items[0]
    const last = items[items.length - 1]
    const active = document.activeElement
    if (e.shiftKey && (active === first || !ref.current?.contains(active))) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && (active === last || !ref.current?.contains(active))) {
      e.preventDefault()
      first.focus()
    }
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-end justify-center bg-black/40 px-safe-4 pb-safe sm:items-center">
      <div
        ref={ref}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="leave-title"
        aria-describedby="leave-desc"
        onKeyDown={onKeyDown}
        className="mb-4 w-full max-w-sm space-y-4 rounded-2xl border border-line bg-bg p-5 shadow-xl sm:mb-0"
      >
        <div className="space-y-1.5">
          <h2 id="leave-title" className="text-base font-semibold">
            {title}
          </h2>
          <p id="leave-desc" className="text-sm text-muted">
            {message}
          </p>
        </div>
        <div className="flex justify-end gap-2">
          {onLeave && (
            <Button variant="ghost" className="text-danger" onClick={onLeave}>
              {leaveLabel}
            </Button>
          )}
          <Button variant="primary" autoFocus onClick={onStay}>
            {stayLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}
