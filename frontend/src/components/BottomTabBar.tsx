import { NavLink, useLocation } from 'react-router'
import { cx } from '../lib/styles'
import { IconHeart, IconList, IconSettings, IconSparkles } from './Icons'

const tabs = [
  { to: '/', label: '전체', icon: IconList, match: (p: string) => p === '/' || p.startsWith('/due') || p.startsWith('/scraps') },
  { to: '/liked', label: '좋아요', icon: IconHeart, match: (p: string) => p.startsWith('/liked') },
  { to: '/search', label: 'AI 검색', icon: IconSparkles, match: (p: string) => p.startsWith('/search') },
  { to: '/settings', label: '설정', icon: IconSettings, match: (p: string) => p.startsWith('/settings') },
]

/** 모바일(~767px) 하단 탭바 */
export function BottomTabBar() {
  const { pathname } = useLocation()
  return (
    <nav
      aria-label="하단 메뉴"
      className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-bg/95 pb-safe px-safe backdrop-blur md:hidden"
    >
      <ul className="grid h-14 grid-cols-4">
        {tabs.map(({ to, label, icon: Icon, match }) => {
          const active = match(pathname)
          return (
            <li key={to}>
              <NavLink
                to={to}
                aria-current={active ? 'page' : undefined}
                className={cx(
                  'flex h-full flex-col items-center justify-center gap-0.5 text-[11px]',
                  active ? 'font-semibold text-accent' : 'text-muted',
                )}
              >
                {Icon === IconHeart ? <IconHeart size={22} filled={active} /> : <Icon size={22} />}
                {label}
              </NavLink>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
