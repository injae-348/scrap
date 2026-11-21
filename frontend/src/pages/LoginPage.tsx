import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router'
import { authApi } from '../api'
import type { LoginVerifyRequest } from '../api/types'
import { errorMessage, isApiError } from '../api/http'
import { AuthErrorNotice, AuthShell, CodeInput } from '../components/auth'
import { Button, ErrorState, Field, Notice, Spinner } from '../components/ui'
import { clearPrivateCache, keys, useAuthStatus } from '../hooks/queries'
import { useAuthMutation } from '../hooks/useAuthMutation'
import { useRetryCountdown } from '../hooks/useRetryCountdown'
import { usernameInputProps } from '../lib/authInputs'
import { clearFlash, peekFlash } from '../lib/flash'
import { inputCls } from '../lib/styles'

interface LoginState {
  from?: string
  expired?: boolean
}

/** 로그인 뒤 돌아갈 경로. 앱 안 경로만 허용한다 */
function safeFrom(from: unknown): string {
  return typeof from === 'string' && from.startsWith('/') && !from.startsWith('//') && !from.startsWith('/login')
    ? from
    : '/'
}

/** 로그인: 비밀번호 → 6자리 코드 (또는 복구 코드) */
export function LoginPage() {
  const status = useAuthStatus()
  const location = useLocation()
  const st = (location.state ?? {}) as LoginState

  if (status.isPending)
    return (
      <div className="flex min-h-dvh items-center justify-center text-muted">
        <Spinner className="size-6" />
      </div>
    )
  if (status.isError)
    return (
      <AuthShell title="로그인">
        <ErrorState message={`서버 상태를 확인하지 못했어요. ${errorMessage(status.error)}`} onRetry={() => status.refetch()} />
      </AuthShell>
    )
  if (status.data.setup_required) return <Navigate to="/setup" replace />
  if (status.data.logged_in) return <Navigate to={safeFrom(st.from)} replace />
  return <LoginForm state={st} />
}

