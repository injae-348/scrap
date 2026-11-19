// 실제 API 호출용 공통 함수 (Phase 6에서 목 대신 사용).
// 인증은 서버가 설정하는 HttpOnly 쿠키로만 한다. 토큰을 저장소에 두지 않는다.

export class ApiError extends Error {
  status: number
  code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

const BASE = '/api'

export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response
  try {
    res = await fetch(BASE + path, {
      method,
      credentials: 'include',
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'network_error', '네트워크에 연결할 수 없습니다. 연결 상태를 확인해 주세요.')
  }
  if (res.status === 204) return undefined as T
  const data: unknown = await res.json().catch(() => null)
  if (!res.ok) {
    const err = (data as { error?: { code?: string; message?: string } } | null)?.error
    throw new ApiError(res.status, err?.code ?? 'unknown', err?.message ?? '요청을 처리하지 못했습니다.')
  }
  return data as T
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message
  return '알 수 없는 오류가 발생했습니다.'
}
