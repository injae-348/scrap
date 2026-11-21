import { NavLink } from 'react-router'
import type { ScrapListItem as ScrapListItemData } from '../api/types'
import { relativeTime } from '../lib/date'
import { cx } from '../lib/styles'
import { hostOf } from '../lib/url'
import { DueBadge } from './DueBadge'
import { LikeButton } from './LikeButton'
import { displayText } from '../lib/text'

/** 메모 미리보기는 마크다운을 렌더링하지 않고 기호만 덜어 낸 평문으로 보여 준다 */
function plainPreview(md: string): string {
  return md
    .replace(/```[\s\S]*?(```|$)/g, ' ')
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/^\s{0,3}(#{1,6}|>|[-*+]|\d+[.)])\s+/gm, '')
    .replace(/[*_`~]+/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

export function ScrapListItem({ scrap, to }: { scrap: ScrapListItemData; to: string }) {
  const preview = scrap.memo_preview ? displayText(plainPreview(scrap.memo_preview)) : ''
  const host = hostOf(scrap.url)
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
        <div className="line-clamp-2 font-medium leading-snug break-words text-fg">{displayText(scrap.title) || '(제목 없음)'}</div>
        {preview && <p className="mt-1 line-clamp-2 text-sm break-words text-muted">{preview}</p>}
        <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
          <span className="font-medium text-fg/80">{displayText(scrap.source.name)}</span>
          {host && (
            <>
              <span aria-hidden="true">·</span>
              <span className="max-w-[12rem] truncate">{host}</span>
            </>
          )}
          <span aria-hidden="true">·</span>
          <span>{relativeTime(scrap.created_at)}</span>
          <DueBadge due={scrap.due_date} />
        </div>
        {scrap.topics.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {scrap.topics.map((t) => (
              <span key={t.id} className="text-xs text-accent">
                #{displayText(t.name)}
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
