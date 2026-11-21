// 인증 화면 스모크 테스트: 상태별 분기, 입력칸 속성(iOS), 오류 코드 처리.
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'
import { request } from '../api/http'
import { LeaveDialog } from '../components/ui'
import { useLeaveGuard } from '../hooks/useLeaveGuard'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppLayout } from '../components/AppLayout'
import { createQueryClient, keys, useSources } from '../hooks/queries'
import { LoginPage } from './LoginPage'
import { SetupPage } from './SetupPage'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

type Handler = (method: string, path: string, body: unknown) => { status: number; body?: unknown; headers?: Record<string, string> }

function stubApi(handler: Handler) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    const r = handler(init?.method ?? 'GET', url.replace(/^\/api/, ''), init?.body ? JSON.parse(String(init.body)) : undefined)
    return new Response(r.body === undefined ? null : JSON.stringify(r.body), {
      status: r.status,
      headers: { 'Content-Type': 'application/json', ...r.headers },
    })
  })
  vi.stubGlobal('fetch', fn)
  return fn
}

function renderAt(path: string, qc: QueryClient = createQueryClient()) {
  const router = createMemoryRouter(
    [
      { path: '/setup', element: <SetupPage /> },
      { path: '/login', element: <LoginPage /> },
      {
        element: <AppLayout />,
        children: [
          { path: '/', element: <div>앱 화면</div> },
          { path: '/sources', element: <SourcesProbe /> },
          { path: '/scraps/new', element: <EditProbe /> },
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
  return router
}

function SourcesProbe() {
  const q = useSources()
  return <div>{q.isError ? '출처 오류' : '출처 화면'}</div>
}

/** 작성 중인 편집 화면 흉내: 이탈 가드 + 데이터 요청 버튼 + 다른 화면 링크 */
function EditProbe() {
  const [text, setText] = useState('작성 중인 메모')
  const { blocker } = useLeaveGuard(true)
  useSources()
  return (
    <div>
      <textarea aria-label="메모" value={text} onChange={(e) => setText(e.target.value)} />
      <button type="button" onClick={() => void request('GET', '/topics').catch(() => {})}>
        주제 다시 받기
      </button>
      <Link to="/">목록으로</Link>
      <LeaveDialog open={blocker.state === 'blocked'} onStay={() => blocker.reset?.()} onLeave={() => blocker.proceed?.()} />
    </div>
  )
}

const status200 = { status: 200, body: { setup_required: false, logged_in: true } }
const unauthorized = { status: 401, body: { error: { code: 'unauthorized', message: '로그인이 필요합니다.' } } }

describe('세션 만료 뒤 데이터 정리', () => {
  it('로그인 화면에 들어오면 받아 둔 개인 데이터 캐시를 비운다', async () => {
    stubApi((_m, p) => (p === '/auth/status' ? status200 : unauthorized))
    const qc = createQueryClient()
    qc.setQueryData(keys.topics, [{ id: 1, name: '가상 주제' }])
    qc.setQueryData(keys.scrap(1), { id: 1, title: '가상 제목' })
    const r = renderAt('/sources', qc)
    await waitFor(() => expect(r.state.location.pathname).toBe('/login'))
    await waitFor(() => expect(qc.getQueryData(keys.topics)).toBeUndefined())
    expect(qc.getQueryData(keys.scrap(1))).toBeUndefined()
  })

  it('작성 중 "계속 작성"을 고르면 편집 폼만 남기고, 다시 요청하거나 다른 화면으로 가면 로그인으로 보낸다', async () => {
    stubApi((_m, p) => (p === '/auth/status' ? status200 : unauthorized))
    const r = renderAt('/scraps/new')
    // 첫 401 → 이탈 확인
    fireEvent.click(await screen.findByRole('button', { name: '계속 작성' }))
    expect(r.state.location.pathname).toBe('/scraps/new')
    expect(await screen.findByText(/로그인이 만료됐어요. 작성 중인 내용을 복사해 둔 뒤/)).toBeTruthy()
    expect((screen.getByLabelText('메모') as HTMLTextAreaElement).value).toBe('작성 중인 메모')
    expect(screen.queryByRole('navigation', { name: '주요 메뉴' })).toBeNull()
    expect(screen.queryByRole('navigation', { name: '하단 메뉴' })).toBeNull()

    // 다시 데이터를 요청해 401 → 다시 로그인으로 보내려 한다 (작성 중이라 확인이 또 뜬다)
    fireEvent.click(screen.getByRole('button', { name: '주제 다시 받기' }))
    fireEvent.click(await screen.findByRole('button', { name: '계속 작성' }))
    expect(r.state.location.pathname).toBe('/scraps/new')

    // 다른 화면으로 가면 로그인 화면
    fireEvent.click(screen.getByRole('link', { name: '목록으로' }))
    fireEvent.click(await screen.findByRole('button', { name: '나가기' }))
    await waitFor(() => expect(r.state.location.pathname).toBe('/login'))
  })
})

describe('인증 요청 값이 캐시에 남지 않는다', () => {
  it('로그인 비밀번호·코드는 성공·실패 뒤 뮤테이션 캐시에 없다', async () => {
    const PW = 'very-secret-password-1'
    stubApi((_m, p, body) => {
      if (p === '/auth/status') return { status: 200, body: { setup_required: false, logged_in: false } }
      if (p === '/auth/login') return { status: 200, body: { totp_required: true, challenge_id: 'challenge-x' } }
      const b = body as { code?: string }
      if (b.code === '111111') return { status: 401, body: { error: { code: 'invalid_code', message: '인증 코드가 올바르지 않습니다.' } } }
      return { status: 204 }
    })
    const qc = createQueryClient()
    renderAt('/login', qc)
    fireEvent.change(await screen.findByLabelText('아이디'), { target: { value: 'tester' } })
    fireEvent.change(screen.getByLabelText('비밀번호'), { target: { value: PW } })
    fireEvent.click(screen.getByRole('button', { name: '다음' }))
    const code = await screen.findByLabelText('6자리 코드')
    const cached = () => JSON.stringify(qc.getMutationCache().getAll().map((m) => [m.state.variables, m.state.data]))
    await waitFor(() => expect(cached()).not.toContain(PW))
    expect(cached()).not.toContain('challenge-x')
    fireEvent.change(code, { target: { value: '111111' } })
    expect(await screen.findByText(/인증 코드가 올바르지 않습니다/)).toBeTruthy()
    await waitFor(() => expect(cached()).not.toContain('111111'))
    expect(qc.getMutationCache().getAll()).toHaveLength(0)
  })
})

describe('가입 요청 값이 캐시에 남지 않는다', () => {
  it('가입 토큰·비밀번호·TOTP 비밀값·복구 코드가 뮤테이션 캐시에 없다', async () => {
    stubApi((_m, p) => {
      if (p === '/auth/status') return { status: 200, body: { setup_required: true, logged_in: false } }
      if (p === '/auth/setup') return { status: 200, body: { qr_data_url: 'data:image/svg+xml;base64,AAAA', secret: 'TOTPSECRETVALUE234' } }
      return { status: 200, body: { recovery_codes: ['AAAA-BBBB-CCCC-DDDD'] } }
    })
    const qc = createQueryClient()
    renderAt('/setup', qc)
    fireEvent.change(await screen.findByLabelText('아이디'), { target: { value: 'tester' } })
    fireEvent.change(screen.getByLabelText('비밀번호'), { target: { value: 'setup-password-xyz' } })
    fireEvent.change(screen.getByLabelText('비밀번호 확인'), { target: { value: 'setup-password-xyz' } })
    fireEvent.change(screen.getByLabelText('가입 토큰'), { target: { value: 'setup-token-value-xyz' } })
    fireEvent.click(screen.getByRole('button', { name: '다음' }))
    fireEvent.change(await screen.findByLabelText('6자리 코드'), { target: { value: '123456' } })
    expect(await screen.findByText('AAAA-BBBB-CCCC-DDDD')).toBeTruthy()
    const cached = () => JSON.stringify(qc.getMutationCache().getAll().map((m) => [m.state.variables, m.state.data]))
    await waitFor(() => expect(qc.getMutationCache().getAll()).toHaveLength(0))
    for (const v of ['setup-password-xyz', 'setup-token-value-xyz', 'TOTPSECRETVALUE234', 'AAAA-BBBB-CCCC-DDDD']) {
      expect(cached()).not.toContain(v)
    }
  })
})

describe('사용 중 세션 만료', () => {
  it('401 unauthorized면 로그인 화면으로 보내고 만료 안내', async () => {
    stubApi((_m, p) =>
      p === '/auth/status'
        ? { status: 200, body: { setup_required: false, logged_in: true } }
        : { status: 401, body: { error: { code: 'unauthorized', message: '로그인이 필요합니다.' } } },
    )
    const r = renderAt('/sources')
    await waitFor(() => expect(r.state.location.pathname).toBe('/login'))
    expect(await screen.findByText('로그인이 만료됐어요. 다시 로그인해 주세요.')).toBeTruthy()
  })

  it('다른 401(invalid_credentials)은 로그인 화면으로 보내지 않는다', async () => {
    stubApi((_m, p) =>
      p === '/auth/status'
        ? { status: 200, body: { setup_required: false, logged_in: true } }
        : { status: 401, body: { error: { code: 'invalid_credentials', message: '비밀번호가 올바르지 않습니다.' } } },
    )
    const r = renderAt('/sources')
    expect(await screen.findByText('출처 오류')).toBeTruthy()
    expect(r.state.location.pathname).toBe('/sources')
  })
})

describe('앱 시작 시 /auth/status', () => {
  it('실패하면 재시도 화면 (로그아웃으로 단정하지 않음)', async () => {
    let fail = true
    stubApi(() => (fail ? { status: 503, body: { error: { code: 'db_unavailable', message: '데이터베이스에 연결할 수 없습니다.' } } } : { status: 200, body: { setup_required: false, logged_in: true } }))
    renderAt('/')
    // 503은 한 번 다시 시도(1초 뒤)한 다음 오류 화면
    expect(await screen.findByText(/서버 상태를 확인하지 못했어요/, undefined, { timeout: 4000 })).toBeTruthy()
    fail = false
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }))
    expect(await screen.findByText('앱 화면')).toBeTruthy()
  })

  it('사용자가 없으면 가입 화면, 로그아웃 상태면 로그인 화면', async () => {
    stubApi(() => ({ status: 200, body: { setup_required: true, logged_in: false } }))
    const r = renderAt('/')
    await waitFor(() => expect(r.state.location.pathname).toBe('/setup'))
    cleanup()
    stubApi(() => ({ status: 200, body: { setup_required: false, logged_in: false } }))
    const r2 = renderAt('/')
    await waitFor(() => expect(r2.state.location.pathname).toBe('/login'))
  })
})

describe('가입 화면', () => {
  it('가입 토큰 칸은 비밀번호 형태 + 자동완성 끔, 아이디는 자동 대문자·수정 끔', async () => {
    stubApi(() => ({ status: 200, body: { setup_required: true, logged_in: false } }))
    renderAt('/setup')
    const token = (await screen.findByLabelText('가입 토큰')) as HTMLInputElement
    expect(token.type).toBe('password')
    expect(token.getAttribute('autocomplete')).toBe('off')
    expect(token.name).not.toMatch(/password/)
    const user = screen.getByLabelText('아이디') as HTMLInputElement
    expect(user.getAttribute('autocomplete')).toBe('username')
    expect(user.getAttribute('autocapitalize')).toBe('off')
    expect(user.getAttribute('autocorrect')).toBe('off')
    expect(user.getAttribute('spellcheck')).toBe('false')
    expect((screen.getByLabelText('비밀번호') as HTMLInputElement).getAttribute('autocomplete')).toBe('new-password')
  })

  it('setup_token_not_configured 안내, invalid_setup_token은 토큰 칸 오류 + 칸 비우기', async () => {
    let code = 'setup_token_not_configured'
    stubApi((m, p) =>
      m === 'GET' && p === '/auth/status'
        ? { status: 200, body: { setup_required: true, logged_in: false } }
        : { status: 403, body: { error: { code, message: code === 'invalid_setup_token' ? '가입 토큰이 올바르지 않습니다.' : '가입 토큰이 설정되어 있지 않습니다.' } } },
    )
    renderAt('/setup')
    const fill = () => {
      fireEvent.change(screen.getByLabelText('아이디'), { target: { value: 'tester' } })
      fireEvent.change(screen.getByLabelText('비밀번호'), { target: { value: 'long enough pw' } })
      fireEvent.change(screen.getByLabelText('비밀번호 확인'), { target: { value: 'long enough pw' } })
      fireEvent.change(screen.getByLabelText('가입 토큰'), { target: { value: 'tok' } })
      fireEvent.click(screen.getByRole('button', { name: '다음' }))
    }
    await screen.findByLabelText('가입 토큰')
    fill()
    expect(await screen.findByText(/서버에 가입 토큰이 설정되어 있지 않아요/)).toBeTruthy()
    code = 'invalid_setup_token'
    fill()
    expect(await screen.findByText(/가입 토큰이 올바르지 않습니다/)).toBeTruthy()
    expect((screen.getByLabelText('가입 토큰') as HTMLInputElement).value).toBe('')
  })
})

describe('로그인 화면', () => {
  it('입력칸 iOS 속성과 코드 칸 숫자 키패드', async () => {
    stubApi((_m, p) =>
      p === '/auth/status'
        ? { status: 200, body: { setup_required: false, logged_in: false } }
        : { status: 200, body: { totp_required: true, challenge_id: 'c1' } },
    )
    renderAt('/login')
    const user = (await screen.findByLabelText('아이디')) as HTMLInputElement
    expect(user.getAttribute('autocomplete')).toBe('username')
    expect(user.getAttribute('autocapitalize')).toBe('off')
    const pw = screen.getByLabelText('비밀번호') as HTMLInputElement
    expect(pw.getAttribute('autocomplete')).toBe('current-password')
    fireEvent.change(user, { target: { value: 'tester' } })
    fireEvent.change(pw, { target: { value: 'whatever pw' } })
    fireEvent.click(screen.getByRole('button', { name: '다음' }))
    const code = (await screen.findByLabelText('6자리 코드')) as HTMLInputElement
    expect(code.getAttribute('autocomplete')).toBe('one-time-code')
    expect(code.getAttribute('inputmode')).toBe('numeric')
    // 복구 코드로 로그인하는 경로
    fireEvent.click(screen.getByRole('button', { name: /복구 코드로 로그인/ }))
    expect(await screen.findByLabelText('복구 코드')).toBeTruthy()
  })

  it('too_many_attempts는 Retry-After만큼 버튼을 잠근다', async () => {
    stubApi((_m, p) =>
      p === '/auth/status'
        ? { status: 200, body: { setup_required: false, logged_in: false } }
        : { status: 429, body: { error: { code: 'too_many_attempts', message: '로그인 시도가 너무 많습니다.' } }, headers: { 'Retry-After': '120' } },
    )
    renderAt('/login')
    fireEvent.change(await screen.findByLabelText('아이디'), { target: { value: 'tester' } })
    fireEvent.change(screen.getByLabelText('비밀번호'), { target: { value: 'whatever pw' } })
    fireEvent.click(screen.getByRole('button', { name: '다음' }))
    expect(await screen.findByText(/2분 뒤에 다시 시도할 수 있어요/)).toBeTruthy()
    expect((screen.getByRole('button', { name: '다음' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('challenge_expired면 비밀번호 단계부터 다시', async () => {
    stubApi((_m, p) => {
      if (p === '/auth/status') return { status: 200, body: { setup_required: false, logged_in: false } }
      if (p === '/auth/login') return { status: 200, body: { totp_required: true, challenge_id: 'c1' } }
      return { status: 400, body: { error: { code: 'challenge_expired', message: '시간이 지났습니다.' } } }
    })
    renderAt('/login')
    fireEvent.change(await screen.findByLabelText('아이디'), { target: { value: 'tester' } })
    fireEvent.change(screen.getByLabelText('비밀번호'), { target: { value: 'whatever pw' } })
    fireEvent.click(screen.getByRole('button', { name: '다음' }))
    fireEvent.change(await screen.findByLabelText('6자리 코드'), { target: { value: '123456' } })
    expect(await screen.findByText(/아이디와 비밀번호부터 다시 입력해 주세요/)).toBeTruthy()
    expect(screen.getByLabelText('비밀번호')).toBeTruthy()
  })
})
