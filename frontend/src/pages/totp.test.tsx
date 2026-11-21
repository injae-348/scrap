// 2차 인증 재설정·가입 확인 단계: 429 대기 중 재제출 막기, 확인 진행 중 이탈 막기.
import { QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createQueryClient } from '../hooks/queries'
import { SetupPage } from './SetupPage'
import { TotpResetPage } from './TotpResetPage'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

type Reply = { status: number; body?: unknown; headers?: Record<string, string> }

function stubApi(handler: (path: string) => Reply | Promise<Reply>) {
  const fn = vi.fn(async (input: RequestInfo | URL) => {
    const r = await handler(String(input).replace(/^\/api/, ''))
    return new Response(r.body === undefined ? null : JSON.stringify(r.body), {
      status: r.status,
      headers: { 'Content-Type': 'application/json', ...r.headers },
    })
  })
  vi.stubGlobal('fetch', fn)
  return fn
}

const info = { qr_data_url: 'data:image/svg+xml;base64,AAAA', secret: 'SECRETSECRET2345' }
const tooMany: Reply = {
  status: 429,
  body: { error: { code: 'too_many_attempts', message: '시도가 너무 많습니다.' } },
  headers: { 'Retry-After': '60' },
}

function renderAt(path: string) {
  const router = createMemoryRouter(
    [
      { path: '/setup', element: <SetupPage /> },
      { path: '/settings/totp', element: <TotpResetPage /> },
      { path: '/settings', element: <div>설정 화면</div> },
    ],
    { initialEntries: [path] },
  )
  render(
    <QueryClientProvider client={createQueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return router
}

async function toTotpStep1() {
  fireEvent.change(await screen.findByLabelText('현재 비밀번호'), { target: { value: 'current password' } })
  fireEvent.change(screen.getByLabelText('지금 인증 앱의 6자리 코드'), { target: { value: '123456' } })
  fireEvent.click(screen.getByRole('button', { name: '다음' }))
  return (await screen.findByLabelText('새로 등록한 앱의 6자리 코드')) as HTMLInputElement
}

describe('2차 인증 재설정 확인', () => {
  it('429 대기 중에는 다시 제출하지 않는다', async () => {
    const fn = stubApi((p) => (p === '/auth/totp/reset' ? { status: 200, body: info } : tooMany))
    renderAt('/settings/totp')
    const code = await toTotpStep1()
    fireEvent.change(code, { target: { value: '111111' } })
    expect(await screen.findByText(/1분 뒤에 다시 시도할 수 있어요/)).toBeTruthy()
    const verifyCalls = () => fn.mock.calls.filter(([u]) => String(u).endsWith('/reset/verify')).length
    expect(verifyCalls()).toBe(1)
    fireEvent.change(code, { target: { value: '222222' } })
    expect((screen.getByRole('button', { name: '확인' }) as HTMLButtonElement).disabled).toBe(true)
    expect(verifyCalls()).toBe(1)
  })

  it('확인 요청이 진행 중이면 나가기를 허용하지 않고, 끝나면 복구 코드를 보여 준다', async () => {
    let finish: () => void = () => {}
    stubApi((p) =>
      p === '/auth/totp/reset'
        ? { status: 200, body: info }
        : new Promise<Reply>((resolve) => {
            finish = () => resolve({ status: 200, body: { recovery_codes: ['AAAA-BBBB-CCCC-DDDD'] } })
          }),
    )
    const router = renderAt('/settings/totp')
    const code = await toTotpStep1()
    fireEvent.change(code, { target: { value: '123456' } })
    fireEvent.click(screen.getByRole('link', { name: '설정' }))
    expect(await screen.findByText('코드를 확인하는 중이에요')).toBeTruthy()
    expect(screen.queryByRole('button', { name: '나가기' })).toBeNull()
    expect(router.state.location.pathname).toBe('/settings/totp')
    finish()
    expect(await screen.findByText('AAAA-BBBB-CCCC-DDDD')).toBeTruthy()
  })
})

describe('가입 코드 확인', () => {
  it('429 대기 중에는 다시 제출하지 않는다', async () => {
    const fn = stubApi((p) => {
      if (p === '/auth/status') return { status: 200, body: { setup_required: true, logged_in: false } }
      if (p === '/auth/setup') return { status: 200, body: info }
      return tooMany
    })
    renderAt('/setup')
    fireEvent.change(await screen.findByLabelText('아이디'), { target: { value: 'tester' } })
    fireEvent.change(screen.getByLabelText('비밀번호'), { target: { value: 'long enough pw' } })
    fireEvent.change(screen.getByLabelText('비밀번호 확인'), { target: { value: 'long enough pw' } })
    fireEvent.change(screen.getByLabelText('가입 토큰'), { target: { value: 'tok' } })
    fireEvent.click(screen.getByRole('button', { name: '다음' }))
    const code = await screen.findByLabelText('6자리 코드')
    fireEvent.change(code, { target: { value: '111111' } })
    expect(await screen.findByText(/1분 뒤에 다시 시도할 수 있어요/)).toBeTruthy()
    const verifyCalls = () => fn.mock.calls.filter(([u]) => String(u).endsWith('/setup/verify')).length
    fireEvent.change(code, { target: { value: '222222' } })
    await waitFor(() => expect((screen.getByRole('button', { name: '확인' }) as HTMLButtonElement).disabled).toBe(true))
    expect(verifyCalls()).toBe(1)
  })
})
