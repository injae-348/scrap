import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Navigate, useNavigate } from 'react-router'
import { authApi } from '../api'
import type { TotpSetupInfo } from '../api/types'
import { errorMessage, isApiError } from '../api/http'
import { AuthErrorNotice, AuthShell, CodeInput, RecoveryCodesStep, Steps, TotpQr } from '../components/auth'
import { Button, ErrorState, Field, LeaveDialog, Notice, Spinner } from '../components/ui'
import { clearPrivateCache, keys, useAuthStatus } from '../hooks/queries'
import { useLeaveGuard } from '../hooks/useLeaveGuard'
import { useAuthMutation } from '../hooks/useAuthMutation'
import { useRetryCountdown } from '../hooks/useRetryCountdown'
import { usernameInputProps } from '../lib/authInputs'
import { cx, inputCls } from '../lib/styles'

/** 최초 가입 화면. 확정된 사용자가 0명일 때만 열린다 */
export function SetupPage() {
  const status = useAuthStatus()
  // 가입을 시작한 뒤에는 상태가 바뀌어도(가입 확정 → 로그인 상태) 복구 코드 화면까지 이어서 보여 준다
  const [started, setStarted] = useState(false)

  if (!started) {
    if (status.isPending)
      return (
        <div className="flex min-h-dvh items-center justify-center text-muted">
          <Spinner className="size-6" />
        </div>
      )
    if (status.isError)
      return (
        <AuthShell title="계정 만들기">
          <ErrorState message={`서버 상태를 확인하지 못했어요. ${errorMessage(status.error)}`} onRetry={() => status.refetch()} />
        </AuthShell>
      )
    if (!status.data.setup_required) return <Navigate to={status.data.logged_in ? '/' : '/login'} replace />
  }
  return <SetupFlow onStart={() => setStarted(true)} />
}

const PASSWORD_MIN = 10

/**
 * 최초 가입 + 2차 인증 등록 + 복구 코드.
 * 1) 아이디·비밀번호·가입 토큰 → QR (서버는 가입 대기 정보를 이 브라우저 쿠키에 10분 묶는다)
 * 2) 6자리 코드 확인 → 가입 확정 + 로그인 + 복구 코드 10개 (한 번만 표시)
 */
