import { Link, useNavigate, useOutletContext, useParams } from 'react-router'
import { errorMessage } from '../api/http'
import { DueBadge } from '../components/DueBadge'
import { IconExternal, IconPencil, IconTrash } from '../components/Icons'
import { LikeButton } from '../components/LikeButton'
import { Markdown } from '../components/Markdown'
import { PanelHeader } from '../components/PanelHeader'
import type { PanelContext } from '../components/SplitPane'
import { ConfirmButton, ErrorState, Notice, Spinner } from '../components/ui'
import { useDeleteScrap, useScrap } from '../hooks/queries'
import { formatDate, formatDateTime } from '../lib/date'
import { hostOf, safeHref } from '../lib/url'

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
  if (q.isError)
    return (
      <>
        <PanelHeader backTo={listPath} />
        <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />
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

      <div className="mx-auto max-w-2xl space-y-6 px-4 py-5 pb-safe lg:px-8 lg:py-8">
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted">
            <span className="rounded bg-hover px-1.5 py-0.5 text-xs font-medium text-fg">{s.source.name}</span>
            <span>{hostOf(s.url)}</span>
          </div>
          <h1 className="text-2xl leading-snug font-bold tracking-tight break-words">{s.title || '(제목 없음)'}</h1>
          {s.topics.length > 0 && (
            <ul className="flex flex-wrap gap-1.5" aria-label="주제">
              {s.topics.map((t) => (
                <li key={t.id}>
                  <Link
                    to={`${topicBase}?topics=${t.id}`}
                    className="inline-flex min-h-11 items-center rounded-full bg-accent-soft px-3 text-sm text-accent lg:min-h-8 lg:px-2.5"
                  >
                    #{t.name}
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
            <span className="min-w-0 flex-1 truncate text-sm">{s.url}</span>
            <span className="shrink-0 text-sm font-medium text-accent">열기</span>
          </a>
        ) : (
          <Notice tone="warn">열 수 없는 링크 형식입니다: {s.url}</Notice>
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
            onConfirm={() => del.mutate(s.id, { onSuccess: () => navigate(listPath, { replace: true }) })}
          />
        </footer>
      </div>
    </article>
  )
}