function LoginForm({ state }: { state: LoginState }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [recovery, setRecovery] = useState('')
  const [useRecovery, setUseRecovery] = useState(false)
  const [restartReason, setRestartReason] = useState<string | null>(null)
  // 다른 화면에서 넘겨준 한 번짜리 안내 (예: 모든 기기 로그아웃 뒤)
  const [notice] = useState(peekFlash)
  useEffect(() => clearFlash(), [])
  // 로그인 화면에 들어오면(세션 만료 포함) 이전에 받아 둔 개인 데이터 캐시를 비운다
  useEffect(() => clearPrivateCache(qc), [qc])
  const passwordRef = useRef<HTMLInputElement>(null)

  // 비밀번호·코드는 뮤테이션 캐시에 남지 않는다 (useAuthMutation). 다음 단계에는 challenge_id만 들고 간다
  const login = useAuthMutation(authApi.login)
  const verify = useAuthMutation(authApi.loginVerify)
  const [challenge, setChallenge] = useState<string | null>(null)
  const loginWait = useRetryCountdown(login.error)
  const verifyWait = useRetryCountdown(verify.error)

  const submitLogin = () => {
    if (loginWait > 0) return
    login.mutate(
      { username: username.trim(), password },
      {
        onSuccess: (d) => {
          setRestartReason(null)
          setPassword('')
          setChallenge(d.challenge_id)
        },
        onError: (e) => {
          if (isApiError(e, 'invalid_credentials')) {
            setPassword('')
            passwordRef.current?.focus()
          }
        },
      },
    )
  }

  const submitVerify = (body: LoginVerifyRequest) => {
    if (verify.isPending || verifyWait > 0) return
    verify.mutate(body, {
      onSuccess: async () => {
        // 이전 사용자 캐시가 남지 않게 비우고 상태를 다시 받는다
        clearPrivateCache(qc)
        setChallenge(null)
        await qc.invalidateQueries({ queryKey: keys.authStatus })
        navigate(safeFrom(state.from), { replace: true })
      },
      onError: (e) => {
        if (isApiError(e, 'challenge_expired')) {
          restart('인증 시간이 지났거나 시도 횟수를 넘겼어요. 아이디와 비밀번호부터 다시 입력해 주세요.')
        } else if (isApiError(e, 'invalid_code')) {
          setCode('')
          setRecovery('')
        }
      },
    })
  }

  const submitCode = (c: string) => {
    if (challenge && c.length === 6) submitVerify({ challenge_id: challenge, code: c })
  }

  function restart(reason: string | null = null) {
    login.clearError()
    verify.clearError()
    setChallenge(null)
    setCode('')
    setRecovery('')
    setUseRecovery(false)
    setRestartReason(reason)
  }

  if (!challenge)
    return (
      <AuthShell title="로그인">
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault()
            submitLogin()
          }}
        >
          {state.expired && !notice && !restartReason && !login.error && (
            <Notice tone="warn">로그인이 만료됐어요. 다시 로그인해 주세요.</Notice>
          )}
          {notice && !restartReason && !login.error && <Notice tone="ok">{notice}</Notice>}
          {restartReason && <Notice tone="warn">{restartReason}</Notice>}
          <Field label="아이디" htmlFor="username">
            <input
              id="username"
              name="username"
              {...usernameInputProps}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className={inputCls}
            />
          </Field>
          <Field label="비밀번호" htmlFor="password">
            <input
              id="password"
              name="password"
              ref={passwordRef}
              type="password"
              autoComplete="current-password"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={inputCls}
            />
          </Field>
          <AuthErrorNotice error={login.error} />
          <Button
            type="submit"
            variant="primary"
            className="w-full"
            loading={login.isPending}
            disabled={!username.trim() || !password || loginWait > 0}
          >
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
          if (useRecovery) submitVerify({ challenge_id: challenge, recovery_code: recovery.trim() })
          else submitCode(code)
        }}
      >
        {useRecovery ? (
          <Field label="복구 코드" htmlFor="recovery" hint="대소문자와 하이픈(-)은 상관없어요.">
            <input
              id="recovery"
              name="recovery"
              autoFocus
              autoComplete="off"
              autoCapitalize="characters"
              autoCorrect="off"
              spellCheck={false}
              placeholder="XXXX-XXXX-XXXX-XXXX"
              maxLength={40}
              value={recovery}
              onChange={(e) => setRecovery(e.target.value)}
              className={`${inputCls} font-mono`}
            />
          </Field>
        ) : (
          <Field label="6자리 코드" htmlFor="otp">
            <CodeInput value={code} onChange={setCode} onComplete={submitCode} disabled={verify.isPending} autoFocus />
          </Field>
        )}
        <AuthErrorNotice error={verify.error}>
          {isApiError(verify.error, 'invalid_code') && !useRecovery && (
            <span className="mt-1 block text-xs">
              방금 쓴 코드는 다시 쓸 수 없어요. 인증 앱에 다음 코드가 나오면 그 코드를 입력하세요.
            </span>
          )}
        </AuthErrorNotice>
        <Button
          type="submit"
          variant="primary"
          className="w-full"
          loading={verify.isPending}
          disabled={(useRecovery ? !recovery.trim() : code.length !== 6) || verifyWait > 0}
        >
          로그인
        </Button>
        <div className="flex flex-col items-center gap-1 text-sm">
          <button
            type="button"
            className="min-h-11 text-accent underline"
            onClick={() => {
              verify.clearError()
              setUseRecovery(!useRecovery)
            }}
          >
            {useRecovery ? '인증 코드로 로그인' : '휴대폰을 쓸 수 없나요? 복구 코드로 로그인'}
          </button>
          <button type="button" className="min-h-11 text-muted" onClick={() => restart()}>
            처음으로
          </button>
        </div>
      </form>
    </AuthShell>
  )
}
