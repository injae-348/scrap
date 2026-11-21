// AI로 채우기·AI 검색 화면: 제안만 채우기, 덮어쓰기 확인, 주제 제안, 본문 붙여넣기, 진행·취소, 오류 코드.
// 테스트 데이터는 모두 가짜 주소·제목이다.
import { QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createQueryClient } from '../hooks/queries'
import { BrowsePage } from './BrowsePage'
import { ScrapEditorPage } from './ScrapEditorPage'
import { SearchPage } from './SearchPage'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

type Res = { status: number; body?: unknown; headers?: Record<string, string> }
type Handler = (method: string, path: string, body: unknown) => Res | Promise<Res> | null
interface Call {
  method: string
  path: string
  body: unknown
  signal?: AbortSignal
}

const sources = [{ id: 3, name: '일반사이트', domain_patterns: [], is_default: true }]
const topics = [
  { id: 1, name: 'Alpha' },
  { id: 2, name: 'beta' },
]

/** 취소 신호를 지키는 fetch 대역. 취소되면 브라우저처럼 AbortError로 끝난다 */
function stubApi(handler: Handler) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(
      (input: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((resolve, reject) => {
          const method = init?.method ?? 'GET'
          const path = String(input).replace(/^\/api/, '')
          const body = init?.body ? JSON.parse(String(init.body)) : undefined
          const signal = init?.signal ?? undefined
          calls.push({ method, path, body, signal })
          signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
          void Promise.resolve(handler(method, path, body) ?? defaults(path)).then((r) => {
            if (signal?.aborted) return
            resolve(
              new Response(r.body === undefined ? null : JSON.stringify(r.body), {
                status: r.status,
                headers: { 'Content-Type': 'application/json', ...r.headers },
              }),
            )
          })
        }),
    ),
  )
  return calls
}

function defaults(path: string): Res {
  if (path === '/auth/status') return { status: 200, body: { setup_required: false, logged_in: true } }
  if (path === '/sources') return { status: 200, body: sources }
  if (path === '/topics') return { status: 200, body: topics }
  if (path === '/meta/preview') return { status: 200, body: { title: null, source_id: 3 } }
  if (path.startsWith('/scraps?')) return { status: 200, body: { items: [], next_cursor: null } }
  return { status: 404, body: { error: { code: 'not_found', message: '없음' } } }
}

/** 응답을 붙잡아 두었다가 원하는 때 보낸다 */
function deferred() {
  let release: (r: Res) => void = () => {}
  const promise = new Promise<Res>((r) => (release = r))
  return { promise, release }
}

const ok = (body: unknown): Res => ({ status: 200, body })
const aiError = (status: number, code: string, message: string, headers?: Record<string, string>): Res => ({
  status,
  body: { error: { code, message } },
  headers,
})

function renderEditor() {
  const qc = createQueryClient()
  const router = createMemoryRouter(
    [
      {
        path: '/',
        element: <BrowsePage view="all" />,
        children: [
          { path: 'scraps/new', element: <ScrapEditorPage /> },
          { path: 'scraps/:id', element: <div>상세 화면</div> },
        ],
      },
    ],
    { initialEntries: ['/scraps/new'] },
  )
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return router
}

const panel = () => within(screen.getByRole('region', { name: '상세' }))

async function startEditor(url = 'https://example.com/post') {
  const router = renderEditor()
  fireEvent.change(await screen.findByLabelText('링크'), { target: { value: url } })
  return router
}

const clickAi = () => fireEvent.click(panel().getByRole('button', { name: /AI로 채우기/ }))
const fullResult = {
  title: '가상 AI 제목',
  due_date: '2026-12-31',
  memo: '## 요약\n- 가상 내용',
  topic_suggestions: ['alpha', '새주제'],
  content_fetched: true,
}

