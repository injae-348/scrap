import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, useNavigate, useOutletContext, useParams } from 'react-router'
import { aiApi, metaApi } from '../api'
import { errorMessage, formatWait, isAiDailyLimit, isApiError } from '../api/http'
import type { AiExtractResponse, Scrap, Source, Topic } from '../api/types'
import { AiErrorNotice, AiProgress } from '../components/AiStatus'
import { IconClipboard, IconSparkles } from '../components/Icons'
import { Markdown } from '../components/Markdown'
import { PanelHeader } from '../components/PanelHeader'
import type { PanelContext } from '../components/SplitPane'
import { TopicPicker } from '../components/TopicPicker'
import { Badge, Button, EmptyState, ErrorState, Field, LeaveDialog, Notice, Spinner } from '../components/ui'
import { keys, useSaveScrap, useScrap, useSources, useTopics } from '../hooks/queries'
import { useAbortableTask } from '../hooks/useAbortableTask'
import { useLeaveGuard } from '../hooks/useLeaveGuard'
import { useRetryCountdown } from '../hooks/useRetryCountdown'
import { BODY_MAX, cleanPastedBody, matchTopicSuggestions, planAiFill, type AiField } from '../lib/aiSuggest'
import { formatDate } from '../lib/date'
import { buildScrapCreate, buildScrapPatch, reconcileSelection, sameIds, selectionFixMessage } from '../lib/scrapForm'
import { cx, fieldCls, inputCls, textareaCls } from '../lib/styles'
import { showToast } from '../lib/toast'
import { extractUrl, isValidHttpUrl } from '../lib/url'
import { displayText } from '../lib/text'

const URL_MAX = 2048
const TITLE_MAX = 300
const MEMO_MAX = 100_000

/** 저장(새 스크랩) / 수정 화면 */
export function ScrapEditorPage() {
  const { id } = useParams()
  const ctx = useOutletContext<PanelContext>()
  const isEdit = id !== undefined
  // 수정은 목록 데이터가 아니라 GET /scraps/{id}의 최신 전문으로 연다
  const scrap = useScrap(isEdit ? Number(id) : NaN, { fresh: true })
  const sources = useSources()
  const topics = useTopics()
  const listPath = `${ctx.base || '/'}${ctx.search}`
  const backTo = isEdit ? `${ctx.base}/scraps/${id}${ctx.search}` : listPath

  const header = <PanelHeader backTo={backTo} title={isEdit ? '스크랩 수정' : '새 스크랩'} />
  const editLoading = isEdit && (scrap.isPending || (scrap.isFetching && !scrap.isFetchedAfterMount))

  if (editLoading || sources.isPending || topics.isPending)
    return (
      <>
        {header}
        <div className="flex justify-center py-16 text-muted">
          <Spinner className="size-6" />
        </div>
      </>
    )
  if (isEdit && scrap.isError && !scrap.data)
    return (
      <>
        {header}
        {isApiError(scrap.error, 'not_found', 'invalid_input') ? (
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
          <ErrorState message={errorMessage(scrap.error)} onRetry={() => scrap.refetch()} />
        )}
      </>
    )
  // 출처·주제를 한 번도 받지 못했을 때만 오류 화면. 받아 둔 목록이 있으면 폼(작성 중인 내용)을 유지하고 위에 알린다
  const err = sources.error || topics.error
  if (!sources.data || !topics.data)
    return (
      <>
        {header}
        <ErrorState
          message={errorMessage(err)}
          onRetry={() => {
            void sources.refetch()
            void topics.refetch()
          }}
        />
      </>
    )

  return (
    <>
      {header}
      {err && (
        <div role="alert" className="flex flex-wrap items-center gap-x-3 border-b border-line bg-warn-soft px-4 py-1.5 text-sm lg:px-8">
          <span className="min-w-0 flex-1">출처·주제 목록을 새로 불러오지 못했어요. {errorMessage(err)}</span>
          <button
            type="button"
            className="min-h-11 font-medium text-accent underline"
            onClick={() => {
              void sources.refetch()
              void topics.refetch()
            }}
          >
            다시 시도
          </button>
        </div>
      )}
      {isEdit && scrap.isError && (
        <div role="alert" className="border-b border-line bg-warn-soft px-4 py-2 text-sm lg:px-8">
          최신 내용을 불러오지 못해 이전에 받은 내용으로 열었어요. {errorMessage(scrap.error)}
        </div>
      )}
      <ScrapForm
        key={isEdit ? `edit-${id}` : 'new'}
        initial={isEdit ? scrap.data : undefined}
        topics={topics.data}
        ctx={ctx}
        backTo={backTo}
      />
    </>
  )
}

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

