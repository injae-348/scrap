import type { ReactNode } from 'react'
import { useLocation, useOutlet } from 'react-router'
import { cx } from '../lib/styles'
import { IconInbox } from './Icons'

export interface PanelContext {
  /** 목록 경로 (예: '', '/liked', '/search') — 상세 경로는 `${base}/scraps/${id}` */
  base: string
  /** 목록 필터 쿼리 문자열 ('?source=1' 등). 상세에서 목록으로 돌아갈 때 유지 */
  search: string
}

/**
 * 목록 + 상세/편집 패널.
 * - 데스크톱(1024px~): 가운데 목록 + 오른쪽 패널
 * - 그 아래: 패널이 열리면 목록 대신 전체 화면으로 표시
 */
export function SplitPane({ list, context }: { list: ReactNode; context: PanelContext }) {
  const outlet = useOutlet(context)
  const { pathname } = useLocation()
  const panelOpen = !!outlet && pathname.includes('/scraps/')

  return (
    <div className="lg:flex lg:h-dvh">
      <section
        aria-label="목록"
        className={cx(
          'lg:w-[400px] lg:shrink-0 lg:overflow-y-auto lg:border-r lg:border-line xl:w-[460px]',
          panelOpen && 'hidden lg:block',
        )}
      >
        {list}
      </section>
      <section
        aria-label="상세"
        className={cx('min-w-0 flex-1 lg:overflow-y-auto', !panelOpen && 'hidden lg:block')}
      >
        {panelOpen ? (
          outlet
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-muted">
            <IconInbox size={36} />
            <p className="text-sm">목록에서 스크랩을 선택하세요</p>
          </div>
        )}
      </section>
    </div>
  )
}
