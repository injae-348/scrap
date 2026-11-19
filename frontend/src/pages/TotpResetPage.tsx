import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'
import { authApi } from '../api'
import { errorMessage } from '../api/http'
import { CodeInput, MockHint, RecoveryCodes, Steps, TotpQr } from '../components/auth'
import { IconBack } from '../components/Icons'
import { Button, Field, Notice } from '../components/ui'
import { inputCls } from '../lib/styles'

/** 설정 > 2차 인증 재설정 (현재 비밀번호·코드 확인 → 새 QR 등록 → 새 복구 코드) */
export function TotpResetPage() {
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [newCode, setNewCode] = useState('')
  const start = useMutation({ mutationFn: authApi.totpReset })
  const verify = useMutation({ mutationFn: authApi.totpResetVerify })
  const step = verify.data ? 2 : start.data ? 1 : 0

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
              start.mutate({ password, code })
            }}
          >
            <Notice tone="warn">재설정을 마치면 지금 쓰는 인증 앱 코드와 기존 복구 코드는 더 이상 쓸 수 없어요.</Notice>
            <Field label="현재 비밀번호" htmlFor="cur-pw">
              <input
                id="cur-pw"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className={inputCls}
              />
            </Field>
            <Field label="지금 인증 앱의 6자리 코드" htmlFor="cur-code">
              <CodeInput id="cur-code" value={code} onChange={setCode} />
            </Field>
            {start.isError && <Notice tone="danger">{errorMessage(start.error)}</Notice>}
            <MockHint>아무 비밀번호, 아무 6자리 (000000은 실패)</MockHint>
            <Button type="submit" variant="primary" className="w-full" loading={start.isPending} disabled={code.length !== 6}>
              다음
            </Button>
          </form>
        )}

        {step === 1 && start.data && (
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault()
              verify.mutate({ code: newCode })
            }}
          >
            <TotpQr info={start.data} />
            <Field label="새로 등록한 앱의 6자리 코드" htmlFor="new-code">
              <CodeInput id="new-code" value={newCode} onChange={setNewCode} onComplete={(v) => verify.mutate({ code: v })} />
            </Field>
            {verify.isError && <Notice tone="danger">{errorMessage(verify.error)}</Notice>}
            <Button type="submit" variant="primary" className="w-full" loading={verify.isPending} disabled={newCode.length !== 6}>
              확인
            </Button>
          </form>
        )}

        {step === 2 && verify.data && (
          <div className="space-y-4">
            <Notice tone="ok">2차 인증을 다시 등록했어요. 새 복구 코드를 안전한 곳에 보관하세요.</Notice>
            <RecoveryCodes codes={verify.data.recovery_codes} />
            <Link
              to="/settings"
              className="flex min-h-11 w-full items-center justify-center rounded-lg bg-accent-solid text-sm font-medium text-on-accent"
            >
              완료
            </Link>
          </div>
        )}
      </div>
    </div>
  )
}
