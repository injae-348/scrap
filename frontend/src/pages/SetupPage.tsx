import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { authApi } from '../api'
import { errorMessage } from '../api/http'
import { AuthShell, CodeInput, MockHint, RecoveryCodes, Steps, TotpQr } from '../components/auth'
import { Button, Field, Notice } from '../components/ui'
import { keys } from '../hooks/queries'
import { inputCls } from '../lib/styles'

/**
 * 최초 가입 + 2차 인증 등록 + 복구 코드.
 * 실제 앱에서는 사용자가 0명일 때만 열린다 (목 단계에서는 주소로 바로 볼 수 있음).
 */
export function SetupPage() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [password2, setPassword2] = useState('')
  const [code, setCode] = useState('')
  const [saved, setSaved] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)

  const setup = useMutation({ mutationFn: authApi.setup })
  const verify = useMutation({ mutationFn: authApi.setupVerify })
  const step = verify.data ? 2 : setup.data ? 1 : 0

  const submitVerify = (c: string) => {
    if (c.length === 6 && !verify.isPending) verify.mutate({ code: c })
  }

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

      {step === 0 && (
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault()
            if (password !== password2) {
              setLocalError('비밀번호가 서로 달라요.')
              return
            }
            setLocalError(null)
            setup.mutate({ username: username.trim(), password })
          }}
        >
          <Field label="아이디" htmlFor="username">
            <input
              id="username"
              autoComplete="username"
              autoCapitalize="off"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className={inputCls}
            />
          </Field>
          <Field label="비밀번호" htmlFor="password" hint="10자 이상. 비밀번호 관리자로 생성하는 것을 권장해요.">
            <input
              id="password"
              type="password"
              autoComplete="new-password"
              required
              minLength={10}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={inputCls}
            />
          </Field>
          <Field label="비밀번호 확인" htmlFor="password2">
            <input
              id="password2"
              type="password"
              autoComplete="new-password"
              required
              value={password2}
              onChange={(e) => setPassword2(e.target.value)}
              className={inputCls}
            />
          </Field>
          {(localError || setup.isError) && <Notice tone="danger">{localError ?? errorMessage(setup.error)}</Notice>}
          <MockHint>아무 아이디, 10자 이상 비밀번호</MockHint>
          <Button type="submit" variant="primary" className="w-full" loading={setup.isPending} disabled={!username.trim() || !password}>
            다음
          </Button>
        </form>
      )}

      {step === 1 && setup.data && (
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault()
            submitVerify(code)
          }}
        >
          <TotpQr info={setup.data} />
          <Field label="6자리 코드" htmlFor="otp">
            <CodeInput value={code} onChange={setCode} onComplete={submitVerify} disabled={verify.isPending} />
          </Field>
          {verify.isError && <Notice tone="danger">{errorMessage(verify.error)}</Notice>}
          <MockHint>아무 6자리 (000000은 실패)</MockHint>
          <Button type="submit" variant="primary" className="w-full" loading={verify.isPending} disabled={code.length !== 6}>
            확인
          </Button>
        </form>
      )}

      {step === 2 && verify.data && (
        <div className="space-y-4">
          <RecoveryCodes codes={verify.data.recovery_codes} />
          <Notice tone="warn">이 화면을 닫으면 복구 코드를 다시 볼 수 없어요.</Notice>
          <label className="flex min-h-11 items-center gap-3 text-sm">
            <input
              type="checkbox"
              checked={saved}
              onChange={(e) => setSaved(e.target.checked)}
              className="size-5 accent-[var(--c-accent-solid)]"
            />
            복구 코드를 안전한 곳에 보관했어요
          </label>
          <Button
            variant="primary"
            className="w-full"
            disabled={!saved}
            onClick={async () => {
              await qc.invalidateQueries({ queryKey: keys.authStatus })
              navigate('/', { replace: true })
            }}
          >
            시작하기
          </Button>
        </div>
      )}
    </AuthShell>
  )
}
