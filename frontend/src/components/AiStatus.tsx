import { useEffect, useState } from 'react'
import { aiErrorMessage, ApiError, formatWait } from '../api/http'
import { useRetryCountdown } from '../hooks/useRetryCountdown'
import { cx } from '../lib/styles'
import { Button, Notice, Spinner } from './ui'

/**
 * AI 요청 진행 표시 + 취소 버튼. 수십 초 걸릴 수 있으므로 지난 시간을 함께 보여 준다.
 * 지난 시간은 이 표시가 나타난 순간부터 센다 (요청을 시작할 때 함께 나타난다).
 */
export function AiProgress({
  label,
  hint,
  cancelLabel,
  onCancel,
  className,
}: {
  label: string
  hint?: string
  cancelLabel: string
  onCancel: () => void
  className?: string
}) {
  const [startedAt] = useState(() => Date.now())
  const [now, setNow] = useState(startedAt)
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])
  const sec = Math.max(0, Math.floor((now - startedAt) / 1000))

  return (
    <div className={cx('rounded-lg border border-accent/30 bg-accent-soft px-3 py-2 text-sm', className)}>
      <div className="flex items-center gap-2">
        <Spinner className="shrink-0 text-accent" />
        <p role="status" className="min-w-0 flex-1 text-fg">
          {label}
        </p>
        {/* 매초 바뀌므로 화면 읽기 프로그램에는 알리지 않는다 */}
        <span aria-hidden="true" className="shrink-0 text-xs text-muted tabular-nums">
          {formatWait(sec)}
        </span>
        <Button variant="secondary" onClick={onCancel} className="shrink-0">
          {cancelLabel}
        </Button>
      </div>
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  )
}

/**
 * AI 요청 오류 안내 (docs/API.md "AI 세부 규칙 → 프론트 표시").
 * 429는 Retry-After 기준으로 남은 시간을 세고, 그동안 다시 시도 버튼을 막는다.
 * ai_unavailable(서버 설정 필요)과 ai_quota_exceeded(월 사용 한도 도달)는 다시 시도해도 같으므로 버튼을 두지 않는다.
 * 둘은 같은 503이지만 code로 나눠 문구와 표시를 구분한다 (한도 도달은 경고, 설정 필요는 오류).
 * 입력 오류(invalid_input 등 429를 뺀 4xx)도 같은 요청을 다시 보내면 같은 결과이므로 버튼을 두지 않는다.
 */
export function AiErrorNotice({ error, op, onRetry }: { error: unknown; op: 'extract' | 'search'; onRetry?: () => void }) {
  const wait = useRetryCountdown(error)
  const is429 = error instanceof ApiError && error.status === 429 && !!error.retryAfter
  const code = error instanceof ApiError ? error.code : null
  const quota = code === 'ai_quota_exceeded'
  const clientError = error instanceof ApiError && error.status >= 400 && error.status < 500 && error.status !== 429
  const noRetry = code === 'ai_unavailable' || quota || clientError
  return (
    <Notice tone={quota ? 'warn' : 'danger'}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <p className="min-w-0 flex-1">
          {aiErrorMessage(error, op)}
          {is429 && (
            <span aria-live="off">
              {wait > 0 ? ` ${formatWait(wait)} 뒤에 다시 시도할 수 있어요.` : ' 이제 다시 시도할 수 있어요.'}
            </span>
          )}
        </p>
        {onRetry && !noRetry && (
          <Button variant="secondary" disabled={wait > 0} onClick={onRetry} className="shrink-0">
            다시 시도
          </Button>
        )}
      </div>
    </Notice>
  )
}
