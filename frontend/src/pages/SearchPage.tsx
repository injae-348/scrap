import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { aiApi } from '../api'
import { AiErrorNotice, AiProgress } from '../components/AiStatus'
import { DueBadge } from '../components/DueBadge'
import { IconSparkles } from '../components/Icons'
import { SplitPane } from '../components/SplitPane'
import { Button, EmptyState } from '../components/ui'
import { cx, inputCls } from '../lib/styles'
import { hostOf } from '../lib/url'
import { displayText } from '../lib/text'

/** 질문 최대 길이 (서버: 앞뒤 공백 제거 후 1~200자) */
const QUERY_MAX = 200

const EXAMPLES = ['마감 임박한 공모전 찾아줘', '도커 관련 정리 글', '보안 공부 자료 모아줘', '집에서 해 먹을 요리']

const aiSearchKey = (query: string) => ['ai', 'search', query] as const

/** AI 검색: 질문 → 로딩(취소 가능) → 결과 카드(스크랩 + 이유). 데스크톱에서는 결과 옆에 상세 패널 */
export function SearchPage() {
  const [sp] = useSearchParams()
  const search = sp.toString() ? '?' + sp.toString() : ''
  return <SplitPane list={<SearchPane />} context={{ base: '/search', search }} />
}

function SearchPane() {
  const qc = useQueryClient()
  const [sp, setSp] = useSearchParams()
  const query = sp.get('q') ?? ''
  const [input, setInput] = useState(query)
  const [cancelled, setCancelled] = useState(false)
  /** 이 화면에서 사용자가 검색 버튼(예시 칩 포함)으로 보낸 질문. 이 질문만 서버로 보낸다 */
  const [askedQuery, setAskedQuery] = useState<string | null>(null)

  // 질문은 URL에 두어 상세를 봤다가 돌아와도 결과가 유지되게 한다 (결과는 캐시).
  // 새로고침·브라우저 복원·주소 직접 열기로 ?q=만 있는 경우에는 자동으로 보내지 않고 "이 질문으로 검색"을 거친다
  // (AI 호출은 수십 초·횟수 제한). 이미 받은 결과가 캐시에 있으면 그대로 보여 준다.
  // 수십 초(서버 상한 90초) 걸릴 수 있다. signal을 넘기므로 화면을 떠나면(쓰는 곳이 없어지면) 요청이 취소된다.
  // 실패해도 자동으로 다시 보내지 않는다.
  const hasCachedResult = qc.getQueryState(aiSearchKey(query))?.status === 'success'
  const result = useQuery({
    queryKey: aiSearchKey(query),
    queryFn: ({ signal }) => aiApi.search({ query }, signal),
    enabled: query.length > 0 && (askedQuery === query || hasCachedResult),
    staleTime: Infinity,
    retry: false,
    retryOnMount: false,
    refetchOnReconnect: false,
  })

  const ask = (q: string) => {
    const t = q.trim().slice(0, QUERY_MAX)
    if (!t) return
    setInput(t)
    setCancelled(false)
    setAskedQuery(t)
    // 같은 질문이 오류로 끝나 있었다면 다시 보낸다 (성공 결과는 다시 보내지 않고 그대로 쓴다)
    if (t === query && result.isError && askedQuery === t) void result.refetch()
    setSp({ q: t })
  }

  /** 진행 중인 검색 취소: 요청을 멈추고 질문 입력 상태로 돌아간다 (입력한 질문은 남김) */
  const cancel = () => {
    void qc.cancelQueries({ queryKey: aiSearchKey(query), exact: true })
    setCancelled(true)
    setSp({}, { replace: true })
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
            maxLength={QUERY_MAX}
            enterKeyHint="search"
            className={cx(inputCls, 'flex-1')}
          />
          <Button type="submit" variant="primary" disabled={!input.trim()} loading={result.isFetching} className="shrink-0">
            {result.isFetching ? '' : '검색'}
          </Button>
        </form>
      </header>

      {!query ? (
        <div className="space-y-3 px-4 py-6 lg:px-5">
          {cancelled && <p className="text-sm text-muted">검색을 취소했어요. 질문을 고쳐 다시 검색할 수 있어요.</p>}
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
        <div className="space-y-4 px-4 py-6 lg:px-5">
          <AiProgress
            label="AI가 비슷한 표현까지 여러 번 검색하고 있어요…"
            hint="1분 넘게 걸릴 수 있어요."
            cancelLabel="검색 취소"
            onCancel={cancel}
          />
          {[0, 1, 2].map((i) => (
            <div key={i} className="animate-pulse space-y-2 rounded-xl border border-line p-4">
              <div className="h-4 w-2/3 rounded bg-hover" />
              <div className="h-3 w-1/3 rounded bg-hover" />
              <div className="h-10 rounded bg-hover" />
            </div>
          ))}
        </div>
      ) : result.isError ? (
        <div className="px-4 py-6 lg:px-5">
          <AiErrorNotice error={result.error} op="search" onRetry={() => void result.refetch()} />
        </div>
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
                    <div className="font-medium leading-snug break-words">{displayText(scrap.title)}</div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-muted">
                      <span className="font-medium text-fg/80">{displayText(scrap.source.name)}</span>
                      <span className="max-w-full truncate">{hostOf(scrap.url)}</span>
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
      ) : (
        // 주소에 질문만 있고 아직 보내지 않은 상태 (새로고침·복원·주소 직접 열기)
        <div className="space-y-3 px-4 py-6 lg:px-5">
          <p className="text-sm break-words text-fg">
            ‘{displayText(query)}’ 질문으로 AI 검색을 할까요?
          </p>
          <p className="text-xs text-muted">AI 검색은 시간이 걸리고 사용 횟수에 들어가서, 눌렀을 때만 보내요.</p>
          <Button variant="primary" onClick={() => ask(query)}>
            <IconSparkles size={16} />이 질문으로 검색
          </Button>
        </div>
      )}
    </div>
  )
}
