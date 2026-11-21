// 저장·수정 화면: 기준값 고정, 목록 다시 받기 실패 시 폼 유지, 저장 실패 뒤 선택 정리.
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createQueryClient, keys } from '../hooks/queries'
import { BrowsePage } from './BrowsePage'
import { ScrapEditorPage } from './ScrapEditorPage'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

type Reply = { status: number; body?: unknown } | Promise<{ status: number; body?: unknown }>
type Handler = (method: string, path: string, body: unknown) => Reply | null

const sources = [
  { id: 3, name: '일반사이트', domain_patterns: [], is_default: true },
  { id: 4, name: '테스트출처', domain_patterns: ['example.com'], is_default: false },
]
let topics = [
  { id: 1, name: 'alpha' },
  { id: 2, name: 'beta' },
]

const scrap1 = {
  id: 1,
  url: 'https://example.com/1',
  title: '가상 제목',
  memo: '처음 메모',
  source: { id: 4, name: '테스트출처' },
  topics: [],
  liked: false,
  due_date: null,
  created_at: '2026-11-20T10:00:00+09:00',
  updated_at: '2026-11-20T10:00:00+09:00',
}

function stubApi(handler: Handler) {
  const calls: { method: string; path: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      const path = String(input).replace(/^\/api/, '')
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      calls.push({ method, path, body })
      const r = (await handler(method, path, body)) ?? (await defaults(method, path))
      return new Response(r.body === undefined ? null : JSON.stringify(r.body), {
        status: r.status,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
  return calls
}

function defaults(method: string, path: string): { status: number; body?: unknown } {
  if (path === '/auth/status') return { status: 200, body: { setup_required: false, logged_in: true } }
  if (path === '/sources') return { status: 200, body: sources }
  if (path === '/topics') return { status: 200, body: topics }
  if (path === '/meta/preview') return { status: 200, body: { title: null, source_id: 3 } }
  if (path.startsWith('/scraps?')) return { status: 200, body: { items: [], next_cursor: null } }
  if (method === 'GET' && path === '/scraps/1') return { status: 200, body: scrap1 }
  return { status: 404, body: { error: { code: 'not_found', message: '없음' } } }
}

function renderAt(path: string): { router: ReturnType<typeof createMemoryRouter>; qc: QueryClient } {
  const qc = createQueryClient()
  const router = createMemoryRouter(
    [
      {
        path: '/',
        element: <BrowsePage view="all" />,
        children: [
          { path: 'scraps/new', element: <ScrapEditorPage /> },
          { path: 'scraps/:id/edit', element: <ScrapEditorPage /> },
          { path: 'scraps/:id', element: <div>상세 화면</div> },
        ],
      },
    ],
    { initialEntries: [path] },
  )
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return { router, qc }
}

describe('수정 기준값', () => {
  it('폼을 연 뒤 다시 받은 값이 바뀌어도 손대지 않은 칸은 PATCH에 넣지 않는다', async () => {
    const calls = stubApi((m, p) => (m === 'PATCH' && p === '/scraps/1' ? { status: 200, body: { ...scrap1, title: '새 제목' } } : null))
    const { qc } = renderAt('/scraps/1/edit')
    const title = (await screen.findByLabelText('제목')) as HTMLInputElement
    // 다른 기기에서 메모가 바뀌어 캐시가 새 값으로 갱신된 상황
    await act(async () => {
      qc.setQueryData(keys.scrap(1), { ...scrap1, memo: '다른 기기에서 바꾼 메모' })
      await new Promise((r) => setTimeout(r, 10))
    })
    fireEvent.change(title, { target: { value: '새 제목' } })
    fireEvent.click(screen.getByRole('button', { name: '저장' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    expect(calls.find((c) => c.method === 'PATCH')!.body).toEqual({ title: '새 제목' })
  })
})

describe('목록 다시 받기 실패', () => {
  it('출처·주제를 다시 받지 못해도 작성 중인 폼은 남기고 알린다', async () => {
    let fail = false
    stubApi((_m, p) =>
      fail && p === '/topics' ? { status: 500, body: { error: { code: 'internal_error', message: '서버 오류가 발생했습니다.' } } } : null,
    )
    const { qc } = renderAt('/scraps/new')
    const url = (await screen.findByLabelText('링크')) as HTMLInputElement
    fireEvent.change(url, { target: { value: 'https://example.com/draft' } })
    fail = true
    await qc.invalidateQueries({ queryKey: keys.topics })
    expect(await screen.findByText(/출처·주제 목록을 새로 불러오지 못했어요/)).toBeTruthy()
    expect((screen.getByLabelText('링크') as HTMLInputElement).value).toBe('https://example.com/draft')
  })
})

describe('저장 실패 뒤 선택 정리', () => {
  it('목록을 다시 받는 동안 바꾼 선택은 유지하고, 지워진 주제만 뺀다', async () => {
    topics = [
      { id: 1, name: 'alpha' },
      { id: 2, name: 'beta' },
    ]
    let releaseTopics: () => void = () => {}
    let afterSave = false
    stubApi((m, p) => {
      if (m === 'POST' && p === '/scraps') {
        afterSave = true
        return { status: 400, body: { error: { code: 'invalid_input', message: '없는 주제가 포함되어 있습니다.' } } }
      }
      if (afterSave && p === '/topics') {
        // 다시 받는 응답을 잠시 붙잡아 둔다. 그동안 사용자가 선택을 바꾼다
        return new Promise((resolve) => {
          releaseTopics = () => resolve({ status: 200, body: [{ id: 2, name: 'beta' }] })
        })
      }
      return null
    })
    renderAt('/scraps/new')
    fireEvent.change(await screen.findByLabelText('링크'), { target: { value: 'https://example.com/x' } })
    // 목록 쪽 주제 필터 칩과 구분하려고 편집 패널 안에서만 찾는다
    const panel = within(screen.getByRole('region', { name: '상세' }))
    fireEvent.click(panel.getByRole('button', { name: /#alpha/ }))
    fireEvent.click(screen.getByRole('button', { name: '저장' }))
    expect(await screen.findByText(/없는 주제가 포함되어 있습니다/)).toBeTruthy()
    await waitFor(() => expect(afterSave).toBe(true))
    // 다시 받는 중에 beta를 고른다
    fireEvent.click(panel.getByRole('button', { name: /#beta/ }))
    releaseTopics()
    expect(await screen.findByText(/지워진 주제 1개를 뺐어요/)).toBeTruthy()
    await waitFor(() => expect(panel.queryByRole('button', { name: /#alpha/ })).toBeNull())
    expect(panel.getByRole('button', { name: /#beta/ }).getAttribute('aria-pressed')).toBe('true')
  })
})
