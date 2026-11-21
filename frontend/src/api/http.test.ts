import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, errorMessage, request, setUnauthorizedHandler } from './http'

function mockFetch(status: number, body: unknown, headers: Record<string, string> = {}) {
  const fn = vi.fn(async () =>
    new Response(body === undefined ? null : JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json', ...headers },
    }),
  )
  vi.stubGlobal('fetch', fn)
  return fn
}

afterEach(() => {
  vi.unstubAllGlobals()
  setUnauthorizedHandler(null)
})

describe('request', () => {
  it('같은 출처 /api 로 쿠키를 포함해 보낸다', async () => {
    const fn = mockFetch(200, { ok: 1 })
    await request('POST', '/x', { a: 1 })
    const [url, init] = fn.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/x')
    expect(init.credentials).toBe('include')
    expect(init.body).toBe('{"a":1}')
  })

  it('204는 undefined', async () => {
    mockFetch(204, undefined)
    await expect(request('DELETE', '/x')).resolves.toBeUndefined()
  })

  it('오류는 error.code·message를 그대로 담는다', async () => {
    mockFetch(400, { error: { code: 'duplicate_pattern', message: '이미 다른 출처에 있는 도메인입니다.' } })
    const e = await request('POST', '/sources', {}).catch((x: unknown) => x)
    expect(e).toBeInstanceOf(ApiError)
    expect((e as ApiError).code).toBe('duplicate_pattern')
    expect(errorMessage(e)).toBe('이미 다른 출처에 있는 도메인입니다.')
  })

  it('401 unauthorized일 때만 로그인 필요 처리를 부른다', async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)
    mockFetch(401, { error: { code: 'invalid_credentials', message: '아이디 또는 비밀번호가 올바르지 않습니다.' } })
    await request('POST', '/auth/login', {}).catch(() => {})
    mockFetch(401, { error: { code: 'invalid_code', message: '인증 코드가 올바르지 않습니다.' } })
    await request('POST', '/auth/login/verify', {}).catch(() => {})
    expect(handler).not.toHaveBeenCalled()
    mockFetch(401, { error: { code: 'unauthorized', message: '로그인이 필요합니다.' } })
    await request('GET', '/scraps').catch(() => {})
    expect(handler).toHaveBeenCalledTimes(1)
  })

  it('429는 Retry-After(초)를 담는다', async () => {
    mockFetch(429, { error: { code: 'too_many_attempts', message: '시도 횟수를 넘었습니다.' } }, { 'Retry-After': '900' })
    const e = (await request('POST', '/auth/login', {}).catch((x: unknown) => x)) as ApiError
    expect(e.code).toBe('too_many_attempts')
    expect(e.retryAfter).toBe(900)
    expect(errorMessage(e)).toContain('15분')
  })

  it('JSON이 아닌 오류(프록시 502)는 서버 연결 오류', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<html>bad gateway</html>', { status: 502 })))
    const e = (await request('GET', '/scraps').catch((x: unknown) => x)) as ApiError
    expect(e.code).toBe('server_unavailable')
  })

  it('네트워크 오류는 status 0, network_error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))))
    const e = (await request('GET', '/scraps').catch((x: unknown) => x)) as ApiError
    expect(e.status).toBe(0)
    expect(e.code).toBe('network_error')
  })
})
