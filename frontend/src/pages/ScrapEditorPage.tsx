import { useMutation } from '@tanstack/react-query'
import { useRef, useState, type ReactNode } from 'react'
import { useNavigate, useOutletContext, useParams } from 'react-router'
import { aiApi, metaApi } from '../api'
import { errorMessage } from '../api/http'
import type { AiExtractResponse, Scrap, Topic } from '../api/types'
import { IconClipboard, IconSparkles } from '../components/Icons'
import { Markdown } from '../components/Markdown'
import { PanelHeader } from '../components/PanelHeader'
import type { PanelContext } from '../components/SplitPane'
import { TopicPicker } from '../components/TopicPicker'
import { Badge, Button, ErrorState, Field, Notice, Spinner } from '../components/ui'
import { useSaveScrap, useScrap, useSources, useTopics } from '../hooks/queries'
import { formatDate } from '../lib/date'
import { cx, fieldCls, inputCls, textareaCls } from '../lib/styles'
import { extractUrl, isValidHttpUrl } from '../lib/url'

/** 저장(새 스크랩) / 수정 화면 */
export function ScrapEditorPage() {
  const { id } = useParams()
  const ctx = useOutletContext<PanelContext>()
  const isEdit = id !== undefined
  const scrap = useScrap(isEdit ? Number(id) : NaN)
  const sources = useSources()
  const topics = useTopics()
  const listPath = `${ctx.base || '/'}${ctx.search}`
  const backTo = isEdit ? `${ctx.base}/scraps/${id}${ctx.search}` : listPath

  const header = <PanelHeader backTo={backTo} title={isEdit ? '스크랩 수정' : '새 스크랩'} />

  if ((isEdit && scrap.isPending) || sources.isPending || topics.isPending)
    return (
      <>
        {header}
        <div className="flex justify-center py-16 text-muted">
          <Spinner className="size-6" />
        </div>
      </>
    )
  const err = (isEdit && scrap.error) || sources.error || topics.error
  if (err)
    return (
      <>
        {header}
        <ErrorState message={errorMessage(err)} />
      </>
    )

  return (
    <>
      {header}
      <ScrapForm
        key={isEdit ? `edit-${id}` : 'new'}
        initial={isEdit ? scrap.data : undefined}
        topics={topics.data ?? []}
        ctx={ctx}
        backTo={backTo}
      />
    </>
  )
}

type AiField = 'title' | 'memo' | 'due_date'

interface AiState {
  /** 빈 칸이어서 AI 제안으로 채운 칸 */
  filled: AiField[]
  /** 이미 입력돼 있어서 바로 채우지 않고 제안으로만 보여 주는 값 */
  pending: Partial<Record<AiField, string>>
  suggestedTopicIds: number[]
  newTopicNames: string[]
  /** "제안 되돌리기"용: AI 채우기 직전 값 */
  snapshot: { title: string; memo: string; due: string; topicIds: number[] } | null
}

const emptyAi: AiState = { filled: [], pending: {}, suggestedTopicIds: [], newTopicNames: [], snapshot: null }

