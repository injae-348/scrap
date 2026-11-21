// 목록·상세 화면: 입력 오류 복구, 다시 받기 실패 시 화면 유지, 표시 텍스트 정리.
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createQueryClient, keys } from '../hooks/queries'
import { BrowsePage } from './BrowsePage'
import { ScrapDetailPage } from './ScrapDetailPage'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

type Reply = { status: number; body?: unknown }
type Handler = (method: string, path: string) => Reply

function stubApi(handler: Handler) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const r = handler(init?.method ?? 'GET', String(input).replace(/^\/api/, ''))
      return new Response(r.body === undefined ? null : JSON.stringify(r.body), {
        status: r.status,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
}

const item = (id: number, title: string) => ({
  id,
  url: `https://example.com/${id}`,
  title,
  memo_preview: '',
  source: { id: 3, name: '일반사이트' },
  topics: [],
  liked: false,
  due_date: null,
  created_at: '2026-11-20T10:00:00+09:00',
  updated_at: '2026-11-20T10:00:00+09:00',
})

function common(path: string): Reply | null {
  if (path === '/auth/status') return { status: 200, body: { setup_required: false, logged_in: true } }
  if (path === '/sources') return { status: 200, body: [{ id: 3, name: '일반사이트', domain_patterns: [], is_default: true }] }
  if (path === '/topics') return { status: 200, body: [] }
  return null
}

function renderAt(path: string): { router: ReturnType<typeof createMemoryRouter>; qc: QueryClient } {
  const qc = createQueryClient()
  const router = createMemoryRouter(
    [{ path: '/', element: <BrowsePage view="all" />, children: [{ path: 'scraps/:id', element: <ScrapDetailPage /> }] }],
    { initialEntries: [path] },
  )
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return { router, qc }
}

describe('목록 입력 오류', () => {
  it('400 invalid_input이면 서버 문구와 "검색어·필터 지우기"를 보여 주고, 누르면 필터를 지운다', async () => {
    stubApi((_m, p) => {
      const c = common(p)
      if (c) return c
      if (p.startsWith('/scraps?') && p.includes('q=')) {
        return { status: 400, body: { error: { code: 'invalid_input', message: '검색어는 최대 10단어까지 입력할 수 있습니다.' } } }
      }
      return { status: 200, body: { items: [item(1, '가상 제목')], next_cursor: null } }
    })
    const { router } = renderAt('/?q=a+b+c&source=3')
    expect(await screen.findByText('검색어는 최대 10단어까지 입력할 수 있습니다.')).toBeTruthy()
    expect(screen.queryByRole('button', { name: '다시 시도' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: '검색어·필터 지우기' }))
    await waitFor(() => expect(router.state.location.search).toBe(''))
    expect(await screen.findByText('가상 제목')).toBeTruthy()
  })
})

describe('다시 받기 실패', () => {
  it('받아 둔 목록이 있으면 목록을 유지하고 한 줄로 알린다', async () => {
    let fail = false
    stubApi((_m, p) => {
      const c = common(p)
      if (c) return c
      if (fail) return { status: 500, body: { error: { code: 'internal_error', message: '서버 오류가 발생했습니다.' } } }
      return { status: 200, body: { items: [item(1, '가상 제목 하나')], next_cursor: null } }
    })
    const { qc } = renderAt('/')
    expect(await screen.findByText('가상 제목 하나')).toBeTruthy()
    fail = true
    await qc.invalidateQueries({ queryKey: keys.scrapLists })
    expect(await screen.findByText(/최신 목록을 불러오지 못했어요/)).toBeTruthy()
    expect(screen.getByText('가상 제목 하나')).toBeTruthy()
  })

  it('받아 둔 목록이 없으면 오류 화면 + 다시 시도', async () => {
    stubApi((_m, p) => common(p) ?? { status: 500, body: { error: { code: 'internal_error', message: '서버 오류가 발생했습니다.' } } })
    renderAt('/')
    expect(await screen.findByRole('button', { name: '다시 시도' })).toBeTruthy()
  })

  it('상세도 받아 둔 내용이 있으면 유지한다', async () => {
    let fail = false
    stubApi((_m, p) => {
      const c = common(p)
      if (c) return c
      if (p === '/scraps/1') {
        if (fail) return { status: 500, body: { error: { code: 'internal_error', message: '서버 오류가 발생했습니다.' } } }
        return { status: 200, body: { ...item(1, '상세 가상 제목'), memo: '메모 본문' } }
      }
      return { status: 200, body: { items: [], next_cursor: null } }
    })
    const { qc } = renderAt('/scraps/1')
    expect(await screen.findByRole('heading', { name: '상세 가상 제목' })).toBeTruthy()
    fail = true
    await qc.invalidateQueries({ queryKey: keys.scrap(1) })
    expect(await screen.findByText(/최신 내용을 불러오지 못했어요/)).toBeTruthy()
    expect(screen.getByRole('heading', { name: '상세 가상 제목' })).toBeTruthy()
  })
})

describe('표시 텍스트', () => {
  it('목록 제목의 글자 방향 서식 문자는 지우고 보여 준다', async () => {
    stubApi((_m, p) => common(p) ?? { status: 200, body: { items: [item(1, '가상‮제목؜')], next_cursor: null } })
    renderAt('/')
    expect(await screen.findByText('가상제목')).toBeTruthy()
  })
})
