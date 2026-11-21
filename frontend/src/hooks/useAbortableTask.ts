import { useCallback, useEffect, useRef, useState } from 'react'

export type TaskState =
  | { status: 'idle' }
  | { status: 'pending' }
  | { status: 'success' }
  | { status: 'cancelled' }
  | { status: 'error'; error: unknown }

/**
 * 오래 걸리는 요청(AI) 하나를 돌리고 취소할 수 있게 한다.
 * - run을 다시 부르면 이전 요청은 취소된다 (늦게 온 이전 응답은 버림).
 * - cancel(): 사용자가 취소. 상태는 'cancelled'.
 * - 컴포넌트가 사라지면(화면 이탈) 진행 중인 요청을 취소한다.
 */
export function useAbortableTask() {
  const ctrl = useRef<AbortController | null>(null)
  const [state, setState] = useState<TaskState>({ status: 'idle' })

  useEffect(
    () => () => {
      ctrl.current?.abort()
      ctrl.current = null
    },
    [],
  )

  const run = useCallback(
    <T>(fn: (signal: AbortSignal) => Promise<T>, onSuccess: (value: T) => void, onError?: (error: unknown) => void) => {
    ctrl.current?.abort()
    const c = new AbortController()
    ctrl.current = c
    setState({ status: 'pending' })
    fn(c.signal).then(
      (value) => {
        if (ctrl.current !== c) return
        ctrl.current = null
        setState({ status: 'success' })
        onSuccess(value)
      },
      (error: unknown) => {
        if (ctrl.current !== c) return
        ctrl.current = null
        if (c.signal.aborted) {
          setState({ status: 'cancelled' })
          return
        }
        setState({ status: 'error', error })
        onError?.(error)
      },
    )
  }, [])

  const cancel = useCallback(() => {
    const c = ctrl.current
    if (!c) return
    ctrl.current = null
    c.abort()
    setState({ status: 'cancelled' })
  }, [])

  const reset = useCallback(() => setState({ status: 'idle' }), [])

  return { state, run, cancel, reset }
}
