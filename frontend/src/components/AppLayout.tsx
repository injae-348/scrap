import { useEffect } from 'react'
import { Link, Navigate, Outlet, useLocation, useNavigate } from 'react-router'
import { errorMessage } from '../api/http'
import { useAuthStatus } from '../hooks/queries'
import { BottomTabBar } from './BottomTabBar'
import { IconPlus } from './Icons'
import { Sidebar } from './Sidebar'
import { Toaster } from './Toaster'
import { showToast } from '../lib/toast'
import { keepsScreenOnExpiry } from '../lib/routes'
import { Button, ErrorState, Spinner } from './ui'

/** 로그인 후 화면의 공통 틀: 사이드바(md~) / 하단 탭바 + 떠 있는 "+"(~767px) */
export function AppLayout() {
  const status = useAuthStatus()
  const location = useLocation()
  const navigate = useNavigate()
  const { pathname } = location
  const expired = !!status.data && !status.data.logged_in && !!status.data.expired
  const expiredSeq = status.data?.expiredSeq ?? 0
  const keepScreen = keepsScreenOnExpiry(pathname)

  // 사용 중 세션이 만료되면(401 unauthorized) 로그인 화면으로 보낸다.
  // 편집 화면에 작성 중인 내용이 있으면 이탈 경고가 먼저 뜬다. "머무르기"를 고르면 편집 폼만 남기고,
  // 그 뒤 다른 화면으로 옮기거나(경로 변경) 다시 401을 받으면(expiredSeq 증가) 또 로그인 화면으로 보낸다.
  useEffect(() => {
    if (expired) navigate('/login', { replace: true, state: { from: location.pathname + location.search, expired: true } })
    // location.search는 일부러 빼둔다: 만료·경로 변경·새 401 때만 이동을 시도한다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expired, expiredSeq, pathname, navigate])

  // 받아 둔 상태가 있는데 다시 확인만 실패했으면 화면을 유지하고 짧게 알린다
  const refreshFailed = status.isError && !!status.data
  useEffect(() => {
    if (refreshFailed) showToast('서버 상태를 다시 확인하지 못했어요. 연결을 확인해 주세요.', 'danger')
  }, [refreshFailed])

  if (status.isPending)
    return (
      <div className="flex min-h-dvh items-center justify-center text-muted">
        <Spinner className="size-6" />
      </div>
    )
  if (status.isError && !status.data)
    return (
      <div className="flex min-h-dvh items-center justify-center px-safe-4 pt-safe pb-safe">
        <ErrorState
          message={`서버 상태를 확인하지 못했어요. ${errorMessage(status.error)}`}
          onRetry={() => status.refetch()}
        />
      </div>
    )
  const data = status.data!
  if (data.setup_required) return <Navigate to="/setup" replace />
  if (!data.logged_in && !expired) return <Navigate to="/login" replace state={{ from: pathname + location.search }} />

  // 상세·편집은 모바일에서 전체 화면 페이지로 연다 → 탭바와 "+" 숨김
  const fullScreen = pathname.includes('/scraps/') || pathname.startsWith('/settings/')
  // "+" 저장 버튼은 목록 화면(전체·좋아요·마감 임박)에서만 띄운다
  const showFab = !fullScreen && !pathname.startsWith('/settings') && !pathname.startsWith('/search')

  // 만료 상태에서는 편집 폼(과 2차 인증 재설정 화면)만 남긴다 (사이드바·탭바·목록 등 다른 데이터는 그리지 않는다).
  // 요소 구조(자리)는 그대로 두어 편집 폼이 다시 마운트되지 않게 한다 (작성 중인 내용 유지).
  return (
    <div className="min-h-dvh px-safe md:flex">
      {!expired && <Sidebar />}
      <main className={fullScreen || expired ? 'min-w-0 flex-1' : 'min-w-0 flex-1 pb-tabbar md:pb-0'}>
        {expired && (
          <div
            role="alert"
            className="sticky top-0 z-40 flex flex-wrap items-center gap-2 border-b border-warn/30 bg-warn-soft px-4 pt-safe pb-2 text-sm"
          >
            <span className="min-w-0 flex-1 py-2">
              로그인이 만료됐어요. 작성 중인 내용을 복사해 둔 뒤 다시 로그인해 주세요.
            </span>
            <Button
              variant="primary"
              onClick={() => navigate('/login', { replace: true, state: { from: pathname, expired: true } })}
            >
              로그인
            </Button>
          </div>
        )}
        {(!expired || keepScreen) && <Outlet />}
      </main>
      {showFab && !expired && (
        <Link
          to="/scraps/new"
          aria-label="새 스크랩 저장"
          className="fixed right-[max(1rem,env(safe-area-inset-right))] bottom-fab z-30 flex size-14 items-center justify-center rounded-full bg-accent-solid text-on-accent shadow-lg shadow-black/20 active:scale-95 md:hidden"
        >
          <IconPlus size={26} />
        </Link>
      )}
      {!fullScreen && !expired && <BottomTabBar />}
      <Toaster />
    </div>
  )
}
