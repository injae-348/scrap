import { useEffect, useState } from 'react'
import { registerSW } from 'virtual:pwa-register'
import { bypassAllLeaveGuards, hasActiveLeaveGuard } from '../lib/leaveGuards'
import { Button, LeaveDialog } from './ui'

/**
 * 서비스워커 등록 + 새 버전 안내.
 * 자동으로 새로고침하지 않는다 (작성 중인 내용을 지키기 위해). 새 버전이 있으면 안내를 띄우고,
 * 사용자가 "새로고침"을 눌렀을 때만 바꾼다. 작성 중(이탈 가드가 켜진 상태)이면 앱의 확인 창을 먼저 띄운다
 * (iOS 홈 화면 앱은 브라우저 이탈 확인이 뜨지 않을 수 있어서 브라우저 확인에 기대지 않는다).
 */
// StrictMode에서 effect가 두 번 돌아도 한 번만 등록한다
let registered = false

export function UpdatePrompt() {
  const [update, setUpdate] = useState<((reload?: boolean) => Promise<void>) | null>(null)
  const [dismissed, setDismissed] = useState(false)
  const [confirming, setConfirming] = useState(false)

  const apply = () => {
    if (!update) return
    bypassAllLeaveGuards()
    void update(true)
  }
  const onRefresh = () => {
    if (hasActiveLeaveGuard()) setConfirming(true)
    else apply()
  }

  useEffect(() => {
    if (registered) return
    registered = true
    const updateSW = registerSW({
      onNeedRefresh() {
        setDismissed(false)
        setUpdate(() => updateSW)
      },
      onRegisteredSW(_url, registration) {
        // 오래 켜 둔 홈 화면 앱도 새 버전을 알 수 있게 1시간마다 확인한다
        if (registration) setInterval(() => void registration.update(), 60 * 60 * 1000)
      },
    })
  }, [])

  if (!update || dismissed) return null
  if (confirming)
    return (
      <LeaveDialog
        open
        title="작성 중인 내용이 있어요"
        message="새로고침하면 저장하지 않은 내용이 사라져요. 저장한 뒤 새로고침하는 것을 권해요."
        stayLabel="계속 작성"
        leaveLabel="새로고침"
        onStay={() => setConfirming(false)}
        onLeave={apply}
      />
    )
  return (
    <div className="pointer-events-none fixed inset-x-0 top-0 z-[70] flex justify-center px-safe-4 pt-[max(0.75rem,env(safe-area-inset-top))]">
      <div
        role="status"
        className="pointer-events-auto flex max-w-sm items-center gap-2 rounded-xl bg-fg py-1 pr-1 pl-3.5 text-sm text-bg shadow-lg shadow-black/20"
      >
        <span className="py-2">새 버전이 있어요.</span>
        <Button variant="primary" onClick={onRefresh}>
          새로고침
        </Button>
        <Button variant="ghost" className="text-bg! hover:bg-white/10" onClick={() => setDismissed(true)}>
          나중에
        </Button>
      </div>
    </div>
  )
}
