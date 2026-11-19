import { useSyncExternalStore } from 'react'
import { dismissToast, toastStore } from '../lib/toast'
import { cx } from '../lib/styles'
import { IconAlert, IconClose } from './Icons'

/** 화면 아래쪽 짧은 안내. 모바일은 탭바 위, 데스크톱은 아래 가운데 */
export function Toaster() {
  const items = useSyncExternalStore(toastStore.subscribe, toastStore.getSnapshot)
  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed inset-x-0 bottom-toast z-50 flex flex-col items-center gap-2 px-safe-4 md:bottom-6"
    >
      {items.map((t) => (
        <div
          key={t.id}
          role={t.tone === 'danger' ? 'alert' : 'status'}
          className={cx(
            'pointer-events-auto flex max-w-sm items-center gap-2 rounded-xl py-1 pr-1 pl-3.5 text-sm shadow-lg shadow-black/20',
            'bg-fg text-bg',
          )}
        >
          {t.tone === 'danger' && <IconAlert size={16} className="shrink-0" />}
          <span className="py-2">{t.message}</span>
          <button
            type="button"
            aria-label="닫기"
            onClick={() => dismissToast(t.id)}
            className="inline-flex size-11 shrink-0 items-center justify-center rounded-lg opacity-70 hover:opacity-100"
          >
            <IconClose size={16} />
          </button>
        </div>
      ))}
    </div>
  )
}
