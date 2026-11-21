import { useCallback, useEffect, useRef } from 'react'
import { useBlocker, type Blocker } from 'react-router'
import { registerLeaveGuard } from '../lib/leaveGuards'

/**
 * 작성 중 이탈 경고.
 * - 앱 안 이동(링크·뒤로 가기·로그인 만료로 인한 이동): react-router blocker → 확인 대화상자(LeaveDialog)
 * - 새로고침·탭 닫기·외부 이동: beforeunload (브라우저 기본 확인 창)
 *
 * 저장 성공 직후처럼 의도한 이동은 allowLeave()를 먼저 부른다.
 */
export function useLeaveGuard(when: boolean): { blocker: Blocker; allowLeave: () => void } {
  const whenRef = useRef(when)
  const bypassRef = useRef(false)
  useEffect(() => {
    whenRef.current = when
    if (when) bypassRef.current = false
  }, [when])

  const blocker = useBlocker(
    useCallback(
      ({ currentLocation, nextLocation }) =>
        whenRef.current &&
        !bypassRef.current &&
        (currentLocation.pathname !== nextLocation.pathname || currentLocation.search !== nextLocation.search),
      [],
    ),
  )

  // 새로고침 안내(UpdatePrompt) 같은 라우터 밖 동작도 작성 중인지 알 수 있게 등록한다
  useEffect(() => {
    if (!when) return
    return registerLeaveGuard({
      bypass: () => {
        bypassRef.current = true
      },
    })
  }, [when])

  useEffect(() => {
    if (!when) return
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (bypassRef.current) return
      e.preventDefault()
      // 일부 브라우저는 returnValue가 있어야 확인 창을 띄운다
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [when])

  const allowLeave = useCallback(() => {
    bypassRef.current = true
  }, [])

  return { blocker, allowLeave }
}
