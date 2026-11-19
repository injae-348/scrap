import { NavLink } from 'react-router'
import type { Scrap } from '../api/types'
import { relativeTime } from '../lib/date'
import { cx } from '../lib/styles'
import { hostOf } from '../lib/url'
import { DueBadge } from './DueBadge'
import { LikeButton } from './LikeButton'

export function ScrapListItem({ scrap, to }: { scrap: Scrap; to: string }) {
  return (
    <li className="relative">
      <NavLink
        to={to}
        className={({ isActive }) =>
          cx(
            'block py-3 pr-14 pl-4 transition hover:bg-hover lg:pl-5',
            isActive && 'bg-accent-soft hover:bg-accent-soft',
          )
        }
      >
        <div className="line-clamp-2 font-medium leading-snug text-fg">{scrap.title || '(제목 없음)'}</div>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
          <span className="font-medium text-fg/80">{scrap.source.name}</span>
          <span aria-hidden="true">·</span>
          <span className="max-w-[12rem] truncate">{hostOf(scrap.url)}</span>
          <span aria-hidden="true">·</span>
          <span>{relativeTime(scrap.created_at)}</span>
          <DueBadge due={scrap.due_date} />
        </div>
        {scrap.topics.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {scrap.topics.map((t) => (
              <span key={t.id} className="text-xs text-accent">
                #{t.name}
              </span>
            ))}
          </div>
        )}
      </NavLink>
      <div className="absolute top-1.5 right-1.5">
        <LikeButton scrap={scrap} />
      </div>
    </li>
  )
}
