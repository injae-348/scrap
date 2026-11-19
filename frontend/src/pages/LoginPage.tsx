import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { authApi } from '../api'
import { errorMessage } from '../api/http'
import { AuthShell, CodeInput, MockHint } from '../components/auth'
import { Button, Field, Notice } from '../components/ui'
import { keys } from '../hooks/queries'
import { inputCls } from '../lib/styles'

/** 로그인: 비밀번호 → 6자리 코드 (또는 복구 코드) */
export function LoginPage() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [recovery, setRecovery] = useState('')
  const [useRecovery, setUseRecovery] = useState(false)

  const login = useMutation({ mutationFn: authApi.login })
  const verify = useMutation({
    mutationFn: authApi.loginVerify,
    onSuccess: async () => {
      // 이전 사용자 캐시가 남지 않게 비우고 상태를 다시 받는다
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== 'auth' })
      await qc.invalidateQueries({ queryKey: keys.authStatus })
      navigate('/', { replace: true })
    },
  })
  const challenge = login.data?.challenge_id

  const submitCode = (c: string) => {
    if (challenge && c.length === 6 && !verify.isPending) verify.mutate({ challenge_id: challenge, code: c })
  }

  const restart = () => {
    login.reset()
    verify.reset()
    setCode('')
    setRecovery('')
    setUseRecovery(false)
  }

  if (!challenge)
    return (
      <AuthShell title="로그인">
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault()
            login.mutate({ username: username.trim(), password })
          }}
        >
          <Field label="아이디" htmlFor="username">
            <input
              id="username"
              autoComplete="username"
              autoCapitalize="off"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className={inputCls}
            />
          </Field>
          <Field label="비밀번호" htmlFor="password">
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={inputCls}
            />
          </Field>
          {login.isError && <Notice tone="danger">{errorMessage(login.error)}</Notice>}
          <MockHint>아무 아이디·비밀번호 (비밀번호 'wrong'은 실패, 5번 실패하면 잠금)</MockHint>
          <Button type="submit" variant="primary" className="w-full" loading={login.isPending} disabled={!username.trim() || !password}>
            다음
          </Button>
        </form>
      </AuthShell>
    )

  return (
    <AuthShell
      title={useRecovery ? '복구 코드로 로그인' : '인증 코드 입력'}
      subtitle={
        useRecovery
          ? '보관해 둔 복구 코드 중 하나를 입력하세요. 쓴 코드는 다시 쓸 수 없어요.'
          : '인증 앱에 표시된 6자리 코드를 입력하세요.'
      }
    >
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (useRecovery) verify.mutate({ challenge_id: challenge, recovery_code: recovery.trim() })
          else submitCode(code)
        }}
      >
        {useRecovery ? (
          <Field label="복구 코드" htmlFor="recovery">
            <input
              id="recovery"
              autoFocus
              autoComplete="off"
              autoCapitalize="off"
              spellCheck={false}
              placeholder="xxxx-xxxx"
              value={recovery}
              onChange={(e) => setRecovery(e.target.value)}
              className={`${inputCls} font-mono`}
            />
          </Field>
        ) : (
          <Field label="6자리 코드" htmlFor="otp">
            <CodeInput value={code} onChange={setCode} onComplete={submitCode} disabled={verify.isPending} />
          </Field>
        )}
        {verify.isError && <Notice tone="danger">{errorMessage(verify.error)}</Notice>}
        <MockHint>{useRecovery ? 'xxxx-xxxx 형식이면 통과' : '아무 6자리 (000000은 실패)'}</MockHint>
        <Button
          type="submit"
          variant="primary"
          className="w-full"
          loading={verify.isPending}
          disabled={useRecovery ? !recovery.trim() : code.length !== 6}
        >
          로그인
        </Button>
        <div className="flex flex-col items-center gap-1 text-sm">
          <button
            type="button"
            className="min-h-11 text-accent underline"
            onClick={() => {
              verify.reset()
              setUseRecovery(!useRecovery)
            }}
          >
            {useRecovery ? '인증 코드로 로그인' : '휴대폰을 쓸 수 없나요? 복구 코드로 로그인'}
          </button>
          <button type="button" className="min-h-11 text-muted" onClick={restart}>
            처음으로
          </button>
        </div>
      </form>
    </AuthShell>
  )
}