function SetupFlow({ onStart }: { onStart: () => void }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [password2, setPassword2] = useState('')
  const [setupToken, setSetupToken] = useState('')
  const [code, setCode] = useState('')
  const [localError, setLocalError] = useState<string | null>(null)
  const [restartReason, setRestartReason] = useState<string | null>(null)

  // 비밀번호·가입 토큰·코드와 서버가 준 TOTP 비밀값·복구 코드는 뮤테이션 캐시에 남기지 않는다.
  // 다음 단계에 필요한 결과(QR·비밀값, 복구 코드)만 컴포넌트 상태로 옮긴다.
  const setup = useAuthMutation(authApi.setup)
  const verify = useAuthMutation(authApi.setupVerify)
  const [totpInfo, setTotpInfo] = useState<TotpSetupInfo | null>(null)
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null)
  const setupWait = useRetryCountdown(setup.error)
  const verifyWait = useRetryCountdown(verify.error)
  const step = recoveryCodes ? 2 : totpInfo ? 1 : 0

  // 페이지를 떠나면(뒤로·앞으로 캐시에 들어갈 때 포함) 화면에 들고 있던 비밀값·복구 코드를 지운다
  useEffect(() => {
    const clear = () => {
      setTotpInfo(null)
      setRecoveryCodes(null)
    }
    window.addEventListener('pagehide', clear)
    return () => window.removeEventListener('pagehide', clear)
  }, [])

  const submitSetup = (body: { username: string; password: string; setup_token: string }) => {
    setup.mutate(body, {
      onSuccess: (info) => {
        onStart()
        setTotpInfo(info)
        // 입력칸의 가입 토큰과 비밀번호도 비운다
        setSetupToken('')
        setPassword('')
        setPassword2('')
        setRestartReason(null)
      },
      onError: (e) => {
        if (isApiError(e, 'invalid_setup_token')) setSetupToken('')
        if (isApiError(e, 'setup_disabled')) void qc.invalidateQueries({ queryKey: keys.authStatus })
      },
    })
  }

  const submitVerify = (c: string) => {
    if (c.length !== 6 || verify.isPending || verifyWait > 0) return
    verify.mutate(
      { code: c },
      {
        onSuccess: (res) => {
          setTotpInfo(null)
          setRecoveryCodes(res.recovery_codes)
        },
        onError: (e) => {
          if (isApiError(e, 'setup_expired')) {
            setTotpInfo(null)
            setCode('')
            setRestartReason(
              '가입 시간(10분)이 지났거나 코드를 여러 번 틀렸어요. 처음부터 다시 진행해 주세요. 인증 앱에 이미 추가한 항목은 지우고 새 QR로 다시 등록하세요.',
            )
          } else if (isApiError(e, 'invalid_code')) setCode('')
          else if (isApiError(e, 'setup_disabled')) void qc.invalidateQueries({ queryKey: keys.authStatus })
        },
      },
    )
  }

  // QR 단계·복구 코드 단계에서 나가면(새로고침 포함) 진행 중인 가입이나 복구 코드를 잃는다
  const { blocker, allowLeave } = useLeaveGuard(step > 0)

  const finish = async () => {
    allowLeave()
    setRecoveryCodes(null)
    clearPrivateCache(qc)
    await qc.invalidateQueries({ queryKey: keys.authStatus })
    navigate('/', { replace: true })
  }

  const tokenError = isApiError(setup.error, 'invalid_setup_token')
  const notConfigured = isApiError(setup.error, 'setup_token_not_configured')
  const disabled = isApiError(setup.error, 'setup_disabled') || isApiError(verify.error, 'setup_disabled')

  return (
    <AuthShell
      title={['계정 만들기', '2차 인증 등록', '복구 코드 보관'][step]}
      subtitle={
        step === 0
          ? '처음 한 번만 만들 수 있어요. 가입 후에는 새 계정을 만들 수 없어요.'
          : step === 1
            ? '로그인할 때마다 인증 앱의 6자리 코드가 필요해요.'
            : '휴대폰을 잃어버렸을 때 이 코드로 로그인할 수 있어요. 각 코드는 한 번만 쓸 수 있어요.'
      }
    >
      <Steps current={step} labels={['계정', '2차 인증', '복구 코드']} />

      {disabled && (
        <Notice tone="warn">
          이미 가입이 끝났어요.{' '}
          <button type="button" className="min-h-11 font-medium text-accent underline" onClick={() => navigate('/login', { replace: true })}>
            로그인 화면으로
          </button>
        </Notice>
      )}

      {step === 0 && (
        <form
          className="space-y-4"
          autoComplete="on"
          onSubmit={(e) => {
            e.preventDefault()
            const u = username.trim()
            if (!u) return setLocalError('아이디를 입력해 주세요.')
            if (u.length > 64) return setLocalError('아이디는 64자 이하로 입력해 주세요.')
            if (password.length < PASSWORD_MIN) return setLocalError(`비밀번호는 ${PASSWORD_MIN}자 이상이어야 해요.`)
            if (password !== password2) return setLocalError('비밀번호가 서로 달라요.')
            if (!setupToken.trim()) return setLocalError('가입 토큰을 입력해 주세요.')
            setLocalError(null)
            submitSetup({ username: u, password, setup_token: setupToken.trim() })
          }}
        >
          {restartReason && <Notice tone="warn">{restartReason}</Notice>}
          <Field label="아이디" htmlFor="username" hint="대소문자를 구분해요.">
            <input
              id="username"
              name="username"
              {...usernameInputProps}
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className={inputCls}
            />
          </Field>
          <Field label="비밀번호" htmlFor="new-password" hint={`${PASSWORD_MIN}자 이상. 비밀번호 관리자로 생성하는 것을 권장해요.`}>
            <input
              id="new-password"
              name="new-password"
              type="password"
              autoComplete="new-password"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              required
              minLength={PASSWORD_MIN}
              maxLength={1024}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={inputCls}
            />
          </Field>
          <Field label="비밀번호 확인" htmlFor="new-password2">
            <input
              id="new-password2"
              name="new-password2"
              type="password"
              autoComplete="new-password"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              required
              maxLength={1024}
              value={password2}
              onChange={(e) => setPassword2(e.target.value)}
              className={inputCls}
            />
          </Field>
          <Field
            label="가입 토큰"
            htmlFor="setup-token"
            hint="서버 설정 파일에 적어 둔 가입 토큰 값이에요. 이 화면에서만 쓰고 저장하지 않아요."
          >
            {/* 비밀번호 관리자가 저장·자동완성하지 않게: autocomplete off + 관리자별 무시 속성, name도 password가 아니게 */}
            <input
              id="setup-token"
              name="setup-token"
              type="password"
              autoComplete="off"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              data-1p-ignore="true"
              data-lpignore="true"
              data-bwignore="true"
              data-form-type="other"
              required
              value={setupToken}
              onChange={(e) => setSetupToken(e.target.value)}
              aria-invalid={tokenError || undefined}
              aria-describedby={tokenError ? 'setup-token-error' : undefined}
              className={cx(inputCls, 'font-mono', tokenError && 'border-danger')}
            />
          </Field>
          {tokenError && (
            <p id="setup-token-error" className="text-sm text-danger">
              {errorMessage(setup.error)} 다시 입력해 주세요.
            </p>
          )}
          {localError && <Notice tone="danger">{localError}</Notice>}
          {notConfigured ? (
            <Notice tone="warn">
              서버에 가입 토큰이 설정되어 있지 않아요. 서버 관리자가 가입 토큰을 설정하고 앱을 다시 시작한 뒤에 가입할 수 있어요.
            </Notice>
          ) : (
            !tokenError && !disabled && <AuthErrorNotice error={setup.error} />
          )}
          <Button
            type="submit"
            variant="primary"
            className="w-full"
            loading={setup.isPending}
            disabled={!username.trim() || !password || setupWait > 0}
          >
            다음
          </Button>
        </form>
      )}

      {step === 1 && totpInfo && (
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault()
            submitVerify(code)
          }}
        >
          <TotpQr info={totpInfo} />
          <Field label="6자리 코드" htmlFor="otp">
            <CodeInput value={code} onChange={setCode} onComplete={submitVerify} disabled={verify.isPending} />
          </Field>
          {!disabled && <AuthErrorNotice error={verify.error} />}
          <p className="text-xs text-muted">
            10분 안에 확인을 마쳐 주세요. 새로고침하거나 화면을 나가면 처음부터 다시 해야 하고, 그때는 새 QR을 다시 등록해야
            해요.
          </p>
          <Button
            type="submit"
            variant="primary"
            className="w-full"
            loading={verify.isPending}
            disabled={code.length !== 6 || verifyWait > 0}
          >
            확인
          </Button>
        </form>
      )}

      {step === 2 && recoveryCodes && (
        <RecoveryCodesStep codes={recoveryCodes} doneLabel="시작하기" onDone={finish} />
      )}

      <LeaveDialog
        open={blocker.state === 'blocked'}
        title={verify.isPending ? '코드를 확인하는 중이에요' : step === 2 ? '복구 코드를 보관했나요?' : '가입을 그만둘까요?'}
        message={
          verify.isPending
            ? '확인이 끝나면 새 복구 코드가 한 번만 표시돼요. 끝날 때까지 이 화면에 머물러 주세요.'
            : step === 2
            ? '이 화면을 나가면 복구 코드를 다시 볼 수 없어요.'
            : '나가면 처음부터 다시 해야 하고, 인증 앱에 등록한 항목은 쓸 수 없게 돼요.'
        }
        stayLabel="머무르기"
        onStay={() => blocker.reset?.()}
        // 확인 요청이 진행 중이면 나가지 못하게 한다 (끝나면 복구 코드 단계로 넘어간다)
        onLeave={verify.isPending ? undefined : () => blocker.proceed?.()}
      />
    </AuthShell>
  )
}
