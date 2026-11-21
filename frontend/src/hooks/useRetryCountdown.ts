import { useEffect, useState } from 'react'
import { ApiError } from '../api/http'

/**
 * 429(too_many_attempts / too_many_requests) 오류의 Retry-After를 초 단위로 줄여 가며 돌려준다.
 * 0이면 다시 시도할 수 있다. 오류가 바뀌면 새로 센다.
 */
export function useRetryCountdown(err: unknown): number {
  const total = err instanceof ApiError && err.status === 429 && err.retryAfter ? err.retryAfter : 0
  const [tracked, setTracked] = useState<{ err: unknown; elapsed: number }>({ err, elapsed: 0 })

  // 새 오류가 오면 처음부터 센다 (렌더 중 이전 값과 비교해 바로 맞추는 React 권장 방식)
  if (tracked.err !== err) setTracked({ err, elapsed: 0 })
  const elapsed = tracked.err === err ? tracked.elapsed : 0
  const remaining = Math.max(0, total - elapsed)

  useEffect(() => {
    if (!total) return
    const t = setInterval(() => {
      setTracked((s) => (s.err === err ? { err, elapsed: s.elapsed + 1 } : s))
    }, 1000)
    return () => clearInterval(t)
  }, [err, total])

  return remaining
}
