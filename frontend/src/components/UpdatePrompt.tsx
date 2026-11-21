import { useEffect, useState } from 'react'
import { registerSW } from 'virtual:pwa-register'
import { bypassAllLeaveGuards, hasActiveLeaveGuard } from '../lib/leaveGuards'
import { createUpdateController, type UpdateView } from '../lib/updateFlow'
import { Button, LeaveDialog } from './ui'

/**
 * 서비스워커 등록 + 새 버전 안내 (흐름은 lib/updateFlow.ts).
 * 자동으로 새로고침하지 않는다. 사용자가 "새로고침"을 눌렀을 때만 바꾸고, 작성 중이면 앱의 확인 창을 먼저 띄운다
 * (iOS 홈 화면 앱은 브라우저 이탈 확인이 뜨지 않을 수 있어서 브라우저 확인에 기대지 않는다).
 */
type Controller = ReturnType<typeof createUpdateController>

// StrictMode에서 effect가 두 번 돌아도 한 번만 등록한다
let controller: Controller | null = null
let registration: ServiceWorkerRegistration | null = null
let setViewGlobal: ((v: UpdateView) => void) | null = null

export function UpdatePrompt() {
  const [view, setView] = useState<UpdateView>('hidden')

  useEffect(() => {
    setViewGlobal = setView
    if (!controller) {
      const c = createUpdateController(
        {
          hasActiveGuard: hasActiveLeaveGuard,
          bypassGuards: bypassAllLeaveGuards,
          reload: () => window.location.reload(),
          getRegistration: () => registration,
        },
        (v) => setViewGlobal?.(v),
      )
      controller = c
      const updateSW = registerSW({
        onNeedRefresh: () => c.onNeedRefresh(),
        onNeedReload: () => c.onNeedReload(),
        onRegisteredSW(_url, reg) {
          registration = reg ?? null
          // 오래 켜 둔 홈 화면 앱도 새 버전을 알 수 있게 1시간마다 확인한다
          if (reg) setInterval(() => void reg.update(), 60 * 60 * 1000)
        },
      })
      c.setApplyUpdate(() => updateSW(false))
    }
  }, [])

  const c = controller
  if (!c || view === 'hidden') return null
  if (view === 'confirm')
    return (
      <LeaveDialog
        open
        title="작성 중인 내용이 있어요"
        message="새로고침하면 저장하지 않은 내용이 사라져요. 저장한 뒤 새로고침하는 것을 권해요."
        stayLabel="계속 작성"
        leaveLabel="새로고침"
        onStay={() => c.cancel()}
        onLeave={() => c.confirm()}
      />
    )
  return (
    <div className="pointer-events-none fixed inset-x-0 top-0 z-[70] flex justify-center px-safe-4 pt-[max(0.75rem,env(safe-area-inset-top))]">
      <div
        role="status"
        className="pointer-events-auto flex max-w-sm items-center gap-2 rounded-xl bg-fg py-1 pr-1 pl-3.5 text-sm text-bg shadow-lg shadow-black/20"
      >
        <span className="py-2">새 버전이 있어요.</span>
        <Button variant="primary" onClick={() => c.requestRefresh()}>
          새로고침
        </Button>
        <Button variant="ghost" className="text-bg! hover:bg-white/10" onClick={() => c.dismiss()}>
          나중에
        </Button>
      </div>
    </div>
  )
}
