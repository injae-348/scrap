import { useEffect, useState } from 'react'
import { ApiError } from '../api/http'

/**
 * 429(too_many_attempts / too_many_requests) 오류의 남은 대기 시간(초). 0이면 다시 시도할 수 있다.
 * 응답을 받을 때 정한 절대 시각(retryAt)을 기준으로 계산하므로, 백그라운드에서 타이머가 늦게 돌아도
 * 화면으로 돌아오는 순간(visibilitychange) 바로 맞춰진다.
 */
export function useRetryCountdown(err: unknown): number {
  const is429 = err instanceof ApiError && err.status === 429 && err.retryAt !== null && !!err.retryAfter
  const retryAt = is429 ? (err as ApiError).retryAt! : 0
  const total = is429 ? (err as ApiError).retryAfter! : 0
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!retryAt) return
    const tick = () => setNow(Date.now())
    const t = setInterval(tick, 1000)
    const first = setTimeout(tick, 0)
    document.addEventListener('visibilitychange', tick)
    return () => {
      clearInterval(t)
      clearTimeout(first)
      document.removeEventListener('visibilitychange', tick)
    }
  }, [retryAt])

  if (!retryAt) return 0
  // now가 오류보다 먼저 정해졌을 수 있으므로 Retry-After 값보다 커지지 않게 한다
  return Math.min(total, Math.max(0, Math.ceil((retryAt - now) / 1000)))
}
