import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { authApi } from '../api'
import type { TotpSetupInfo } from '../api/types'
import { isApiError } from '../api/http'
import { AuthErrorNotice, CodeInput, RecoveryCodesStep, Steps, TotpQr } from '../components/auth'
import { IconBack } from '../components/Icons'
import { Button, Field, LeaveDialog, Notice } from '../components/ui'
import { keys } from '../hooks/queries'
import { useLeaveGuard } from '../hooks/useLeaveGuard'
import { useAuthMutation } from '../hooks/useAuthMutation'
import { useRetryCountdown } from '../hooks/useRetryCountdown'
import { inputCls } from '../lib/styles'

/** 설정 > 2차 인증 재설정 (현재 비밀번호·코드 확인 → 새 QR 등록 → 새 복구 코드) */
export function TotpResetPage() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [newCode, setNewCode] = useState('')
  const [restartReason, setRestartReason] = useState<string | null>(null)

  // 비밀번호·코드와 새 TOTP 비밀값·복구 코드는 뮤테이션 캐시에 남기지 않는다.
  // 다음 단계에 필요한 결과만 컴포넌트 상태로 옮긴다.
  const start = useAuthMutation(authApi.totpReset)
  const verify = useAuthMutation(authApi.totpResetVerify)
  const [totpInfo, setTotpInfo] = useState<TotpSetupInfo | null>(null)
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null)
  const startWait = useRetryCountdown(start.error)
  const step = recoveryCodes ? 2 : totpInfo ? 1 : 0
  const { blocker, allowLeave } = useLeaveGuard(step > 0)

  // 페이지를 떠나면(뒤로·앞으로 캐시에 들어갈 때 포함) 화면에 들고 있던 비밀값·복구 코드를 지운다
  useEffect(() => {
    const clear = () => {
      setTotpInfo(null)
      setRecoveryCodes(null)
    }
    window.addEventListener('pagehide', clear)
    return () => window.removeEventListener('pagehide', clear)
  }, [])

  const submitStart = () => {
    if (startWait > 0) return
    start.mutate(
      { password, code },
      {
        onSuccess: (info) => {
          setTotpInfo(info)
          setPassword('')
          setCode('')
          setRestartReason(null)
        },
        onError: (e) => {
          if (isApiError(e, 'invalid_code')) setCode('')
          if (isApiError(e, 'invalid_credentials')) setPassword('')
        },
      },
    )
  }

  const submitNew = (c: string) => {
    if (c.length !== 6 || verify.isPending) return
    verify.mutate(
      { code: c },
      {
        onSuccess: (res) => {
          setTotpInfo(null)
          setRecoveryCodes(res.recovery_codes)
          // 다른 기기는 서버에서 모두 로그아웃됐다
          void qc.invalidateQueries({ queryKey: keys.sessions })
        },
        onError: (e) => {
          if (isApiError(e, 'totp_reset_expired')) {
            setTotpInfo(null)
            setNewCode('')
            setRestartReason(
              '재설정 시간이 지났어요. 처음부터 다시 진행해 주세요. 인증 앱에 새로 추가한 항목은 지우고, 지금 쓰던 코드로 다시 시작하세요.',
            )
          } else if (isApiError(e, 'invalid_code')) setNewCode('')
        },
      },
    )
  }

  return (
    <div className="lg:h-dvh lg:overflow-y-auto">
      <header className="sticky top-0 z-20 border-b border-line bg-bg/95 pt-safe backdrop-blur">
        <div className="mx-auto flex min-h-14 max-w-lg items-center gap-1 px-1.5 lg:px-4">
          <Link to="/settings" className="inline-flex min-h-11 items-center gap-0.5 rounded-lg pr-2 pl-1 text-accent hover:bg-hover">
            <IconBack size={22} />
            설정
          </Link>
          <h1 className="flex-1 text-center text-sm font-semibold lg:text-left">2차 인증 재설정</h1>
          <span className="w-16" />
        </div>
      </header>

      <div className="mx-auto max-w-lg space-y-6 px-4 py-6 pb-safe lg:px-8">
        <Steps current={step} labels={['본인 확인', '새 앱 등록', '복구 코드']} />

        {step === 0 && (
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault()
              submitStart()
            }}
          >
            {restartReason && <Notice tone="warn">{restartReason}</Notice>}
            <Notice tone="warn">
              재설정을 마치면 지금 쓰는 인증 앱 코드와 기존 복구 코드는 더 이상 쓸 수 없고, 이 기기를 뺀 다른 기기는 모두
              로그아웃돼요.
            </Notice>
            <Field label="현재 비밀번호" htmlFor="cur-pw">
              <input
                id="cur-pw"
                name="password"
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
            <Field label="지금 인증 앱의 6자리 코드" htmlFor="cur-code">
              <CodeInput id="cur-code" value={code} onChange={setCode} />
            </Field>
            <AuthErrorNotice error={start.error} />
            <Button
              type="submit"
              variant="primary"
              className="w-full"
              loading={start.isPending}
              disabled={!password || code.length !== 6 || startWait > 0}
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
              submitNew(newCode)
            }}
          >
            <TotpQr info={totpInfo} />
            <Field label="새로 등록한 앱의 6자리 코드" htmlFor="new-code">
              <CodeInput id="new-code" value={newCode} onChange={setNewCode} onComplete={submitNew} disabled={verify.isPending} />
            </Field>
            <AuthErrorNotice error={verify.error} />
            <p className="text-xs text-muted">새 코드를 확인하기 전까지는 지금 쓰는 인증 앱과 복구 코드가 그대로 유효해요.</p>
            <Button type="submit" variant="primary" className="w-full" loading={verify.isPending} disabled={newCode.length !== 6}>
              확인
            </Button>
          </form>
        )}

        {step === 2 && recoveryCodes && (
          <div className="space-y-4">
            <Notice tone="ok">
              2차 인증을 다시 등록했어요. 다른 기기는 모두 로그아웃됐습니다. 새 복구 코드를 안전한 곳에 보관하세요.
            </Notice>
            <RecoveryCodesStep
              codes={recoveryCodes}
              doneLabel="완료"
              onDone={() => {
                allowLeave()
                setRecoveryCodes(null)
                navigate('/settings', { replace: true })
              }}
            />
          </div>
        )}
      </div>

      <LeaveDialog
        open={blocker.state === 'blocked'}
        title={step === 2 ? '복구 코드를 보관했나요?' : '재설정을 그만둘까요?'}
        message={
          step === 2
            ? '이 화면을 나가면 새 복구 코드를 다시 볼 수 없어요.'
            : '아직 새 코드를 확인하지 않았으니 지금 쓰는 인증 앱이 그대로 유효해요. 새로 추가한 항목은 지워 주세요.'
        }
        stayLabel="머무르기"
        onStay={() => blocker.reset?.()}
        onLeave={() => blocker.proceed?.()}
      />
    </div>
  )
}
