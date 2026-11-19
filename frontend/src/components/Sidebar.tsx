import { Link, NavLink, useLocation, useSearchParams } from 'react-router'
import { useSources, useTopics } from '../hooks/queries'
import { cx } from '../lib/styles'
import { IconClock, IconHeart, IconList, IconPlus, IconSettings, IconSparkles } from './Icons'

function viewBase(pathname: string): string {
  if (pathname.startsWith('/liked')) return '/liked'
  if (pathname.startsWith('/due')) return '/due'
  return ''
}

const navCls = ({ isActive }: { isActive: boolean }) =>
  cx(
    'flex min-h-10 items-center gap-2.5 rounded-lg px-2.5 text-sm transition',
    isActive ? 'bg-accent-soft font-medium text-accent' : 'text-fg hover:bg-hover',
  )

function filterCls(active: boolean) {
  return cx(
    'flex min-h-9 items-center gap-2 rounded-lg px-2.5 text-sm transition',
    active ? 'bg-accent-soft font-medium text-accent' : 'text-muted hover:bg-hover hover:text-fg',
  )
}

/** 태블릿·데스크톱(768px~) 왼쪽 사이드바 */
export function Sidebar() {
  const { pathname } = useLocation()
  const [sp] = useSearchParams()
  const sources = useSources()
  const topics = useTopics()
  const base = viewBase(pathname)
  const inBrowse = !pathname.startsWith('/search') && !pathname.startsWith('/settings')
  const activeSource = inBrowse ? Number(sp.get('source')) : NaN
  const activeTopics = inBrowse ? (sp.get('topics') ?? '').split(',').map(Number) : []

  const filterLink = (key: 'source' | 'topics', id: number, active: boolean) => {
    const next = new URLSearchParams(inBrowse ? sp : undefined)
    if (active) next.delete(key)
    else next.set(key, String(id))
    const qs = next.toString()
    return `${base || '/'}${qs ? '?' + qs : ''}`
  }

  return (
    <aside className="hidden w-60 shrink-0 flex-col border-r border-line bg-subtle md:sticky md:top-0 md:flex md:h-dvh">
      <div className="pt-safe">
        <div className="flex items-center justify-between px-4 pt-4 pb-3">
          <Link to="/" className="text-lg font-bold tracking-tight">
            스크랩
          </Link>
        </div>
        <div className="px-3 pb-3">
          <Link
            to={`${base}/scraps/new`}
            className="flex min-h-11 items-center justify-center gap-2 rounded-lg bg-accent-solid text-sm font-medium text-on-accent hover:brightness-110"
          >
            <IconPlus size={18} />새 스크랩
          </Link>
        </div>
      </div>

      <nav aria-label="주요 메뉴" className="flex-1 space-y-6 overflow-y-auto px-3 pb-4">
        <div className="space-y-0.5">
          <NavLink to="/" className={() => navCls({ isActive: base === '' && inBrowse })}>
            <IconList size={18} />
            전체
          </NavLink>
          <NavLink to="/liked" className={navCls}>
            <IconHeart size={18} />
            좋아요
          </NavLink>
          <NavLink to="/due" className={navCls}>
            <IconClock size={18} />
            마감 임박
          </NavLink>
          <NavLink to="/search" className={navCls}>
            <IconSparkles size={18} />
            AI 검색
          </NavLink>
        </div>

        <section>
          <h2 className="px-2.5 pb-1 text-xs font-semibold text-muted">출처</h2>
          <ul className="space-y-0.5">
            {sources.data?.map((s) => {
              const active = activeSource === s.id
              return (
                <li key={s.id}>
                  <Link to={filterLink('source', s.id, active)} className={filterCls(active)} aria-current={active || undefined}>
                    {s.name}
                  </Link>
                </li>
              )
            })}
          </ul>
        </section>

        <section>
          <h2 className="px-2.5 pb-1 text-xs font-semibold text-muted">주제</h2>
          <ul className="space-y-0.5">
            {topics.data?.map((t) => {
              const active = activeTopics.includes(t.id)
              return (
                <li key={t.id}>
                  <Link to={filterLink('topics', t.id, active)} className={filterCls(active)} aria-current={active || undefined}>
                    <span className="text-muted">#</span>
                    {t.name}
                  </Link>
                </li>
              )
            })}
          </ul>
        </section>
      </nav>

      <div className="border-t border-line px-3 py-2 pb-safe">
        <NavLink to="/settings" className={navCls}>
          <IconSettings size={18} />
          설정
        </NavLink>
        <div className="h-2" />
      </div>
    </aside>
  )
}
