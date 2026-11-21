import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'

/**
 * 인증 요청(가입·로그인·2차 인증 재설정)용 뮤테이션.
 * 보낸 값(비밀번호·가입 토큰·코드)과 받은 값(TOTP 비밀값·복구 코드)을 뮤테이션 캐시에 남기지 않는다:
 * - gcTime 0: 관찰자가 없어지면 바로 캐시에서 지운다.
 * - 끝나면(성공·실패) 곧바로 reset()으로 관찰자를 떼고, 화면에 필요한 결과는 호출한 쪽이 onSuccess에서 상태로 옮긴다.
 * - 오류 객체(code·message·retryAfter만 있음)는 이 훅의 상태로 들고 있는다.
 */
export function useAuthMutation<TVars, TData>(fn: (vars: TVars) => Promise<TData>) {
  const m = useMutation<TData, unknown, TVars>({ mutationFn: fn, gcTime: 0, retry: false })
  const [error, setError] = useState<unknown>(null)

  const mutate = (vars: TVars, opts?: { onSuccess?: (data: TData) => void; onError?: (e: unknown) => void }) => {
    setError(null)
    m.mutate(vars, {
      onSuccess: (data) => {
        m.reset()
        opts?.onSuccess?.(data)
      },
      onError: (e) => {
        m.reset()
        setError(e)
        opts?.onError?.(e)
      },
    })
  }

  return { mutate, isPending: m.isPending, error, clearError: () => setError(null) }
}