/** 링크 입력 검사 (서버 규칙과 같게: http/https, 2048자, 사용자 정보 금지) */
function checkUrl(u: string): string | null {
  if (!u) return '링크를 넣어 주세요.'
  if (u.length > URL_MAX) return `링크는 ${URL_MAX}자 이하여야 해요.`
  if (!isValidHttpUrl(u) || /\s/.test(u)) return 'http:// 또는 https://로 시작하는 링크를 넣어 주세요.'
  try {
    const p = new URL(u)
    if (p.username || p.password) return '아이디·비밀번호(user:pass@)가 들어 있는 링크는 저장할 수 없어요.'
  } catch {
    return 'http:// 또는 https://로 시작하는 링크를 넣어 주세요.'
  }
  return null
}

type PreviewState =
  | { status: 'idle' }
  | { status: 'loading'; url: string }
  | { status: 'done'; url: string; gotTitle: boolean }
  | { status: 'error'; url: string; error: unknown }

function ScrapForm({
  initial: initialProp,
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
  const qc = useQueryClient()
  const sources = useSources()
  const save = useSaveScrap()
  const urlRef = useRef<HTMLInputElement>(null)

  // 폼을 연 순간의 스크랩 하나를 기준으로 삼는다 (초기값·변경 감지·PATCH 비교 모두).
  // 그 뒤 다시 받아 온 값(다른 기기의 변경)으로 기준이 바뀌면 손대지 않은 칸까지 덮어쓰게 된다.
  const [initial] = useState(initialProp)
  const init = {
    url: initial?.url ?? '',
    title: initial?.title ?? '',
    memo: initial?.memo ?? '',
    due: initial?.due_date ?? '',
    sourceId: initial?.source.id ?? null,
    topicIds: initial?.topics.map((t) => t.id) ?? [],
  }

  const [url, setUrl] = useState(init.url)
  const [title, setTitle] = useState(init.title)
  /** 새 스크랩에서 null = 자동 판별(서버가 정함) */
  const [sourceId, setSourceId] = useState<number | null>(init.sourceId)
  const [sourceMode, setSourceMode] = useState<'auto' | 'manual' | null>(initial ? 'manual' : null)
  const [topicIds, setTopicIds] = useState<number[]>(init.topicIds)
  const [memo, setMemo] = useState(init.memo)
  const [memoTab, setMemoTab] = useState<'write' | 'preview'>('write')
  const [due, setDue] = useState(init.due)
  const [bodyOpen, setBodyOpen] = useState(false)
  const [bodyText, setBodyText] = useState('')
  const [clipMsg, setClipMsg] = useState<string | null>(null)
  const [preview, setPreview] = useState<PreviewState>({ status: 'idle' })
  /** 미리보기 결과로 채운 제목 (사용자가 고치면 해제) */
  const [titleFromPreview, setTitleFromPreview] = useState(false)
  const [ai, setAi] = useState<AiState>(emptyAi)
  /** 본문을 얻지 못해 AI가 답하지 못함: 'fetch' 페이지를 못 가져옴 / 'pasted' 붙여넣은 본문으로도 부족 */
  const [notFetched, setNotFetched] = useState<'fetch' | 'pasted' | null>(null)
  /** 응답을 적용하지 않은 이유 등 AI 채우기 안내 */
  const [aiNotice, setAiNotice] = useState<string | null>(null)
  /** 이 화면에서 AI 사용 한도 도달(503 ai_quota_exceeded)을 받았는지. 다시 누르는 것은 막지 않고 표시만 한다 */
  const [aiQuotaHit, setAiQuotaHit] = useState(false)
  const [errors, setErrors] = useState<{ url?: string }>({})
  /** 마지막으로 미리보기를 요청한 주소. 늦게 온 이전 응답은 버린다 */
  const latestPreviewUrl = useRef<string>(init.url)
  // 미리보기 응답(최대 5초 뒤)이 그때의 최신 값을 보도록 ref로도 들고 있는다
  const sourceModeRef = useRef(sourceMode)
  const titleRef = useRef(title)
  useEffect(() => {
    sourceModeRef.current = sourceMode
    titleRef.current = title
  }, [sourceMode, title])

  // AI로 채우기: 수십 초(서버 상한 60초) 걸릴 수 있다. 취소할 수 있고, 화면을 떠나면 취소된다.
  // 기다리는 동안 다른 칸은 계속 입력할 수 있다.
  const extract = useAbortableTask()
  const extractError = extract.state.status === 'error' ? extract.state.error : null
  const aiWait = useRetryCountdown(extractError)
  /** 하루 사용량 소진(429 ai_daily_limit): 버튼은 Retry-After(다음 날 0시)까지 막고 남은 시간 대신 소진 표시 */
  const aiDailyLimit = isAiDailyLimit(extractError)

  const dirty =
    url.trim() !== init.url ||
    title !== init.title ||
    memo !== init.memo ||
    due !== init.due ||
    !sameIds(topicIds, init.topicIds) ||
    (sourceMode === 'manual' && sourceId !== init.sourceId)
  const { blocker, allowLeave } = useLeaveGuard(dirty && !save.isSuccess)

  // ------------------------------------------------ 링크 → 출처 자동 판별 + 제목 자동 채움 (POST /meta/preview)
  // 서버가 최대 5초 걸릴 수 있다. 기다리는 동안 다른 칸은 계속 입력할 수 있다.
  const runPreview = (u: string, force = false) => {
    const trimmed = u.trim()
    if (checkUrl(trimmed)) return
    if (!force && trimmed === latestPreviewUrl.current) return
    latestPreviewUrl.current = trimmed
    setPreview({ status: 'loading', url: trimmed })
    metaApi.preview({ url: trimmed }).then(
      (res) => {
        if (latestPreviewUrl.current !== trimmed) return
        // 출처: 사용자가 직접 고른 적이 없을 때만 반영 (이후에도 바꿀 수 있다)
        if (sourceModeRef.current !== 'manual') {
          setSourceId(res.source_id)
          setSourceMode('auto')
        }
        // 제목: 비어 있을 때만 채운다 (이미 입력한 제목은 덮어쓰지 않음). null이면 빈칸 그대로
        if (res.title && titleRef.current.trim() === '') {
          setTitle(res.title)
          setTitleFromPreview(true)
        }
        setPreview({ status: 'done', url: trimmed, gotTitle: !!res.title })
      },
      (error: unknown) => {
        if (latestPreviewUrl.current !== trimmed) return
        if (isApiError(error, 'invalid_input')) setErrors({ url: errorMessage(error) })
        setPreview({ status: 'error', url: trimmed, error })
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
    if (checkUrl(u)) {
      setErrors({ url: 'AI로 채우려면 먼저 올바른 링크를 넣어 주세요.' })
      return
    }
    const text = cleanPastedBody(bodyText)
    setNotFetched(null)
    setAiNotice(null)
    extract.run(
      (signal) => aiApi.extract({ url: u, text: text || undefined }, signal),
      // 응답이 올 때의 최신 입력값을 기준으로 적용한다 (기다리는 동안 사용자가 고친 칸을 덮어쓰지 않게)
      (res) => {
        setAiQuotaHit(false)
        applyAiRef.current(res, { url: u, usedText: !!text })
      },
      (error) => {
        if (isApiError(error, 'ai_quota_exceeded')) setAiQuotaHit(true)
      },
    )
  }

  const applyAi = (res: AiExtractResponse, req: { url: string; usedText: boolean }) => {
    if (url.trim() !== req.url) {
      setAiNotice("기다리는 동안 링크가 바뀌어서 AI 제안을 적용하지 않았어요. 다시 'AI로 채우기'를 눌러 주세요.")
      return
    }
    if (!res.content_fetched) {
      // 본문 없이 온 제목은 미리보기 제목이다. 빈 칸일 때만 채운다
      if (res.title && title.trim() === '') {
        setTitle(res.title)
        setTitleFromPreview(true)
      }
      setNotFetched(req.usedText ? 'pasted' : 'fetch')
      setBodyOpen(true)
      return
    }
    const snapshot = ai.snapshot ?? { title, memo, due, topicIds }
    const plan = planAiFill({ title, memo, due_date: due }, ai.filled, res)
    if (plan.apply.title !== undefined) {
      setTitle(plan.apply.title)
      setTitleFromPreview(false)
    }
    if (plan.apply.due_date !== undefined) setDue(plan.apply.due_date)
    if (plan.apply.memo !== undefined) setMemo(plan.apply.memo)

    // 주제: 기존 주제(대소문자 무시)는 선택에 더하고, 없는 이름은 "새 주제 제안"으로만 보여 준다 (자동 생성 안 함)
    const { matchedIds, newNames } = matchTopicSuggestions(res.topic_suggestions ?? [], topics)
    const added = matchedIds.filter((tid) => !topicIds.includes(tid))

    // 채울 것이 하나도 없으면(모두 비었거나 지금 값과 같음) 이전 제안 표시는 그대로 두고 알린다
    const nothing =
      Object.keys(plan.apply).length === 0 &&
      Object.keys(plan.pending).length === 0 &&
      added.length === 0 &&
      newNames.length === 0
    if (nothing) {
      setAiNotice(
        req.usedText
          ? 'AI가 붙여넣은 본문에서 채울 만한 내용을 찾지 못했어요.'
          : "AI가 이 페이지에서 채울 만한 내용을 찾지 못했어요. '본문 붙여넣기'에 내용을 넣고 다시 시도해 보세요.",
      )
      return
    }
    if (added.length) setTopicIds([...topicIds, ...added])

    setAi({
      filled: Object.keys(plan.apply) as AiField[],
      pending: plan.pending,
      suggestedTopicIds: added,
      newTopicNames: newNames,
      snapshot,
    })
  }
  const applyAiRef = useRef(applyAi)
  useEffect(() => {
    applyAiRef.current = applyAi
  })

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

  const aiPending = extract.state.status === 'pending'
  const hasAiResult =
    ai.filled.length > 0 ||
    Object.keys(ai.pending).length > 0 ||
    ai.suggestedTopicIds.length > 0 ||
    ai.newTopicNames.length > 0

  // ------------------------------------------------ 고른 주제·출처 정리
  const [selectionNotice, setSelectionNotice] = useState<string | null>(null)
  // 비동기 작업(목록 다시 받기)이 끝난 시점의 최신 선택을 읽기 위해 ref로도 들고 있는다
  const selRef = useRef({ sourceId, topicIds })
  useEffect(() => {
    selRef.current = { sourceId, topicIds }
  }, [sourceId, topicIds])
  /** 지금 목록 기준으로 (그 시점의 최신) 선택을 맞추고, 바뀐 것이 있으면 화면 상태와 안내를 갱신한다 */
  const applySelectionFix = (curTopics: Topic[], curSources: Source[]) => {
    const sel = selRef.current
    const fix = reconcileSelection(sel, { topics: curTopics, sources: curSources }, initial ? 'edit' : 'create')
    const msg = selectionFixMessage(fix, curSources.find((x) => x.is_default)?.name)
    if (msg) {
      setTopicIds(fix.topicIds)
      setSourceId(fix.sourceId)
      if (fix.sourceChanged === 'auto') setSourceMode(null)
      setSelectionNotice(msg)
    }
    return { msg, sourceId: fix.sourceId, topicIds: fix.topicIds }
  }

  // ------------------------------------------------ 저장
  const submit = () => {
    const u = url.trim()
    const urlErr = checkUrl(u)
    setErrors({ url: urlErr ?? undefined })
    if (urlErr) {
      urlRef.current?.focus()
      return
    }
    const t = title.trim()
    // 저장 직전에 고른 주제·출처를 지금 목록에 있는 것으로 맞춘다 (다른 기기에서 지운 경우)
    const fixed = applySelectionFix(topics, sources.data ?? [])
    const fix = fixed.msg
    const onSuccess = (s: Scrap) => {
      allowLeave()
      showToast(fix ? `${initial ? '수정했어요' : '저장했어요'}. ${fix}` : initial ? '수정했어요.' : '저장했어요.')
      navigate(`${ctx.base}/scraps/${s.id}${ctx.search}`, { replace: true })
    }
    const onError = (e: unknown) => {
      // 입력 오류면 주제·출처 목록을 새로 받아 선택을 다시 맞춘다 (다시 저장하면 통과하게)
      if (isApiError(e, 'invalid_input')) {
        void Promise.all([
          qc.refetchQueries({ queryKey: keys.topics }),
          qc.refetchQueries({ queryKey: keys.sources }),
        ]).then(() => {
          applySelectionFix(qc.getQueryData<Topic[]>(keys.topics) ?? topics, qc.getQueryData<Source[]>(keys.sources) ?? [])
        })
      }
    }

    const values = { url: u, title: t, memo, sourceId: fixed.sourceId, topicIds: fixed.topicIds, due }
    if (initial) {
      // PATCH: 바뀐 필드만 보낸다 (liked는 보내지 않음 — 좋아요는 PUT /like로만)
      const body = buildScrapPatch(initial, values)
      if (Object.keys(body).length === 0) {
        allowLeave()
        navigate(backTo, { replace: true })
        return
      }
      save.mutate({ id: initial.id, body }, { onSuccess, onError })
      return
    }
    save.mutate({ body: buildScrapCreate(values) }, { onSuccess, onError })
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
              maxLength={URL_MAX}
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
          <PreviewNotice
            state={preview}
            titleEmpty={!title.trim()}
            onRetry={() => runPreview(url, true)}
          />

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
              }}
              className={cx(fieldCls, 'min-w-36 pr-8')}
            >
              {!initial && <option value="">자동 (링크로 판별)</option>}
              {sources.data?.map((s) => (
                <option key={s.id} value={s.id}>
                  {displayText(s.name)}
                </option>
              ))}
            </select>
            {preview.status === 'loading' && sourceMode !== 'manual' ? (
              <span className="inline-flex items-center gap-1.5 text-xs text-muted">
                <Spinner className="size-3" />
                판별 중
              </span>
            ) : sourceMode === 'auto' ? (
              <Badge tone="muted">링크로 자동 판별 · 바꿀 수 있어요</Badge>
            ) : null}
          </div>
        </section>

        {/* 2. AI로 채우기 */}
        <section className="space-y-3 rounded-xl border border-line bg-subtle p-3.5">
          <div className="flex flex-wrap items-center gap-3">
            <Button
              variant="secondary"
              onClick={runAi}
              loading={aiPending}
              disabled={aiWait > 0}
              className="bg-bg"
            >
              {!aiPending && <IconSparkles size={18} className="text-accent" />}
              {aiPending
                ? 'AI가 읽는 중…'
                : aiWait > 0
                  ? aiDailyLimit
                    ? 'AI로 채우기 (오늘 사용량 소진)'
                    : `AI로 채우기 (${formatWait(aiWait)} 뒤)`
                  : aiQuotaHit
                    ? 'AI로 채우기 (한도 도달)'
                    : 'AI로 채우기'}
            </Button>
            <p className="min-w-0 flex-1 text-xs text-muted">
              제목·마감일·메모·주제를 제안만 해요. 저장은 직접 눌러야 돼요.
            </p>
          </div>

          {aiPending && (
            <AiProgress
              label={bodyText.trim() ? 'AI가 붙여넣은 본문을 읽고 있어요…' : 'AI가 페이지를 읽고 있어요…'}
              hint="1분 정도 걸릴 수 있어요. 기다리는 동안 다른 칸은 계속 입력해도 돼요."
              cancelLabel="요청 취소"
              onCancel={extract.cancel}
            />
          )}
          {extract.state.status === 'cancelled' && <p className="text-sm text-muted">AI로 채우기를 취소했어요.</p>}
          {extractError !== null && <AiErrorNotice error={extractError} op="extract" />}
          {aiNotice && <Notice tone="warn">{aiNotice}</Notice>}
          {notFetched === 'fetch' && (
            <Notice tone="warn">
              이 페이지의 본문을 가져오지 못했어요. 아래 '본문 붙여넣기'에 내용을 붙여넣고 다시 'AI로 채우기'를 눌러 주세요.
            </Notice>
          )}
          {notFetched === 'pasted' && (
            <Notice tone="warn">
              붙여넣은 본문으로는 내용을 파악하지 못했어요. 본문을 더 붙여넣고 다시 'AI로 채우기'를 눌러 주세요.
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
              id="ai-body"
              value={bodyText}
              maxLength={BODY_MAX}
              onChange={(e) => setBodyText(e.target.value)}
              rows={6}
              placeholder="페이지 본문을 복사해서 붙여넣으세요. AI로 채우기에만 쓰이고 저장되지 않아요."
              aria-label="본문 붙여넣기"
              aria-describedby="ai-body-count"
              className={cx(textareaCls, 'mt-1 bg-bg')}
            />
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
              <span
                id="ai-body-count"
                className={cx('tabular-nums', bodyText.length >= BODY_MAX ? 'font-medium text-warn' : 'text-muted')}
              >
                {bodyText.length.toLocaleString('ko-KR')} / {BODY_MAX.toLocaleString('ko-KR')}자
                {bodyText.length >= BODY_MAX && ' · 최대 길이예요. 넘는 부분은 들어가지 않아요.'}
              </span>
              {bodyText && (
                <button
                  type="button"
                  onClick={() => setBodyText('')}
                  className="ml-auto min-h-11 text-muted underline hover:text-fg lg:min-h-0"
                >
                  본문 지우기
                </button>
              )}
            </div>
          </details>
        </section>

        {/* 3. 제목 */}
        <div className="space-y-2">
          <Field
            label="제목"
            htmlFor="title"
            badge={
              aiBadge('title') ??
              (preview.status === 'loading' && !title.trim() ? (
                <span className="inline-flex items-center gap-1.5 text-xs text-muted" aria-live="polite">
                  <Spinner className="size-3" />
                  링크에서 제목을 가져오는 중…
                </span>
              ) : titleFromPreview ? (
                <Badge tone="muted">링크에서 가져옴 · 고칠 수 있어요</Badge>
              ) : null)
            }
            hint="비워 두면 링크 주소로 저장돼요."
          >
            <input
              id="title"
              value={title}
              maxLength={TITLE_MAX}
              onChange={(e) => {
                setTitle(e.target.value)
                setTitleFromPreview(false)
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
                    'min-h-11 rounded-md px-3 lg:min-h-8',
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
              maxLength={MEMO_MAX}
              onChange={(e) => {
                setMemo(e.target.value)
                touched('memo')
              }}
              rows={10}
              placeholder={'## 요약\n- 핵심 내용\n\n긴 메모도 괜찮아요.'}
              className={cx(textareaCls, 'font-mono')}
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
          {(save.isError || selectionNotice) && (
            <div className="min-w-0 flex-1 space-y-0.5 text-sm">
              {save.isError && (
                <p role="alert" className="text-danger">
                  {errorMessage(save.error)}
                  {isApiError(save.error, 'invalid_input') && ' 선택을 확인한 뒤 다시 저장해 주세요.'}
                </p>
              )}
              {selectionNotice && (
                <p role="status" className="text-warn">
                  {selectionNotice}
                </p>
              )}
            </div>
          )}
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
      <LeaveDialog
        open={blocker.state === 'blocked'}
        onStay={() => blocker.reset?.()}
        onLeave={() => blocker.proceed?.()}
      />
    </form>
  )
}

/** 제목 미리보기 결과 안내. 실패해도 저장은 막지 않는다 */
function PreviewNotice({ state, titleEmpty, onRetry }: { state: PreviewState; titleEmpty: boolean; onRetry: () => void }) {
  if (state.status === 'done' && !state.gotTitle && titleEmpty)
    return (
      <Notice tone="warn">제목을 자동으로 가져오지 못했어요. 직접 입력해 주세요. (비워 두면 링크 주소로 저장돼요)</Notice>
    )
  if (state.status === 'error' && !isApiError(state.error, 'invalid_input', 'unauthorized'))
    return (
      <Notice tone="warn">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="min-w-0 flex-1">
            링크 정보를 불러오지 못했어요. {errorMessage(state.error)} 제목·출처는 직접 정해도 돼요.
          </span>
          <button type="button" onClick={onRetry} className="min-h-11 text-sm font-medium text-accent underline">
            다시 시도
          </button>
        </div>
      </Notice>
    )
  return null
}

const aiBadgeTopic = (
  <Badge tone="accent">
    <IconSparkles size={12} />
    AI 추천 포함
  </Badge>
)