describe('AI로 채우기: 제안만 채운다', () => {
  it('빈 칸은 채우고, 기존 주제는 대소문자 무시로 고르고, 없는 주제는 "새 주제 제안"으로만 보여 준다', async () => {
    const calls = stubApi((m, p) => (m === 'POST' && p === '/ai/extract' ? ok(fullResult) : null))
    await startEditor()
    clickAi()
    expect(await screen.findByText(/AI 제안을 채웠어요/)).toBeTruthy()
    expect((screen.getByLabelText('제목') as HTMLInputElement).value).toBe('가상 AI 제목')
    expect((screen.getByLabelText(/마감일/) as HTMLInputElement).value).toBe('2026-12-31')
    expect((screen.getByLabelText('메모') as HTMLTextAreaElement).value).toBe('## 요약\n- 가상 내용')
    expect(panel().getByRole('button', { name: /#Alpha/ }).getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByText('새 주제 제안')).toBeTruthy()
    expect(screen.getByRole('button', { name: '새 주제 새주제 추가' })).toBeTruthy()
    // 저장·주제 생성은 사용자가 누르기 전에는 하지 않는다
    expect(calls.some((c) => c.method === 'POST' && (c.path === '/scraps' || c.path === '/topics'))).toBe(false)
    expect(calls.find((c) => c.path === '/ai/extract')!.body).toEqual({ url: 'https://example.com/post' })
  })

  it('이미 입력한 칸은 덮어쓰지 않고 확인 상자로 보여 준다', async () => {
    stubApi((m, p) => (m === 'POST' && p === '/ai/extract' ? ok(fullResult) : null))
    await startEditor()
    fireEvent.change(screen.getByLabelText('제목'), { target: { value: '내가 쓴 제목' } })
    clickAi()
    expect(await screen.findByText('AI 제안 (아직 적용 안 됨)')).toBeTruthy()
    expect((screen.getByLabelText('제목') as HTMLInputElement).value).toBe('내가 쓴 제목')
    fireEvent.click(screen.getByRole('button', { name: '이 제안으로 바꾸기' }))
    expect((screen.getByLabelText('제목') as HTMLInputElement).value).toBe('가상 AI 제목')
  })

  it('기다리는 동안 입력한 값은 응답이 와도 덮어쓰지 않는다 (입력을 막지 않음)', async () => {
    const d = deferred()
    stubApi((m, p) => (m === 'POST' && p === '/ai/extract' ? d.promise : null))
    await startEditor()
    clickAi()
    expect(await screen.findByText('AI가 페이지를 읽고 있어요…')).toBeTruthy()
    const title = screen.getByLabelText('제목') as HTMLInputElement
    expect(title.disabled).toBe(false)
    fireEvent.change(title, { target: { value: '기다리며 쓴 제목' } })
    await act(async () => d.release(ok(fullResult)))
    expect(await screen.findByText('AI 제안 (아직 적용 안 됨)')).toBeTruthy()
    expect(title.value).toBe('기다리며 쓴 제목')
  })
})

describe('AI로 채우기: 본문 붙여넣기', () => {
  it('content_fetched:false면 본문 붙여넣기를 열고 안내한다', async () => {
    stubApi((m, p) =>
      m === 'POST' && p === '/ai/extract'
        ? ok({ title: null, due_date: null, memo: null, topic_suggestions: [], content_fetched: false })
        : null,
    )
    await startEditor()
    clickAi()
    expect(await screen.findByText(/본문을 가져오지 못했어요/)).toBeTruthy()
    const body = screen.getByLabelText('본문 붙여넣기')
    expect((body.closest('details') as HTMLDetailsElement).open).toBe(true)
    expect(screen.queryByText(/AI 제안을 채웠어요/)).toBeNull()
  })

  it('붙여넣은 본문은 50,000자로 제한·표시하고, 제어문자를 지워 text로 보낸다', async () => {
    const calls = stubApi((m, p) => (m === 'POST' && p === '/ai/extract' ? ok(fullResult) : null))
    await startEditor()
    const body = screen.getByLabelText('본문 붙여넣기') as HTMLTextAreaElement
    expect(body.maxLength).toBe(50_000)
    fireEvent.change(body, { target: { value: '  가상 본문\u0000 내용\n둘째 줄  ' } })
    expect(document.getElementById('ai-body-count')!.textContent).toBe('18 / 50,000자')
    clickAi()
    await screen.findByText(/AI 제안을 채웠어요/)
    expect(calls.find((c) => c.path === '/ai/extract')!.body).toEqual({
      url: 'https://example.com/post',
      text: '가상 본문 내용\n둘째 줄',
    })
  })

  it('붙여넣은 본문이 너무 길면(413) 전용 문구', async () => {
    stubApi((m, p) =>
      m === 'POST' && p === '/ai/extract' ? aiError(413, 'payload_too_large', '요청 본문이 너무 큽니다.') : null,
    )
    await startEditor()
    fireEvent.change(screen.getByLabelText('본문 붙여넣기'), { target: { value: '가상 본문' } })
    clickAi()
    expect(await screen.findByText('붙여넣은 본문이 너무 길어요.')).toBeTruthy()
  })
})

describe('AI로 채우기: 진행·취소', () => {
  it('취소 버튼은 요청을 멈추고, 늦게 온 응답은 쓰지 않는다', async () => {
    const d = deferred()
    const calls = stubApi((m, p) => (m === 'POST' && p === '/ai/extract' ? d.promise : null))
    await startEditor()
    clickAi()
    fireEvent.click(await screen.findByRole('button', { name: '요청 취소' }))
    const call = calls.find((c) => c.path === '/ai/extract')!
    expect(call.signal?.aborted).toBe(true)
    expect(await screen.findByText('AI로 채우기를 취소했어요.')).toBeTruthy()
    await act(async () => d.release(ok(fullResult)))
    expect((screen.getByLabelText('제목') as HTMLInputElement).value).toBe('')
  })

  it('화면을 떠나면 요청을 취소한다', async () => {
    const d = deferred()
    const calls = stubApi((m, p) => (m === 'POST' && p === '/ai/extract' ? d.promise : null))
    const router = await startEditor()
    clickAi()
    await screen.findByRole('button', { name: '요청 취소' })
    await act(async () => {
      void router.navigate('/')
    })
    // 작성 중이라 이탈 확인이 뜬다 → 나가기
    fireEvent.click(await screen.findByRole('button', { name: '나가기' }))
    await waitFor(() => expect(calls.find((c) => c.path === '/ai/extract')!.signal?.aborted).toBe(true))
  })
})

describe('AI로 채우기: 오류 코드', () => {
  it('503 ai_unavailable → 서버 설정 필요', async () => {
    stubApi((m, p) => (m === 'POST' && p === '/ai/extract' ? aiError(503, 'ai_unavailable', 'x') : null))
    await startEditor()
    clickAi()
    expect(await screen.findByText('AI 기능을 사용할 수 없어요 (서버 설정 필요)')).toBeTruthy()
  })

  it('503 ai_quota_exceeded → 서버 message, 설정 필요 문구와 구분', async () => {
    stubApi((m, p) =>
      m === 'POST' && p === '/ai/extract' ? aiError(503, 'ai_quota_exceeded', '이번 달 AI 사용 한도에 도달했어요.') : null,
    )
    await startEditor()
    clickAi()
    expect(await screen.findByText('이번 달 AI 사용 한도에 도달했어요.')).toBeTruthy()
    expect(screen.queryByText(/서버 설정 필요/)).toBeNull()
    expect(screen.queryByText(/다시 시도할 수 있어요/)).toBeNull()
  })

  it('502 ai_failed → 서버 message', async () => {
    const msg = 'AI 응답을 받지 못했어요. 잠시 후 다시 시도해 주세요.'
    stubApi((m, p) => (m === 'POST' && p === '/ai/extract' ? aiError(502, 'ai_failed', msg) : null))
    await startEditor()
    clickAi()
    expect(await screen.findByText(msg)).toBeTruthy()
  })

  it('429 → Retry-After 동안 버튼을 막고 남은 시간을 보여 준다', async () => {
    stubApi((m, p) =>
      m === 'POST' && p === '/ai/extract'
        ? aiError(429, 'too_many_requests', 'AI 요청이 너무 많아요.', { 'Retry-After': '30' })
        : null,
    )
    await startEditor()
    clickAi()
    expect(await screen.findByText(/30초 뒤에 다시 시도할 수 있어요/)).toBeTruthy()
    const btn = panel().getByRole('button', { name: /AI로 채우기/ }) as HTMLButtonElement
    expect(btn.disabled).toBe(true)
    expect(btn.textContent).toContain('30초 뒤')
  })
})

describe('AI로 채우기: 하루 사용량 소진 (429 ai_daily_limit)', () => {
  const DAILY_MSG = '오늘 AI 사용량을 모두 썼어요. 내일 다시 시도해 주세요.'

  it('서버 message만 보여 주고 남은 시간·다시 시도 없이 버튼을 소진 표시로 막는다', async () => {
    stubApi((m, p) =>
      m === 'POST' && p === '/ai/extract' ? aiError(429, 'ai_daily_limit', DAILY_MSG, { 'Retry-After': '36000' }) : null,
    )
    await startEditor()
    clickAi()
    expect(await screen.findByText(DAILY_MSG)).toBeTruthy()
    expect(screen.queryByText(/뒤에 다시 시도할 수 있어요/)).toBeNull()
    expect(screen.queryByRole('button', { name: '다시 시도' })).toBeNull()
    const btn = panel().getByRole('button', { name: /AI로 채우기/ }) as HTMLButtonElement
    expect(btn.disabled).toBe(true)
    expect(btn.textContent).toContain('오늘 사용량 소진')
    expect(btn.textContent).not.toContain('시간')
  })

  it('ai_daily_limit은 Retry-After가 작아도(자정 직전) 소진 표시', async () => {
    stubApi((m, p) =>
      m === 'POST' && p === '/ai/extract' ? aiError(429, 'ai_daily_limit', DAILY_MSG, { 'Retry-After': '30' }) : null,
    )
    await startEditor()
    clickAi()
    expect(await screen.findByText(DAILY_MSG)).toBeTruthy()
    expect(screen.queryByText(/뒤에 다시 시도할 수 있어요/)).toBeNull()
    const btn = panel().getByRole('button', { name: /AI로 채우기/ }) as HTMLButtonElement
    expect(btn.disabled).toBe(true)
    expect(btn.textContent).toContain('오늘 사용량 소진')
  })

  it('too_many_requests는 Retry-After가 커도 일반 429 표시 (남은 시간)', async () => {
    stubApi((m, p) =>
      m === 'POST' && p === '/ai/extract'
        ? aiError(429, 'too_many_requests', 'AI 요청이 너무 많아요.', { 'Retry-After': '3600' })
        : null,
    )
    await startEditor()
    clickAi()
    expect(await screen.findByText(/1시간 뒤에 다시 시도할 수 있어요/)).toBeTruthy()
    expect(panel().getByRole('button', { name: /AI로 채우기/ }).textContent).toContain('1시간 뒤')
  })
})

// ------------------------------------------------------------------ AI 검색
const listItem = {
  id: 7,
  url: 'https://example.com/contest',
  title: '가상 공모전 안내',
  memo_preview: '가상 메모 앞부분',
  source: { id: 3, name: '일반사이트' },
  topics: [{ id: 1, name: 'Alpha' }],
  liked: false,
  due_date: null,
  created_at: '2026-11-20T10:00:00+09:00',
  updated_at: '2026-11-20T10:00:00+09:00',
}

function mountSearch(path: string) {
  const qc = createQueryClient()
  const router = createMemoryRouter(
    [
      { path: '/search', element: <SearchPage />, children: [{ path: 'scraps/:id', element: <div>상세 화면</div> }] },
      { path: '/other', element: <div>다른 화면</div> },
    ],
    { initialEntries: [path] },
  )
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return router
}

/** 검색 화면을 열고 질문을 입력해 검색 버튼을 누른다 */
async function renderSearch(question = '가상 질문') {
  const router = mountSearch('/search')
  fireEvent.change(await screen.findByLabelText('AI에게 질문'), { target: { value: question } })
  fireEvent.submit(screen.getByRole('search'))
  return router
}

describe('AI 검색', () => {
  it('결과 카드는 ScrapListItem과 이유를 보여 준다', async () => {
    const calls = stubApi((m, p) =>
      m === 'POST' && p === '/ai/search'
        ? ok({ answer: '가상 요약 답변', results: [{ scrap: listItem, reason: '가상 이유' }] })
        : null,
    )
    await renderSearch()
    expect(await screen.findByText('가상 공모전 안내')).toBeTruthy()
    expect(screen.getByText('가상 요약 답변')).toBeTruthy()
    expect(screen.getByText('가상 이유')).toBeTruthy()
    expect(screen.getByRole('link', { name: /가상 공모전 안내/ }).getAttribute('href')).toBe(
      '/search/scraps/7?q=' + encodeURIComponent('가상 질문'),
    )
    expect(calls.find((c) => c.path === '/ai/search')!.body).toEqual({ query: '가상 질문' })
  })

  it('검색 취소: 요청을 멈추고 질문 입력 상태로 돌아간다', async () => {
    const d = deferred()
    const calls = stubApi((m, p) => (m === 'POST' && p === '/ai/search' ? d.promise : null))
    const router = await renderSearch()
    fireEvent.click(await screen.findByRole('button', { name: '검색 취소' }))
    await waitFor(() => expect(calls.find((c) => c.path === '/ai/search')!.signal?.aborted).toBe(true))
    expect(await screen.findByText(/검색을 취소했어요/)).toBeTruthy()
    expect(router.state.location.search).toBe('')
    expect((screen.getByLabelText('AI에게 질문') as HTMLInputElement).value).toBe('가상 질문')
  })

  it('화면을 떠나면 요청을 취소한다', async () => {
    const d = deferred()
    const calls = stubApi((m, p) => (m === 'POST' && p === '/ai/search' ? d.promise : null))
    const router = await renderSearch()
    await screen.findByRole('button', { name: '검색 취소' })
    await act(async () => {
      void router.navigate('/other')
    })
    await waitFor(() => expect(calls.find((c) => c.path === '/ai/search')!.signal?.aborted).toBe(true))
  })

  it('429 → 남은 시간 동안 다시 시도 버튼을 막는다', async () => {
    stubApi((m, p) =>
      m === 'POST' && p === '/ai/search'
        ? aiError(429, 'too_many_requests', 'AI 요청이 너무 많아요.', { 'Retry-After': '45' })
        : null,
    )
    await renderSearch()
    expect(await screen.findByText(/45초 뒤에 다시 시도할 수 있어요/)).toBeTruthy()
    expect((screen.getByRole('button', { name: '다시 시도' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('502 ai_failed → 서버 message와 다시 시도', async () => {
    const msg = 'AI 응답을 받지 못했어요. 잠시 후 다시 시도해 주세요.'
    stubApi((m, p) => (m === 'POST' && p === '/ai/search' ? aiError(502, 'ai_failed', msg) : null))
    await renderSearch()
    expect(await screen.findByText(msg)).toBeTruthy()
    expect((screen.getByRole('button', { name: '다시 시도' }) as HTMLButtonElement).disabled).toBe(false)
  })

  it('503 ai_unavailable → 서버 설정 필요, 다시 시도 버튼 없음', async () => {
    stubApi((m, p) => (m === 'POST' && p === '/ai/search' ? aiError(503, 'ai_unavailable', 'x') : null))
    await renderSearch()
    expect(await screen.findByText('AI 기능을 사용할 수 없어요 (서버 설정 필요)')).toBeTruthy()
    expect(screen.queryByRole('button', { name: '다시 시도' })).toBeNull()
  })

  it('503 ai_quota_exceeded → 서버 message, 다시 시도·카운트다운 없음 (설정 필요와 구분)', async () => {
    stubApi((m, p) =>
      m === 'POST' && p === '/ai/search' ? aiError(503, 'ai_quota_exceeded', '이번 달 AI 사용 한도에 도달했어요.') : null,
    )
    await renderSearch()
    expect(await screen.findByText('이번 달 AI 사용 한도에 도달했어요.')).toBeTruthy()
    expect(screen.queryByText(/서버 설정 필요/)).toBeNull()
    expect(screen.queryByRole('button', { name: '다시 시도' })).toBeNull()
    expect(screen.queryByText(/다시 시도할 수 있어요/)).toBeNull()
  })
})

describe('AI 검색: 하루 사용량 소진 (429 ai_daily_limit)', () => {
  const DAILY_MSG = '오늘 AI 요청 횟수를 모두 썼어요. 내일 다시 시도해 주세요.'

  it('ai_daily_limit은 Retry-After가 작아도 서버 message만, 다시 시도 버튼·남은 시간 없음', async () => {
    stubApi((m, p) =>
      m === 'POST' && p === '/ai/search' ? aiError(429, 'ai_daily_limit', DAILY_MSG, { 'Retry-After': '30' }) : null,
    )
    await renderSearch()
    expect(await screen.findByText(DAILY_MSG)).toBeTruthy()
    expect(screen.queryByRole('button', { name: '다시 시도' })).toBeNull()
    expect(screen.queryByText(/다시 시도할 수 있어요/)).toBeNull()
  })

  it('Retry-After가 지날 때까지 검색 버튼·예시 질문을 막고 요청을 보내지 않는다', async () => {
    const calls = stubApi((m, p) =>
      m === 'POST' && p === '/ai/search' ? aiError(429, 'ai_daily_limit', DAILY_MSG, { 'Retry-After': '3600' }) : null,
    )
    const router = await renderSearch()
    expect(await screen.findByText(DAILY_MSG)).toBeTruthy()
    const searchBtn = () => screen.getByRole('button', { name: '검색' }) as HTMLButtonElement
    fireEvent.change(screen.getByLabelText('AI에게 질문'), { target: { value: '다른 가상 질문' } })
    expect(searchBtn().disabled).toBe(true)
    fireEvent.submit(screen.getByRole('search'))
    // 질문 목록 화면으로 돌아가도 소진 안내가 남고 예시 질문은 막힌다
    await act(async () => {
      void router.navigate('/search')
    })
    expect(await screen.findByText(DAILY_MSG)).toBeTruthy()
    const chip = screen.getByRole('button', { name: '도커 관련 정리 글' }) as HTMLButtonElement
    expect(chip.disabled).toBe(true)
    fireEvent.click(chip)
    expect(searchBtn().disabled).toBe(true)
    expect(calls.filter((c) => c.path === '/ai/search')).toHaveLength(1)
  })

  it('Retry-After가 지나면 다시 검색할 수 있다', async () => {
    const calls = stubApi((m, p) =>
      m === 'POST' && p === '/ai/search' ? aiError(429, 'ai_daily_limit', DAILY_MSG, { 'Retry-After': '1' }) : null,
    )
    await renderSearch()
    expect(await screen.findByText(DAILY_MSG)).toBeTruthy()
    const searchBtn = () => screen.getByRole('button', { name: '검색' }) as HTMLButtonElement
    expect(searchBtn().disabled).toBe(true)
    await waitFor(() => expect(searchBtn().disabled).toBe(false), { timeout: 3000 })
    expect(screen.queryByRole('button', { name: '다시 시도' })).toBeNull()
    fireEvent.change(screen.getByLabelText('AI에게 질문'), { target: { value: '다른 가상 질문' } })
    fireEvent.submit(screen.getByRole('search'))
    await waitFor(() => expect(calls.filter((c) => c.path === '/ai/search')).toHaveLength(2))
  })

  it('too_many_requests는 Retry-After가 커도 남은 시간 동안 다시 시도 버튼을 막는다', async () => {
    stubApi((m, p) =>
      m === 'POST' && p === '/ai/search'
        ? aiError(429, 'too_many_requests', 'AI 요청이 너무 많아요.', { 'Retry-After': '3600' })
        : null,
    )
    await renderSearch()
    expect(await screen.findByText(/1시간 뒤에 다시 시도할 수 있어요/)).toBeTruthy()
    expect((screen.getByRole('button', { name: '다시 시도' }) as HTMLButtonElement).disabled).toBe(true)
  })
})

describe('AI 검색: 입력 한도·입력 오류·자동 재전송', () => {
  it('질문 입력칸은 200자 제한', async () => {
    stubApi(() => null)
    mountSearch('/search')
    expect((await screen.findByLabelText('AI에게 질문') as HTMLInputElement).maxLength).toBe(200)
  })

  it('400 invalid_input에는 "다시 시도" 버튼을 두지 않는다', async () => {
    stubApi((m, p) =>
      m === 'POST' && p === '/ai/search' ? aiError(400, 'invalid_input', '질문은 1~200자로 입력해 주세요.') : null,
    )
    await renderSearch()
    expect(await screen.findByText('질문은 1~200자로 입력해 주세요.')).toBeTruthy()
    expect(screen.queryByRole('button', { name: '다시 시도' })).toBeNull()
  })

  it('주소에 ?q=만 있는 상태(새로고침·복원)에서는 자동으로 보내지 않고, 눌렀을 때만 보낸다', async () => {
    const calls = stubApi((m, p) =>
      m === 'POST' && p === '/ai/search' ? ok({ answer: '가상 답변', results: [{ scrap: listItem, reason: '가상 이유' }] }) : null,
    )
    mountSearch('/search?q=' + encodeURIComponent('복원된 질문'))
    const run = await screen.findByRole('button', { name: /이 질문으로 검색/ })
    await act(async () => new Promise((r) => setTimeout(r, 20)))
    expect(calls.some((c) => c.path === '/ai/search')).toBe(false)
    fireEvent.click(run)
    expect(await screen.findByText('가상 이유')).toBeTruthy()
    expect(calls.filter((c) => c.path === '/ai/search')).toHaveLength(1)
    expect(calls.find((c) => c.path === '/ai/search')!.body).toEqual({ query: '복원된 질문' })
  })

  it('오류 뒤 같은 질문으로 검색 버튼을 누르면 다시 보낸다', async () => {
    let n = 0
    const calls = stubApi((m, p) => {
      if (m !== 'POST' || p !== '/ai/search') return null
      n += 1
      return n === 1 ? aiError(502, 'ai_failed', '가상 실패') : ok({ answer: '가상 답변', results: [] })
    })
    await renderSearch()
    expect(await screen.findByText('가상 실패')).toBeTruthy()
    fireEvent.submit(screen.getByRole('search'))
    expect(await screen.findByText('가상 답변')).toBeTruthy()
    expect(calls.filter((c) => c.path === '/ai/search')).toHaveLength(2)
  })
})

describe('AI로 채우기: 빈 제안·한도 도달 표시', () => {
  it('채울 내용을 하나도 못 찾으면 안내한다', async () => {
    stubApi((m, p) =>
      m === 'POST' && p === '/ai/extract'
        ? ok({ title: null, due_date: null, memo: null, topic_suggestions: [], content_fetched: true })
        : null,
    )
    await startEditor()
    clickAi()
    expect(await screen.findByText(/AI가 이 페이지에서 채울 만한 내용을 찾지 못했어요/)).toBeTruthy()
    expect(screen.queryByText(/AI 제안을 채웠어요/)).toBeNull()
  })

  it('한도 도달을 받으면 AI 버튼에 표시한다 (다시 누르는 것은 허용)', async () => {
    stubApi((m, p) =>
      m === 'POST' && p === '/ai/extract' ? aiError(503, 'ai_quota_exceeded', '이번 달 AI 사용 한도에 도달했어요.') : null,
    )
    await startEditor()
    clickAi()
    await screen.findByText('이번 달 AI 사용 한도에 도달했어요.')
    const btn = panel().getByRole('button', { name: /AI로 채우기/ }) as HTMLButtonElement
    expect(btn.textContent).toContain('한도 도달')
    expect(btn.disabled).toBe(false)
  })
})
