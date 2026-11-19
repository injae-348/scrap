import { Link, Navigate, Outlet, useLocation } from 'react-router'
import { useAuthStatus } from '../hooks/queries'
import { BottomTabBar } from './BottomTabBar'
import { IconPlus } from './Icons'
import { Sidebar } from './Sidebar'
import { Spinner } from './ui'

/** 로그인 후 화면의 공통 틀: 사이드바(md~) / 하단 탭바 + 떠 있는 "+"(~767px) */
export function AppLayout() {
  const status = useAuthStatus()
  const { pathname } = useLocation()

  if (status.isPending)
    return (
      <div className="flex min-h-dvh items-center justify-center text-muted">
        <Spinner className="size-6" />
      </div>
    )
  if (status.data?.setup_required) return <Navigate to="/setup" replace />
  if (status.data && !status.data.logged_in) return <Navigate to="/login" replace />

  // 상세·편집은 모바일에서 전체 화면 페이지로 연다 → 탭바와 "+" 숨김
  const fullScreen = pathname.includes('/scraps/') || pathname.startsWith('/settings/')
  // "+" 저장 버튼은 목록 화면(전체·좋아요·마감 임박)에서만 띄운다
  const showFab = !fullScreen && !pathname.startsWith('/settings') && !pathname.startsWith('/search')

  return (
    <div className="min-h-dvh px-safe md:flex">
      <Sidebar />
      <main className={fullScreen ? 'min-w-0 flex-1' : 'min-w-0 flex-1 pb-tabbar md:pb-0'}>
        <Outlet />
      </main>
      {showFab && (
        <Link
            to="/scraps/new"
            aria-label="새 스크랩 저장"
            className="fixed right-4 bottom-fab z-30 flex size-14 items-center justify-center rounded-full bg-accent-solid text-on-accent shadow-lg shadow-black/20 active:scale-95 md:hidden"
          >
          <IconPlus size={26} />
        </Link>
      )}
      {!fullScreen && <BottomTabBar />}
    </div>
  )
}
