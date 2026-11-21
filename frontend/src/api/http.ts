// 모든 API 호출의 공통 함수. 실제 서버의 /api 만 호출한다.
// 인증은 서버가 설정하는 HttpOnly 쿠키로만 한다. 토큰을 저장소(localStorage 등)에 두지 않는다.

export class ApiError extends Error {
  /** HTTP 상태 코드. 네트워크 오류는 0 */
  status: number
  /** docs/API.md의 error.code (네트워크 오류는 'network_error') */
  code: string
  /** 429 응답의 Retry-After(초). 없으면 null */
  retryAfter: number | null

  constructor(status: number, code: string, message: string, retryAfter: number | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.retryAfter = retryAfter
  }
}

const BASE = '/api'

/**
 * 세션이 없거나 만료됐을 때(401 `unauthorized`) 부를 함수.
 * 다른 401(`invalid_credentials`, `invalid_code`)은 입력 오류라서 부르지 않는다.
 */
let onUnauthorized: (() => void) | null = null

export function setUnauthorizedHandler(fn: (() => void) | null) {
  onUnauthorized = fn
}

function parseRetryAfter(v: string | null): number | null {
  if (!v) return null
  const n = Number(v)
  if (Number.isFinite(n) && n >= 0) return Math.ceil(n)
  const t = Date.parse(v)
  return Number.isNaN(t) ? null : Math.max(0, Math.ceil((t - Date.now()) / 1000))
}

/** JSON 본문이 없는 오류(프록시 502 등)의 기본 코드·문구 */
function fallbackError(status: number): { code: string; message: string } {
  if (status === 401) return { code: 'unauthorized', message: '로그인이 필요합니다.' }
  if (status === 413) return { code: 'payload_too_large', message: '요청 내용이 너무 큽니다.' }
  if (status === 429) return { code: 'too_many_requests', message: '요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.' }
  if (status >= 500) return { code: 'server_unavailable', message: '서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.' }
  return { code: 'unknown', message: '요청을 처리하지 못했습니다.' }
}

export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response
  try {
    res = await fetch(BASE + path, {
      method,
      credentials: 'include',
      cache: 'no-store',
      headers: body === undefined ? { Accept: 'application/json' } : { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'network_error', '네트워크에 연결할 수 없습니다. 연결 상태를 확인해 주세요.')
  }
  if (res.status === 204) return undefined as T
  const data: unknown = await res.json().catch(() => null)
  if (!res.ok) {
    const err = (data as { error?: { code?: unknown; message?: unknown } } | null)?.error
    const fb = fallbackError(res.status)
    const code = typeof err?.code === 'string' ? err.code : fb.code
    const message = typeof err?.message === 'string' && err.message ? err.message : fb.message
    const e = new ApiError(res.status, code, message, parseRetryAfter(res.headers.get('Retry-After')))
    if (res.status === 401 && code === 'unauthorized') onUnauthorized?.()
    throw e
  }
  if (data === null) throw new ApiError(res.status, 'invalid_response', '서버 응답을 읽지 못했습니다.')
  return data as T
}

export function isApiError(err: unknown, ...codes: string[]): err is ApiError {
  return err instanceof ApiError && (codes.length === 0 || codes.includes(err.code))
}

/** "3분 20초" 형식 */
export function formatWait(seconds: number): string {
  const s = Math.max(0, Math.ceil(seconds))
  if (s < 60) return `${s}초`
  const m = Math.floor(s / 60)
  const r = s % 60
  return r ? `${m}분 ${r}초` : `${m}분`
}

/**
 * 화면에 보여 줄 오류 문구. 서버가 한국어 message를 주므로 대부분 그대로 쓰고,
 * 화면 동작이 달라야 하는 코드만 문구를 보탠다. (화면 분기는 error.code로 한다)
 */
export function errorMessage(err: unknown): string {
  if (!(err instanceof ApiError)) return '알 수 없는 오류가 발생했습니다.'
  switch (err.code) {
    case 'too_many_attempts':
    case 'too_many_requests':
      return err.retryAfter
        ? `${err.message} (${formatWait(err.retryAfter)} 뒤에 다시 시도할 수 있어요)`
        : err.message
    case 'origin_mismatch':
      // 운영에서는 나오지 않아야 한다. 개발 중 프록시·허용 출처 설정이 맞지 않을 때.
      return '요청 출처가 서버 설정과 맞지 않습니다. 주소창의 주소로 다시 접속해 주세요.'
    case 'payload_too_large':
      return '내용이 너무 길어서 저장할 수 없어요. 메모를 줄여 주세요.'
    case 'db_unavailable':
    case 'internal_error':
    case 'service_unavailable':
    case 'server_unavailable':
      return err.message.includes('잠시 후') ? err.message : `${err.message} 잠시 후 다시 시도해 주세요.`
    default:
      return err.message
  }
}
