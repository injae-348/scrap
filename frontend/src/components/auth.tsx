import { useState, type ReactNode } from 'react'
import type { TotpSetupInfo } from '../api/types'
import { cx, inputCls } from '../lib/styles'
import { IconCheck, IconCopy } from './Icons'
import { Button } from './ui'

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
}: {
  value: string
  onChange: (v: string) => void
  onComplete?: (v: string) => void
  id?: string
  disabled?: boolean
}) {
  return (
    <input
      id={id}
      value={value}
      disabled={disabled}
      onChange={(e) => {
        const v = e.target.value.replace(/\D/g, '').slice(0, 6)
        onChange(v)
        if (v.length === 6) onComplete?.(v)
      }}
      inputMode="numeric"
      autoComplete="one-time-code"
      pattern="\d{6}"
      maxLength={6}
      placeholder="000000"
      aria-label="6자리 인증 코드"
      className={cx(inputCls, 'min-h-14 text-center font-mono text-2xl! tracking-[0.5em]')}
    />
  )
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
      <div className="flex justify-center">
        <img
          src={info.qr_data_url}
          alt="2차 인증 등록용 QR 코드"
          width={184}
          height={184}
          className="rounded-lg border border-line bg-white"
        />
      </div>
      <p className="text-center text-xs text-muted">목 데이터: 모양만 있는 가짜 QR이라 스캔되지 않아요.</p>
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

/** 복구 코드 10개 표시 + 복사 */
export function RecoveryCodes({ codes }: { codes: string[] }) {
  const [copied, setCopied] = useState<'ok' | 'fail' | null>(null)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(codes.join('\n'))
      setCopied('ok')
    } catch {
      setCopied('fail')
    }
  }
  return (
    <div className="space-y-3">
      <ul className="grid grid-cols-2 gap-2 rounded-lg border border-line bg-subtle p-3 font-mono text-[15px]">
        {codes.map((c) => (
          <li key={c} className="text-center select-all">
            {c}
          </li>
        ))}
      </ul>
      <Button className="w-full" onClick={copy}>
        {copied === 'ok' ? <IconCheck size={18} className="text-ok" /> : <IconCopy size={18} />}
        {copied === 'ok' ? '복사했어요' : '복구 코드 모두 복사'}
      </Button>
      {copied === 'fail' && (
        <p className="text-sm text-danger">복사하지 못했어요. 코드를 길게 눌러 직접 선택해 주세요.</p>
      )}
    </div>
  )
}

export function MockHint({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-line px-3 py-2 text-xs text-muted">
      <span className="font-semibold">목 모드</span> · {children}
    </div>
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
