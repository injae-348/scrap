import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { aiApi } from '../api'
import { errorMessage } from '../api/http'
import { DueBadge } from '../components/DueBadge'
import { IconSparkles } from '../components/Icons'
import { SplitPane } from '../components/SplitPane'
import { Button, EmptyState, ErrorState, Spinner } from '../components/ui'
import { cx, inputCls } from '../lib/styles'
import { hostOf } from '../lib/url'
import { displayText } from '../lib/text'

const EXAMPLES = ['마감 임박한 공모전 찾아줘', '도커 관련 정리 글', '보안 공부 자료 모아줘', '집에서 해 먹을 요리']

/** AI 검색: 질문 → 로딩 → 결과 카드(스크랩 + 이유). 데스크톱에서는 결과 옆에 상세 패널 */
export function SearchPage() {
  const [sp] = useSearchParams()
  const search = sp.toString() ? '?' + sp.toString() : ''
  return <SplitPane list={<SearchPane />} context={{ base: '/search', search }} />
}

function SearchPane() {
  const [sp, setSp] = useSearchParams()
  const query = sp.get('q') ?? ''
  const [input, setInput] = useState(query)

  // 질문은 URL에 두어 상세를 봤다가 돌아와도 결과가 유지되게 한다 (결과는 캐시)
  const result = useQuery({
    queryKey: ['ai', 'search', query],
    queryFn: () => aiApi.search({ query }),
    enabled: query.length > 0,
    staleTime: Infinity,
    retry: false,
  })

  const ask = (q: string) => {
    const t = q.trim()
    if (!t) return
    setInput(t)
    setSp(t ? { q: t } : {})
  }

  return (
    <div>
      <header className="sticky top-0 z-20 border-b border-line bg-bg/95 pt-safe backdrop-blur">
        <div className="px-4 pt-3 lg:px-5">
          <h1 className="flex items-center gap-2 text-xl font-bold tracking-tight">
            <IconSparkles size={20} className="text-accent" />
            AI 검색
          </h1>
        </div>
        <form
          role="search"
          className="flex gap-2 px-4 py-3 lg:px-5"
          onSubmit={(e) => {
            e.preventDefault()
            ask(input)
          }}
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="예: 이번 달 마감인 공모전 찾아줘"
            aria-label="AI에게 질문"
            enterKeyHint="search"
            className={cx(inputCls, 'flex-1')}
          />
          <Button type="submit" variant="primary" disabled={!input.trim()} loading={result.isFetching}>
            {result.isFetching ? '' : '검색'}
          </Button>
        </form>
      </header>

      {!query ? (
        <div className="space-y-3 px-4 py-6 lg:px-5">
          <p className="text-sm text-muted">저장한 스크랩에서 AI가 관련 있는 것을 찾아 이유와 함께 보여 줘요.</p>
          <div className="flex flex-wrap gap-2">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                type="button"
                onClick={() => ask(ex)}
                className="min-h-11 rounded-full border border-line px-3.5 text-sm text-fg hover:bg-hover lg:min-h-9"
              >
                {ex}
              </button>
            ))}
          </div>
        </div>
      ) : result.isFetching ? (
        <div className="space-y-4 px-4 py-6 lg:px-5" aria-live="polite">
          <p className="flex items-center gap-2 text-sm text-muted">
            <Spinner />
            AI가 비슷한 표현까지 여러 번 검색하고 있어요…
          </p>
          {[0, 1, 2].map((i) => (
            <div key={i} className="animate-pulse space-y-2 rounded-xl border border-line p-4">
              <div className="h-4 w-2/3 rounded bg-hover" />
              <div className="h-3 w-1/3 rounded bg-hover" />
              <div className="h-10 rounded bg-hover" />
            </div>
          ))}
        </div>
      ) : result.isError ? (
        <ErrorState message={errorMessage(result.error)} onRetry={() => result.refetch()} />
      ) : result.data ? (
        <div className="space-y-4 px-4 py-5 lg:px-5" aria-live="polite">
          <p className="text-sm leading-relaxed text-fg">{displayText(result.data.answer)}</p>
          {result.data.results.length === 0 ? (
            <EmptyState title="관련 스크랩이 없어요" description="다른 표현으로 다시 물어봐 주세요." />
          ) : (
            <ul className="space-y-3">
              {result.data.results.map(({ scrap, reason }) => (
                <li key={scrap.id}>
                  <Link
                    to={`/search/scraps/${scrap.id}?q=${encodeURIComponent(query)}`}
                    className="block rounded-xl border border-line p-4 transition hover:bg-hover"
                  >
                    <div className="font-medium leading-snug">{displayText(scrap.title)}</div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-muted">
                      <span className="font-medium text-fg/80">{displayText(scrap.source.name)}</span>
                      <span>{hostOf(scrap.url)}</span>
                      <DueBadge due={scrap.due_date} />
                      {scrap.topics.map((t) => (
                        <span key={t.id} className="text-accent">
                          #{displayText(t.name)}
                        </span>
                      ))}
                    </div>
                    <p className="mt-3 flex gap-1.5 rounded-lg bg-accent-soft px-3 py-2 text-sm text-fg">
                      <IconSparkles size={15} className="mt-0.5 shrink-0 text-accent" />
                      <span>{displayText(reason)}</span>
                    </p>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  )
}
