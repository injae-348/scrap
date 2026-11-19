import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router'

export type View = 'all' | 'liked' | 'due'

export interface BrowseFilters {
  q: string
  sourceId: number | undefined
  topicIds: number[]
  sort: 'created' | 'due'
  /** 마감 임박 보기에서 '지난 마감' 탭 */
  past: boolean
}

/** 목록 필터는 URL 쿼리에 둔다 (새로고침·뒤로가기·링크 공유에도 유지) */
export function useBrowseParams() {
  const [sp, setSp] = useSearchParams()

  const filters = useMemo<BrowseFilters>(() => {
    const source = Number(sp.get('source'))
    return {
      q: sp.get('q') ?? '',
      sourceId: Number.isFinite(source) && source > 0 ? source : undefined,
      topicIds: (sp.get('topics') ?? '')
        .split(',')
        .map(Number)
        .filter((n) => Number.isFinite(n) && n > 0),
      sort: sp.get('sort') === 'due' ? 'due' : 'created',
      past: sp.get('past') === '1',
    }
  }, [sp])

  const update = useCallback(
    (patch: Partial<BrowseFilters>) => {
      setSp(
        (prev) => {
          const next = new URLSearchParams(prev)
          const set = (k: string, v: string | undefined) => (v ? next.set(k, v) : next.delete(k))
          if ('q' in patch) set('q', patch.q || undefined)
          if ('sourceId' in patch) set('source', patch.sourceId ? String(patch.sourceId) : undefined)
          if ('topicIds' in patch) set('topics', patch.topicIds?.length ? patch.topicIds.join(',') : undefined)
          if ('sort' in patch) set('sort', patch.sort === 'due' ? 'due' : undefined)
          if ('past' in patch) set('past', patch.past ? '1' : undefined)
          return next
        },
        { replace: true },
      )
    },
    [setSp],
  )

  return { filters, update, search: sp.toString() ? '?' + sp.toString() : '' }
}

export const VIEW_BASE: Record<View, string> = { all: '', liked: '/liked', due: '/due' }
export const VIEW_TITLE: Record<View, string> = { all: '전체', liked: '좋아요', due: '마감 임박' }
