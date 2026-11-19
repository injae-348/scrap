import { useState } from 'react'
import { Link } from 'react-router'
import { errorMessage } from '../api/http'
import { IconClock, IconPlus, IconSearch } from '../components/Icons'
import { ScrapListItem } from '../components/ScrapListItem'
import { SplitPane } from '../components/SplitPane'
import { Button, Chip, EmptyState, ErrorState, ListSkeleton } from '../components/ui'
import { useScrapList, useSources, useTopics } from '../hooks/queries'
import { useBrowseParams, VIEW_BASE, VIEW_TITLE, type View } from '../hooks/useBrowseParams'
import { cx, inputCls } from '../lib/styles'

/** 목록 화면 (전체 / 좋아요 / 마감 임박). 데스크톱에서는 오른쪽에 상세·편집 패널이 붙는다. */
export function BrowsePage({ view }: { view: View }) {
  const { search } = useBrowseParams()
  const base = VIEW_BASE[view]
  return <SplitPane list={<ListPane view={view} />} context={{ base, search }} />
}

function ListPane({ view }: { view: View }) {
  const { filters, update, search } = useBrowseParams()
  const sources = useSources()
  const topics = useTopics()
  const base = VIEW_BASE[view]
  // 마감 임박 보기는 항상 마감순
  const sort = view === 'due' ? 'due' : filters.sort

  const list = useScrapList({
    q: filters.q || undefined,
    source_id: filters.sourceId,
    topic_ids: filters.topicIds.length ? filters.topicIds : undefined,
    liked: view === 'liked' || undefined,
    due: view === 'due' ? (filters.past ? 'past' : 'upcoming') : undefined,
    sort,
  })

  const items = list.data?.pages.flatMap((p) => p.items) ?? []
  const hasFilter = !!(filters.q || filters.sourceId || filters.topicIds.length)

  const toggleTopic = (id: number) =>
    update({
      topicIds: filters.topicIds.includes(id) ? filters.topicIds.filter((x) => x !== id) : [...filters.topicIds, id],
    })

  return (
    <div>
      <header className="sticky top-0 z-20 border-b border-line bg-bg/95 pt-safe backdrop-blur">
        <div className="flex items-center gap-2 px-4 pt-3 lg:px-5">
          <h1 className="flex-1 text-xl font-bold tracking-tight">{VIEW_TITLE[view]}</h1>
          {view === 'all' && (
            <Link
              to="/due"
              className="inline-flex min-h-11 items-center gap-1.5 rounded-lg px-2.5 text-sm text-muted hover:bg-hover md:hidden"
            >
              <IconClock size={16} />
              마감 임박
            </Link>
          )}
          {view !== 'due' && (
            <div role="group" aria-label="정렬" className="inline-flex rounded-lg border border-line p-0.5 text-sm">
              {(
                [
                  ['created', '최신순'],
                  ['due', '마감순'],
                ] as const
              ).map(([v, label]) => (
                <button
                  key={v}
                  type="button"
                  aria-pressed={filters.sort === v}
                  onClick={() => update({ sort: v })}
                  className={cx(
                    'min-h-11 rounded-md px-3 lg:min-h-8',
                    filters.sort === v ? 'bg-hover font-medium text-fg' : 'text-muted',
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
          )}
        </div>

        {view === 'due' && (
          <div role="group" aria-label="마감 구분" className="flex gap-2 px-4 pt-3 lg:px-5">
            <Chip active={!filters.past} onClick={() => update({ past: false })}>
              다가오는 마감 (7일 이내)
            </Chip>
            <Chip active={filters.past} onClick={() => update({ past: true })}>
              지난 마감
            </Chip>
          </div>
        )}

        <SearchBox key={filters.q} initial={filters.q} onSubmit={(q) => update({ q })} />

        <div className="flex gap-2 overflow-x-auto px-4 pb-2 [scrollbar-width:none] lg:px-5" role="group" aria-label="출처">
          <Chip active={!filters.sourceId} onClick={() => update({ sourceId: undefined })}>
            전체
          </Chip>
          {sources.data?.map((s) => (
            <Chip key={s.id} active={filters.sourceId === s.id} onClick={() => update({ sourceId: s.id })}>
              {s.name}
            </Chip>
          ))}
        </div>
        <div className="flex gap-2 overflow-x-auto px-4 pb-3 [scrollbar-width:none] lg:px-5" role="group" aria-label="주제 필터">
          {topics.data?.map((t) => (
            <Chip key={t.id} active={filters.topicIds.includes(t.id)} onClick={() => toggleTopic(t.id)}>
              #{t.name}
            </Chip>
          ))}
          {filters.topicIds.length > 0 && (
            <button
              type="button"
              onClick={() => update({ topicIds: [] })}
              className="min-h-11 shrink-0 px-2 text-sm text-accent lg:min-h-9"
            >
              주제 해제
            </button>
          )}
        </div>
      </header>

      {list.isPending ? (
        <ListSkeleton />
      ) : list.isError ? (
        <ErrorState message={errorMessage(list.error)} onRetry={() => list.refetch()} />
      ) : items.length === 0 ? (
        hasFilter ? (
          <EmptyState
            title="조건에 맞는 스크랩이 없어요"
            description="필터를 바꾸거나 해제해 보세요."
            action={
              <Button onClick={() => update({ q: '', sourceId: undefined, topicIds: [] })}>필터 모두 해제</Button>
            }
          />
        ) : view === 'liked' ? (
          <EmptyState title="좋아요한 스크랩이 없어요" description="스크랩의 하트를 누르면 여기에 모여요." />
        ) : view === 'due' ? (
          <EmptyState
            title={filters.past ? '지난 마감이 없어요' : '7일 안에 마감되는 스크랩이 없어요'}
            description="저장할 때 마감일을 넣으면 여기에서 볼 수 있어요."
          />
        ) : (
          <EmptyState
            title="아직 저장한 스크랩이 없어요"
            description="링크를 복사한 뒤 '새 스크랩'에서 붙여넣어 저장해 보세요."
            action={
              <Link
                to={`${base}/scraps/new`}
                className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-accent-solid px-4 text-sm font-medium text-on-accent"
              >
                <IconPlus size={18} />첫 스크랩 저장하기
              </Link>
            }
          />
        )
      ) : (
        <>
          <ul className="divide-y divide-line">
            {items.map((s) => (
              <ScrapListItem key={s.id} scrap={s} to={`${base}/scraps/${s.id}${search}`} />
            ))}
          </ul>
          {list.hasNextPage && (
            <div className="flex justify-center py-4">
              <Button onClick={() => list.fetchNextPage()} loading={list.isFetchingNextPage}>
                더 보기
              </Button>
            </div>
          )}
          {list.isFetchNextPageError && (
            <p role="alert" className="pb-4 text-center text-sm text-danger">
              더 불러오지 못했습니다.
            </p>
          )}
        </>
      )}
    </div>
  )
}

function SearchBox({ initial, onSubmit }: { initial: string; onSubmit: (q: string) => void }) {
  const [value, setValue] = useState(initial)
  return (
    <form
      role="search"
      className="px-4 pt-3 pb-2 lg:px-5"
      onSubmit={(e) => {
        e.preventDefault()
        onSubmit(value.trim())
      }}
    >
      <div className="relative">
        <IconSearch size={18} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-muted" />
        <input
          type="search"
          value={value}
          onChange={(e) => {
            setValue(e.target.value)
            if (e.target.value === '') onSubmit('')
          }}
          placeholder="제목·메모·링크에서 찾기"
          aria-label="스크랩 검색"
          enterKeyHint="search"
          className={cx(inputCls, 'pl-10 bg-subtle')}
        />
      </div>
    </form>
  )
}
