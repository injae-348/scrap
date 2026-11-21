import { afterEach, describe, expect, it, vi } from 'vitest'
import { aiErrorMessage, ApiError, errorMessage, formatWait, isAborted, request, setUnauthorizedHandler } from './http'

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

describe('취소 (AbortSignal)', () => {
  it('취소하면 aborted 오류로 끝나고 fetch에 signal을 넘긴다', async () => {
    let seen: AbortSignal | undefined
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            seen = init.signal ?? undefined
            init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
          }),
      ),
    )
    const c = new AbortController()
    const p = request('POST', '/ai/search', { query: 'x' }, { signal: c.signal }).catch((x: unknown) => x)
    c.abort()
    const e = (await p) as ApiError
    expect(seen).toBe(c.signal)
    expect(isAborted(e)).toBe(true)
    expect(e.code).toBe('aborted')
  })

  it('이미 취소된 신호면 보내지 않는다', async () => {
    const fn = mockFetch(200, {})
    const c = new AbortController()
    c.abort()
    const e = await request('POST', '/ai/extract', {}, { signal: c.signal }).catch((x: unknown) => x)
    expect(isAborted(e)).toBe(true)
    expect(fn).not.toHaveBeenCalled()
  })
})

describe('AI 오류 문구 (API.md v1.5 프론트 표시)', () => {
  async function fail(status: number, body: unknown, headers: Record<string, string> = {}) {
    mockFetch(status, body, headers)
    return (await request('POST', '/ai/extract', {}).catch((x: unknown) => x)) as ApiError
  }

  it('/ai/* 404를 "준비 중"으로 바꾸지 않는다 (일반 오류 그대로)', async () => {
    const e = await fail(404, { error: { code: 'not_found', message: '없음' } })
    expect(e.code).toBe('not_found')
    expect(aiErrorMessage(e, 'extract')).toBe('없음')
  })

  it('503 ai_unavailable → 서버 설정 필요', async () => {
    const e = await fail(503, { error: { code: 'ai_unavailable', message: 'x' } })
    expect(aiErrorMessage(e, 'extract')).toBe('AI 기능을 사용할 수 없어요 (서버 설정 필요)')
    expect(aiErrorMessage(e, 'search')).toBe('AI 기능을 사용할 수 없어요 (서버 설정 필요)')
    expect(errorMessage(e)).toBe('AI 기능을 사용할 수 없어요 (서버 설정 필요)')
  })

  it('502 ai_failed → 서버 message 그대로', async () => {
    const msg = 'AI 응답을 받지 못했어요. 잠시 후 다시 시도해 주세요.'
    const e = await fail(502, { error: { code: 'ai_failed', message: msg } })
    expect(aiErrorMessage(e, 'search')).toBe(msg)
  })

  it('413 payload_too_large: AI 채우기에서는 붙여넣은 본문 안내', async () => {
    const e = await fail(413, { error: { code: 'payload_too_large', message: '요청 본문이 너무 큽니다.' } })
    expect(aiErrorMessage(e, 'extract')).toBe('붙여넣은 본문이 너무 길어요.')
  })

  it('429는 Retry-After를 담고, 문구에는 남은 시간을 넣지 않는다 (화면이 따로 센다)', async () => {
    const e = await fail(429, { error: { code: 'too_many_requests', message: 'AI 요청이 너무 많아요.' } }, { 'Retry-After': '45' })
    expect(e.retryAfter).toBe(45)
    expect(aiErrorMessage(e, 'search')).toBe('AI 요청이 너무 많아요.')
  })
})

describe('formatWait', () => {
  it.each([
    [0, '0초'],
    [59, '59초'],
    [60, '1분'],
    [200, '3분 20초'],
    [3600, '1시간'],
    [7500, '2시간 5분'],
  ])('%d초 → %s', (sec, text) => {
    expect(formatWait(sec)).toBe(text)
  })
})

describe('AI 사용 한도 (503 ai_quota_exceeded)', () => {
  it('서버 message 그대로, ai_unavailable과 다른 문구', async () => {
    mockFetch(503, { error: { code: 'ai_quota_exceeded', message: '이번 달 AI 사용 한도에 도달했어요.' } })
    const e = (await request('POST', '/ai/search', {}).catch((x: unknown) => x)) as ApiError
    expect(e.code).toBe('ai_quota_exceeded')
    expect(e.retryAfter).toBeNull()
    expect(aiErrorMessage(e, 'search')).toBe('이번 달 AI 사용 한도에 도달했어요.')
    expect(aiErrorMessage(e, 'extract')).toBe('이번 달 AI 사용 한도에 도달했어요.')
    expect(aiErrorMessage(e, 'search')).not.toContain('서버 설정')
  })
})
