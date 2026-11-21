import { Link, useNavigate, useOutletContext, useParams } from 'react-router'
import { errorMessage } from '../api/http'
import { DueBadge } from '../components/DueBadge'
import { IconExternal, IconPencil, IconTrash } from '../components/Icons'
import { LikeButton } from '../components/LikeButton'
import { Markdown } from '../components/Markdown'
import { PanelHeader } from '../components/PanelHeader'
import type { PanelContext } from '../components/SplitPane'
import { ConfirmButton, EmptyState, ErrorState, Notice, Spinner } from '../components/ui'
import { useDeleteScrap, useScrap } from '../hooks/queries'
import { formatDate, formatDateTime } from '../lib/date'
import { showToast } from '../lib/toast'
import { safeHref } from '../lib/url'
import { DisplayUrl } from '../components/DisplayUrl'
import { isApiError } from '../api/http'
import { displayText } from '../lib/text'

export function ScrapDetailPage() {
  const { id } = useParams()
  const { base, search } = useOutletContext<PanelContext>()
  const navigate = useNavigate()
  const scrapId = Number(id)
  const q = useScrap(scrapId)
  const del = useDeleteScrap()
  const listPath = `${base || '/'}${search}`
  // 주제 링크는 목록 화면으로 (AI 검색에서 연 경우에도 전체 목록)
  const topicBase = base === '/search' ? '/' : base || '/'

  if (q.isPending)
    return (
      <>
        <PanelHeader backTo={listPath} />
        <div className="flex justify-center py-16 text-muted">
          <Spinner className="size-6" />
        </div>
      </>
    )
  // 받아 둔 내용이 없을 때만 오류 화면. 있으면 그대로 보여 주고 위에 한 줄로 알린다
  if (q.isError && !q.data)
    return (
      <>
        <PanelHeader backTo={listPath} />
        {isApiError(q.error, 'not_found', 'invalid_input') ? (
          <EmptyState
            title="스크랩을 찾을 수 없어요"
            description="삭제됐거나 주소가 잘못됐어요."
            action={
              <Link to={listPath} className="inline-flex min-h-11 items-center rounded-lg border border-line px-4 text-sm hover:bg-hover">
                목록으로
              </Link>
            }
          />
        ) : (
          <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />
        )}
      </>
    )

  const s = q.data
  const href = safeHref(s.url)

  return (
    <article>
      <PanelHeader
        backTo={listPath}
        actions={
          <>
            <LikeButton scrap={s} />
            <Link
              to={`${base}/scraps/${s.id}/edit${search}`}
              className="inline-flex min-h-11 items-center gap-1.5 rounded-lg px-3 text-sm font-medium hover:bg-hover"
            >
              <IconPencil size={18} />
              수정
            </Link>
          </>
        }
      />

      {q.isError && (
        <div role="alert" className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line bg-warn-soft px-4 py-1.5 text-sm lg:px-8">
          <span className="min-w-0 flex-1">최신 내용을 불러오지 못했어요. {errorMessage(q.error)}</span>
          <button type="button" className="min-h-11 font-medium text-accent underline" onClick={() => void q.refetch()}>
            다시 시도
          </button>
        </div>
      )}
      <div className="mx-auto max-w-2xl space-y-6 px-4 py-5 pb-safe lg:px-8 lg:py-8">
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted">
            <span className="rounded bg-hover px-1.5 py-0.5 text-xs font-medium text-fg">{displayText(s.source.name)}</span>
          </div>
          <h1 className="text-2xl leading-snug font-bold tracking-tight break-words">{displayText(s.title) || '(제목 없음)'}</h1>
          {s.topics.length > 0 && (
            <ul className="flex flex-wrap gap-1.5" aria-label="주제">
              {s.topics.map((t) => (
                <li key={t.id}>
                  <Link
                    to={`${topicBase}?topics=${t.id}`}
                    className="inline-flex min-h-11 items-center rounded-full bg-accent-soft px-3 text-sm text-accent lg:min-h-8 lg:px-2.5"
                  >
                    #{displayText(t.name)}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>

        {href ? (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="flex min-h-12 items-center gap-3 rounded-lg border border-line px-4 hover:bg-hover"
          >
            <IconExternal size={18} className="shrink-0 text-accent" />
            <DisplayUrl url={s.url} className="min-w-0 flex-1 truncate text-sm" />
            <span className="shrink-0 text-sm font-medium text-accent">열기</span>
          </a>
        ) : (
          <Notice tone="warn">
            열 수 없는 링크 형식이에요: <DisplayUrl url={s.url} />
          </Notice>
        )}

        {s.due_date && (
          <div className="flex items-center gap-2 text-sm">
            <span className="text-muted">마감일</span>
            <span className="font-medium">{formatDate(s.due_date)}</span>
            <DueBadge due={s.due_date} />
          </div>
        )}

        <section aria-label="메모" className="border-t border-line pt-5">
          {s.memo.trim() ? <Markdown>{s.memo}</Markdown> : <p className="text-sm text-muted">메모가 없습니다.</p>}
        </section>

        <footer className="space-y-4 border-t border-line pt-5 text-xs text-muted">
          <div>
            저장 {formatDateTime(s.created_at)}
            {s.updated_at !== s.created_at && <> · 수정 {formatDateTime(s.updated_at)}</>}
          </div>
          {del.isError && <Notice tone="danger">{errorMessage(del.error)}</Notice>}
          <ConfirmButton
            label="삭제"
            confirmLabel="정말 삭제"
            icon={<IconTrash size={18} />}
            loading={del.isPending}
            onConfirm={() =>
              del.mutate(s.id, {
                onSuccess: () => {
                  showToast('삭제했어요.')
                  navigate(listPath, { replace: true })
                },
              })
            }
          />
        </footer>
      </div>
    </article>
  )
}