function ScrapForm({
  initial,
  topics,
  ctx,
  backTo,
}: {
  initial?: Scrap
  topics: Topic[]
  ctx: PanelContext
  backTo: string
}) {
  const navigate = useNavigate()
  const sources = useSources()
  const save = useSaveScrap()
  const urlRef = useRef<HTMLInputElement>(null)

  const [url, setUrl] = useState(initial?.url ?? '')
  const [title, setTitle] = useState(initial?.title ?? '')
  const [sourceId, setSourceId] = useState<number | null>(initial?.source.id ?? null)
  const [sourceMode, setSourceMode] = useState<'auto' | 'manual' | null>(initial ? 'manual' : null)
  const [topicIds, setTopicIds] = useState<number[]>(initial?.topics.map((t) => t.id) ?? [])
  const [memo, setMemo] = useState(initial?.memo ?? '')
  const [memoTab, setMemoTab] = useState<'write' | 'preview'>('write')
  const [due, setDue] = useState(initial?.due_date ?? '')
  const [bodyOpen, setBodyOpen] = useState(false)
  const [bodyText, setBodyText] = useState('')
  const [clipMsg, setClipMsg] = useState<string | null>(null)
  const [previewedUrl, setPreviewedUrl] = useState(initial?.url ?? '')
  const [ai, setAi] = useState<AiState>(emptyAi)
  const [notFetched, setNotFetched] = useState(false)
  const [errors, setErrors] = useState<{ url?: string; source?: string }>({})

  const preview = useMutation({ mutationFn: metaApi.preview })
  const extract = useMutation({ mutationFn: aiApi.extract })

  // ------------------------------------------------ 링크 → 출처 자동 판별 + 제목 자동 채움
  const runPreview = (u: string) => {
    const trimmed = u.trim()
    if (!isValidHttpUrl(trimmed) || trimmed === previewedUrl) return
    setPreviewedUrl(trimmed)
    preview.mutate(
      { url: trimmed },
      {
        onSuccess: (res) => {
          if (sourceMode !== 'manual') {
            setSourceId(res.source_id)
            setSourceMode('auto')
          }
          setTitle((prev) => (prev.trim() === '' && res.title ? res.title : prev))
        },
      },
    )
  }

  const changeUrl = (v: string) => {
    setUrl(v)
    setErrors((e) => ({ ...e, url: undefined }))
  }

  const pasteFromClipboard = async () => {
    const fail = (msg: string) => {
      setClipMsg(msg)
      urlRef.current?.focus()
    }
    if (!navigator.clipboard?.readText) {
      fail('이 브라우저에서는 클립보드를 바로 읽을 수 없어요. 아래 링크 칸을 길게 눌러 직접 붙여넣어 주세요.')
      return
    }
    try {
      const text = await navigator.clipboard.readText()
      const found = extractUrl(text)
      if (!found) {
        fail('클립보드에 링크가 없어요. 링크를 복사한 뒤 다시 누르거나, 아래 칸에 직접 붙여넣어 주세요.')
        return
      }
      setClipMsg(null)
      changeUrl(found)
      runPreview(found)
    } catch {
      fail('클립보드를 읽을 수 없어요. 아래 링크 칸을 길게 눌러 직접 붙여넣어 주세요.')
    }
  }

  // ------------------------------------------------ AI로 채우기 (제안만, 저장은 하지 않음)
  const runAi = () => {
    const u = url.trim()
    if (!isValidHttpUrl(u)) {
      setErrors({ url: 'AI로 채우려면 먼저 올바른 링크를 넣어 주세요.' })
      return
    }
    setNotFetched(false)
    extract.mutate({ url: u, text: bodyText.trim() || undefined }, { onSuccess: applyAi })
  }

  const applyAi = (res: AiExtractResponse) => {
    if (!res.content_fetched) {
      setNotFetched(true)
      setBodyOpen(true)
      return
    }
    const snapshot = ai.snapshot ?? { title, memo, due, topicIds }
    const filled: AiField[] = []
    const pending: AiState['pending'] = {}
    const offer = (field: AiField, value: string | null, current: string, set: (v: string) => void) => {
      if (!value) return
      if (current.trim() === '' || ai.filled.includes(field)) {
        set(value)
        filled.push(field)
      } else if (current !== value) {
        pending[field] = value
      }
    }
    offer('title', res.title, title, setTitle)
    offer('due_date', res.due_date, due, setDue)
    offer('memo', res.memo, memo, setMemo)

    const lower = (s: string) => s.trim().toLowerCase()
    const matched = topics.filter((t) => res.topic_suggestions.some((n) => lower(n) === lower(t.name)))
    const added = matched.map((t) => t.id).filter((tid) => !topicIds.includes(tid))
    if (added.length) setTopicIds([...topicIds, ...added])
    const newNames = res.topic_suggestions.filter((n) => !topics.some((t) => lower(t.name) === lower(n)))

    setAi({ filled, pending, suggestedTopicIds: added, newTopicNames: newNames, snapshot })
  }

  const undoAi = () => {
    if (ai.snapshot) {
      setTitle(ai.snapshot.title)
      setMemo(ai.snapshot.memo)
      setDue(ai.snapshot.due)
      setTopicIds(ai.snapshot.topicIds)
    }
    setAi(emptyAi)
  }

  const touched = (field: AiField) =>
    setAi((a) => (a.filled.includes(field) ? { ...a, filled: a.filled.filter((f) => f !== field) } : a))

  const acceptPending = (field: AiField) => {
    const v = ai.pending[field]
    if (v === undefined) return
    if (field === 'title') setTitle(v)
    if (field === 'memo') setMemo(v)
    if (field === 'due_date') setDue(v)
    setAi((a) => {
      const pending = { ...a.pending }
      delete pending[field]
      return { ...a, pending, filled: [...a.filled, field] }
    })
  }
  const dismissPending = (field: AiField) =>
    setAi((a) => {
      const pending = { ...a.pending }
      delete pending[field]
      return { ...a, pending }
    })

  const hasAiResult =
    ai.filled.length > 0 ||
    Object.keys(ai.pending).length > 0 ||
    ai.suggestedTopicIds.length > 0 ||
    ai.newTopicNames.length > 0

  // ------------------------------------------------ 저장
  const submit = () => {
    const u = url.trim()
    const next: typeof errors = {}
    if (!isValidHttpUrl(u)) next.url = 'http:// 또는 https://로 시작하는 링크를 넣어 주세요.'
    if (!sourceId) next.source = '출처를 선택해 주세요.'
    setErrors(next)
    if (next.url || next.source) return
    save.mutate(
      {
        id: initial?.id,
        body: {
          url: u,
          title: title.trim() || u,
          memo,
          source_id: sourceId!,
          topic_ids: topicIds,
          liked: initial?.liked ?? false,
          due_date: due || null,
        },
      },
      { onSuccess: (s) => navigate(`${ctx.base}/scraps/${s.id}${ctx.search}`, { replace: true }) },
    )
  }

  const aiBadge = (field: AiField) =>
    ai.filled.includes(field) ? (
      <Badge tone="accent">
        <IconSparkles size={12} />
        AI 제안
      </Badge>
    ) : null

  const pendingBox = (field: AiField, render?: (v: string) => ReactNode) => {
    const v = ai.pending[field]
    if (v === undefined) return null
    return (
      <div className="rounded-lg border border-dashed border-accent/40 bg-accent-soft/50 p-2.5 text-sm">
        <div className="mb-1 inline-flex items-center gap-1 text-xs font-medium text-accent">
          <IconSparkles size={13} />
          AI 제안 (아직 적용 안 됨)
        </div>
        <div className="line-clamp-4 whitespace-pre-wrap text-fg">{render ? render(v) : v}</div>
        <div className="mt-2 flex gap-2">
          <Button variant="secondary" onClick={() => acceptPending(field)}>
            이 제안으로 바꾸기
          </Button>
          <Button variant="ghost" onClick={() => dismissPending(field)}>
            무시
          </Button>
        </div>
      </div>
    )
  }

  return (
    <form
      noValidate
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
      className="flex min-h-[calc(100dvh-3.5rem)] flex-col lg:min-h-[calc(100dvh-3.5rem)]"
    >
      <div className="mx-auto w-full max-w-2xl flex-1 space-y-6 px-4 py-5 lg:px-8 lg:py-6">
        {/* 1. 링크 */}
        <section className="space-y-3">
          <Button
            variant={initial ? 'secondary' : 'primary'}
            size="lg"
            className="w-full"
            onClick={pasteFromClipboard}
          >
            <IconClipboard size={22} />
            {initial ? '링크 다시 붙여넣기' : '링크 붙여넣기'}
          </Button>
          {clipMsg && <Notice tone="warn">{clipMsg}</Notice>}

          <Field label="링크" htmlFor="url">
            <input
              id="url"
              ref={urlRef}
              type="url"
              inputMode="url"
              autoComplete="off"
              autoCapitalize="off"
              spellCheck={false}
              placeholder="https://"
              value={url}
              onChange={(e) => changeUrl(e.target.value)}
              onBlur={() => runPreview(url)}
              onPaste={(e) => {
                const text = e.clipboardData.getData('text')
                const found = extractUrl(text)
                if (found) {
                  e.preventDefault()
                  changeUrl(found)
                  runPreview(found)
                }
              }}
              aria-invalid={!!errors.url}
              aria-describedby={errors.url ? 'url-error' : undefined}
              className={cx(inputCls, errors.url && 'border-danger')}
            />
          </Field>
          {errors.url && (
            <p id="url-error" className="text-sm text-danger">
              {errors.url}
            </p>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <label htmlFor="source" className="text-sm font-medium">
              출처
            </label>
            <select
              id="source"
              value={sourceId ?? ''}
              onChange={(e) => {
                setSourceId(e.target.value ? Number(e.target.value) : null)
                setSourceMode('manual')
                setErrors((x) => ({ ...x, source: undefined }))
              }}
              className={cx(fieldCls, 'min-w-36 pr-8', errors.source && 'border-danger')}
            >
              <option value="">선택</option>
              {sources.data?.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
            {preview.isPending ? (
              <span className="inline-flex items-center gap-1.5 text-xs text-muted">
                <Spinner className="size-3" />
                판별 중
              </span>
            ) : sourceMode === 'auto' ? (
              <Badge tone="muted">링크로 자동 판별 · 바꿀 수 있어요</Badge>
            ) : null}
            {errors.source && <p className="w-full text-sm text-danger">{errors.source}</p>}
          </div>
        </section>

        {/* 2. AI로 채우기 */}
        <section className="space-y-3 rounded-xl border border-line bg-subtle p-3.5">
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="secondary" onClick={runAi} loading={extract.isPending} className="bg-bg">
              {!extract.isPending && <IconSparkles size={18} className="text-accent" />}
              {extract.isPending ? 'AI가 읽는 중…' : 'AI로 채우기'}
            </Button>
            <p className="min-w-0 flex-1 text-xs text-muted">
              제목·마감일·메모·주제를 제안만 해요. 저장은 직접 눌러야 돼요.
            </p>
          </div>

          {extract.isError && <Notice tone="danger">{errorMessage(extract.error)}</Notice>}
          {notFetched && (
            <Notice tone="warn">
              이 페이지의 본문을 가져오지 못했어요. 아래 '본문 붙여넣기'에 내용을 붙여넣고 다시 'AI로 채우기'를 눌러 주세요.
            </Notice>
          )}
          {hasAiResult && (
            <Notice tone="info">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="flex-1">
                  <strong className="font-semibold">AI 제안을 채웠어요.</strong> 내용을 확인하고 아래 '저장'을 눌러야 저장돼요.
                </span>
                <button type="button" onClick={undoAi} className="min-h-11 text-sm font-medium text-accent underline lg:min-h-0">
                  제안 되돌리기
                </button>
              </div>
            </Notice>
          )}

          <details
            open={bodyOpen}
            onToggle={(e) => setBodyOpen((e.currentTarget as HTMLDetailsElement).open)}
            className="group"
          >
            <summary className="flex min-h-11 cursor-pointer list-none items-center gap-1 text-sm text-muted select-none hover:text-fg [&::-webkit-details-marker]:hidden">
              <span className="inline-block transition group-open:rotate-90">▸</span>
              본문 붙여넣기 (본문을 못 가져오는 사이트용)
            </summary>
            <textarea
              value={bodyText}
              onChange={(e) => setBodyText(e.target.value)}
              rows={6}
              placeholder="페이지 본문을 복사해서 붙여넣으세요. AI로 채우기에만 쓰이고 저장되지 않아요."
              aria-label="본문 붙여넣기"
              className={cx(textareaCls, 'mt-1 bg-bg')}
            />
          </details>
        </section>

        {/* 3. 제목 */}
        <div className="space-y-2">
          <Field label="제목" htmlFor="title" badge={aiBadge('title')} hint="비워 두면 링크 주소로 저장돼요.">
            <input
              id="title"
              value={title}
              onChange={(e) => {
                setTitle(e.target.value)
                touched('title')
              }}
              placeholder="제목"
              className={inputCls}
            />
          </Field>
          {pendingBox('title')}
        </div>

        {/* 4. 주제 */}
        <Field label="주제" badge={ai.suggestedTopicIds.length > 0 ? aiBadgeTopic : null}>
          <TopicPicker
            topics={topics}
            selected={topicIds}
            onChange={setTopicIds}
            aiSuggestedIds={ai.suggestedTopicIds}
            aiNewNames={ai.newTopicNames}
            onDismissNewName={(n) => setAi((a) => ({ ...a, newTopicNames: a.newTopicNames.filter((x) => x !== n) }))}
          />
        </Field>

        {/* 5. 마감일 */}
        <div className="space-y-2">
          <Field label="마감일 (선택)" htmlFor="due" badge={aiBadge('due_date')}>
            <div className="flex gap-2">
              <input
                id="due"
                type="date"
                value={due}
                onChange={(e) => {
                  setDue(e.target.value)
                  touched('due_date')
                }}
                className={cx(fieldCls, 'min-w-44 flex-1 sm:flex-none')}
              />
              {due && (
                <Button variant="ghost" onClick={() => setDue('')}>
                  지우기
                </Button>
              )}
            </div>
          </Field>
          {pendingBox('due_date', (v) => formatDate(v))}
        </div>

        {/* 6. 메모 */}
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <label htmlFor="memo" className="text-sm font-medium">
              메모
            </label>
            {aiBadge('memo')}
            <span className="text-xs text-muted">마크다운 지원</span>
            <div role="tablist" aria-label="메모 보기" className="ml-auto inline-flex rounded-lg border border-line p-0.5 text-sm">
              {(
                [
                  ['write', '작성'],
                  ['preview', '미리보기'],
                ] as const
              ).map(([v, label]) => (
                <button
                  key={v}
                  type="button"
                  role="tab"
                  aria-selected={memoTab === v}
                  onClick={() => setMemoTab(v)}
                  className={cx(
                    'min-h-10 rounded-md px-3 lg:min-h-8',
                    memoTab === v ? 'bg-hover font-medium text-fg' : 'text-muted',
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          {memoTab === 'write' ? (
            <textarea
              id="memo"
              value={memo}
              onChange={(e) => {
                setMemo(e.target.value)
                touched('memo')
              }}
              rows={10}
              placeholder={'## 요약\n- 핵심 내용\n\n긴 메모도 괜찮아요.'}
              className={cx(textareaCls, 'font-mono text-[15px] lg:text-sm')}
            />
          ) : (
            <div className="min-h-40 rounded-lg border border-line px-3 py-2.5">
              {memo.trim() ? <Markdown>{memo}</Markdown> : <p className="text-sm text-muted">미리 볼 내용이 없어요.</p>}
            </div>
          )}
          {pendingBox('memo')}
        </div>
      </div>

      {/* 저장 바 */}
      <div className="sticky bottom-0 z-10 border-t border-line bg-bg/95 pb-safe backdrop-blur">
        <div className="mx-auto flex w-full max-w-2xl items-center gap-2 px-4 py-3 lg:px-8">
          {save.isError && <p className="min-w-0 flex-1 text-sm text-danger">{errorMessage(save.error)}</p>}
          <div className="ml-auto flex gap-2">
            <Button variant="ghost" onClick={() => navigate(backTo)}>
              취소
            </Button>
            <Button type="submit" variant="primary" loading={save.isPending} className="min-w-24">
              저장
            </Button>
          </div>
        </div>
      </div>
    </form>
  )
}

const aiBadgeTopic = (
  <Badge tone="accent">
    <IconSparkles size={12} />
    AI 추천 포함
  </Badge>
)
