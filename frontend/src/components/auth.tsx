import { useState, type ReactNode } from 'react'
import { ApiError, errorMessage, formatWait } from '../api/http'
import type { TotpSetupInfo } from '../api/types'
import { useRetryCountdown } from '../hooks/useRetryCountdown'
import { cx, inputCls } from '../lib/styles'
import { IconCheck, IconCopy } from './Icons'
import { Button, Notice } from './ui'

/** 인증 화면 공통 틀 (가운데 카드) */
export function AuthShell({ title, subtitle, children }: { title: string; subtitle?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex min-h-dvh items-start justify-center bg-subtle px-safe-4 pt-safe pb-safe sm:items-center">
      <main className="my-8 w-full max-w-sm space-y-6 rounded-2xl border border-line bg-bg p-6 shadow-sm">
        <div className="space-y-1.5">
          <div className="text-sm font-semibold text-accent">스크랩</div>
          <h1 className="text-xl font-bold tracking-tight">{title}</h1>
          {subtitle && <p className="text-sm text-muted">{subtitle}</p>}
        </div>
        {children}
      </main>
    </div>
  )
}

/** 6자리 인증 코드 입력. 6자리가 되면 자동 제출 */
export function CodeInput({
  value,
  onChange,
  onComplete,
  id = 'otp',
  disabled,
  autoFocus,
}: {
  value: string
  onChange: (v: string) => void
  onComplete?: (v: string) => void
  id?: string
  disabled?: boolean
  autoFocus?: boolean
}) {
  return (
    <input
      id={id}
      name={id}
      value={value}
      disabled={disabled}
      autoFocus={autoFocus}
      onChange={(e) => {
        const v = e.target.value.replace(/\D/g, '').slice(0, 6)
        onChange(v)
        if (v.length === 6) onComplete?.(v)
      }}
      type="text"
      inputMode="numeric"
      autoComplete="one-time-code"
      autoCapitalize="off"
      autoCorrect="off"
      spellCheck={false}
      pattern="[0-9]*"
      maxLength={6}
      placeholder="000000"
      className={cx(inputCls, 'min-h-14 text-center font-mono text-2xl! tracking-[0.5em]')}
    />
  )
}

/** 서버가 준 QR은 data:image/ 형식일 때만 이미지로 쓴다 */
function isImageDataUrl(s: string): boolean {
  return /^data:image\/(png|svg\+xml|gif|jpeg);base64,[a-z0-9+/=]+$/i.test(s)
}

/** QR + 수동 입력용 비밀키 표시 */
export function TotpQr({ info }: { info: TotpSetupInfo }) {
  const [showSecret, setShowSecret] = useState(false)
  return (
    <div className="space-y-3">
      <ol className="list-decimal space-y-1 pl-5 text-sm text-fg">
        <li>휴대폰에서 Google Authenticator 같은 인증 앱을 엽니다.</li>
        <li>아래 QR 코드를 스캔합니다.</li>
        <li>앱에 표시된 6자리 코드를 입력합니다.</li>
      </ol>
      {isImageDataUrl(info.qr_data_url) && (
        <div className="flex justify-center">
          <img
            src={info.qr_data_url}
            alt="2차 인증 등록용 QR 코드"
            width={184}
            height={184}
            className="rounded-lg border border-line bg-white p-1"
          />
        </div>
      )}
      <div className="text-center">
        {showSecret ? (
          <code className="rounded bg-hover px-2 py-1 font-mono text-sm break-all select-all">{info.secret}</code>
        ) : (
          <button type="button" onClick={() => setShowSecret(true)} className="min-h-11 text-sm text-accent underline">
            QR을 스캔할 수 없나요? 키 직접 입력하기
          </button>
        )}
      </div>
    </div>
  )
}

/**
 * 복구 코드 10개 — 서버는 다시 보여 주지 않는다 (조회 API 없음).
 * "보관했어요" 확인 뒤에만 다음으로 넘어갈 수 있다. 가입 확정과 2차 인증 재설정이 함께 쓴다.
 */
export function RecoveryCodesStep({
  codes,
  doneLabel,
  onDone,
  doneLoading,
}: {
  codes: string[]
  doneLabel: string
  onDone: () => void
  doneLoading?: boolean
}) {
  const [copied, setCopied] = useState<'ok' | 'fail' | null>(null)
  const [saved, setSaved] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(codes.join('\n'))
      setCopied('ok')
    } catch {
      setCopied('fail')
    }
  }
  return (
    <div className="space-y-4">
      <Notice tone="warn">
        <strong className="font-semibold">이 코드는 지금 한 번만 보여요.</strong> 이 화면을 벗어나면 다시 볼 수 없어요.
        비밀번호 관리자 등 안전한 곳에 보관하세요.
      </Notice>
      <ul
        aria-label="복구 코드"
        className="grid grid-cols-1 gap-1.5 rounded-lg border border-line bg-subtle p-3 font-mono text-[15px] sm:grid-cols-2"
      >
        {codes.map((c) => (
          <li key={c} className="text-center whitespace-nowrap select-all">
            {c}
          </li>
        ))}
      </ul>
      <Button className="w-full" onClick={copy}>
        {copied === 'ok' ? <IconCheck size={18} className="text-ok" /> : <IconCopy size={18} />}
        {copied === 'ok' ? '복사했어요' : '복구 코드 모두 복사'}
      </Button>
      <p className="text-xs text-muted">
        복사한 내용은 클립보드와 기기 간 동기화에 남을 수 있어요. 비밀번호 관리자에 붙여넣은 뒤 다른 텍스트를 복사해 두세요.
      </p>
      {copied === 'fail' && (
        <p className="text-sm text-danger">복사하지 못했어요. 코드를 길게 눌러 직접 선택해 주세요.</p>
      )}
      <label className="flex min-h-11 items-center gap-3 text-sm">
        <input
          type="checkbox"
          checked={saved}
          onChange={(e) => setSaved(e.target.checked)}
          className="size-5 accent-[var(--c-accent-solid)]"
        />
        복구 코드를 안전한 곳에 보관했어요
      </label>
      <Button variant="primary" className="w-full" disabled={!saved} loading={doneLoading} onClick={onDone}>
        {doneLabel}
      </Button>
    </div>
  )
}

/** 인증 화면 오류 안내. 429는 Retry-After 기준으로 남은 시간을 센다 */
export function AuthErrorNotice({ error, children }: { error: unknown; children?: ReactNode }) {
  const wait = useRetryCountdown(error)
  if (!error) return null
  const is429 = error instanceof ApiError && error.status === 429
  return (
    <Notice tone="danger">
      {is429 ? (
        <>
          {error.message}
          {wait > 0 ? ` ${formatWait(wait)} 뒤에 다시 시도할 수 있어요.` : ' 이제 다시 시도할 수 있어요.'}
        </>
      ) : (
        errorMessage(error)
      )}
      {children}
    </Notice>
  )
}

export function Steps({ current, labels }: { current: number; labels: string[] }) {
  return (
    <ol className="flex gap-1.5" aria-label="진행 단계">
      {labels.map((l, i) => (
        <li key={l} className="flex-1" aria-current={i === current ? 'step' : undefined}>
          <div className={cx('h-1 rounded-full', i <= current ? 'bg-accent-solid' : 'bg-line')} />
          <div className={cx('mt-1 text-[11px]', i === current ? 'font-medium text-fg' : 'text-muted')}>{l}</div>
        </li>
      ))}
    </ol>
  )
}
