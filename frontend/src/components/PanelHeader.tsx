import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { IconBack, IconClose } from './Icons'

/** 상세·편집 상단 바. 모바일은 "뒤로", 데스크톱 패널은 "닫기"(X) */
export function PanelHeader({ backTo, title, actions }: { backTo: string; title?: string; actions?: ReactNode }) {
  return (
    <header className="sticky top-0 z-20 border-b border-line bg-bg/95 pt-safe backdrop-blur">
      <div className="flex min-h-14 items-center gap-1 px-1.5 lg:px-3">
        <Link
          to={backTo}
          aria-label="목록으로"
          className="inline-flex min-h-11 items-center gap-0.5 rounded-lg pr-2 pl-1 text-accent hover:bg-hover lg:hidden"
        >
          <IconBack size={22} />
          목록
        </Link>
        <Link
          to={backTo}
          aria-label="패널 닫기"
          className="hidden size-11 items-center justify-center rounded-lg text-muted hover:bg-hover lg:inline-flex"
        >
          <IconClose size={20} />
        </Link>
        <div className="min-w-0 flex-1 truncate text-center text-sm font-semibold lg:text-left">{title}</div>
        <div className="flex items-center gap-1">{actions}</div>
      </div>
    </header>
  )
}
