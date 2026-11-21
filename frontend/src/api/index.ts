// API 호출은 모두 이 파일을 거친다. 계약: docs/API.md
// request()는 같은 출처의 /api 만 호출하고 credentials: 'include'로 세션 쿠키를 보낸다.

import { request } from './http'
import type {
  AiExtractResponse,
  AiSearchResponse,
  AuthStatus,
  LoginChallenge,
  LoginVerifyRequest,
  MetaPreview,
  RecoveryCodesResponse,
  Scrap,
  ScrapCreate,
  ScrapListParams,
  ScrapListResponse,
  ScrapPatch,
  Session,
  Source,
  SourceInput,
  Topic,
  TotpSetupInfo,
} from './types'

/** 목록 쿼리 문자열. cursor는 서버가 준 값을 그대로 넘긴다 (해석·생성하지 않음) */
export function toQuery(p: ScrapListParams): string {
  const q = new URLSearchParams()
  if (p.q) q.set('q', p.q)
  if (p.source_id) q.set('source_id', String(p.source_id))
  if (p.topic_ids?.length) q.set('topic_ids', p.topic_ids.join(','))
  if (p.liked) q.set('liked', 'true')
  if (p.due) q.set('due', p.due)
  if (p.sort) q.set('sort', p.sort)
  if (p.cursor) q.set('cursor', p.cursor)
  if (p.limit) q.set('limit', String(p.limit))
  const s = q.toString()
  return s ? '?' + s : ''
}

// ---------------------------------------------------------------- /api/auth
export const authApi = {
  status: () => request<AuthStatus>('GET', '/auth/status'),
  setup: (body: { username: string; password: string; setup_token: string }) =>
    request<TotpSetupInfo>('POST', '/auth/setup', body),
  setupVerify: (body: { code: string }) => request<RecoveryCodesResponse>('POST', '/auth/setup/verify', body),
  login: (body: { username: string; password: string }) => request<LoginChallenge>('POST', '/auth/login', body),
  /** 204 + 세션 쿠키 */
  loginVerify: (body: LoginVerifyRequest) => request<void>('POST', '/auth/login/verify', body),
  logout: () => request<void>('POST', '/auth/logout'),
  /** 현재 기기 포함 모든 세션 삭제 */
  logoutAll: () => request<void>('POST', '/auth/logout-all'),
  sessions: () => request<Session[]>('GET', '/auth/sessions'),
  deleteSession: (id: number) => request<void>('DELETE', `/auth/sessions/${id}`),
  totpReset: (body: { password: string; code: string }) => request<TotpSetupInfo>('POST', '/auth/totp/reset', body),
  /** 성공하면 현재 기기를 뺀 다른 세션은 모두 로그아웃된다 */
  totpResetVerify: (body: { code: string }) => request<RecoveryCodesResponse>('POST', '/auth/totp/reset/verify', body),
}

// ---------------------------------------------------------------- /api/scraps
export const scrapsApi = {
  /** 목록 항목은 memo 대신 memo_preview(앞 300자). 전문은 get()으로 */
  list: (p: ScrapListParams) => request<ScrapListResponse>('GET', '/scraps' + toQuery(p)),
  get: (id: number) => request<Scrap>('GET', `/scraps/${id}`),
  create: (body: ScrapCreate) => request<Scrap>('POST', '/scraps', body),
  /** 바뀐 필드만 보낸다. liked는 받지 않는다 (좋아요는 setLike로만) */
  update: (id: number, body: ScrapPatch) => request<Scrap>('PATCH', `/scraps/${id}`, body),
  remove: (id: number) => request<void>('DELETE', `/scraps/${id}`),
  /** PUT /scraps/{id}/like { liked } — 값 지정 방식 */
  setLike: (id: number, liked: boolean) => request<{ liked: boolean }>('PUT', `/scraps/${id}/like`, { liked }),
}

// ---------------------------------------------------------------- 보조 기능
export const metaApi = {
  /** 제목 미리보기 + 출처 자동 판별. 서버가 최대 5초 걸릴 수 있다. title은 null 가능 */
  preview: (body: { url: string }) => request<MetaPreview>('POST', '/meta/preview', body),
}

export const sourcesApi = {
  list: () => request<Source[]>('GET', '/sources'),
  create: (body: SourceInput) => request<Source>('POST', '/sources', body),
  update: (id: number, body: Partial<SourceInput>) => request<Source>('PATCH', `/sources/${id}`, body),
  /** 기본 출처는 403 default_source */
  remove: (id: number) => request<void>('DELETE', `/sources/${id}`),
  /** 전체 순서 지정 → 204 */
  reorder: (ids: number[]) => request<void>('PUT', '/sources/order', { ids }),
}

export const topicsApi = {
  list: () => request<Topic[]>('GET', '/topics'),
  create: (body: { name: string }) => request<Topic>('POST', '/topics', body),
  update: (id: number, body: { name: string }) => request<Topic>('PATCH', `/topics/${id}`, body),
  remove: (id: number) => request<void>('DELETE', `/topics/${id}`),
  reorder: (ids: number[]) => request<void>('PUT', '/topics/order', { ids }),
}

// ---------------------------------------------------------------- /api/ai
// 수십 초 걸릴 수 있다 (서버 상한: 채우기 60초, 검색 90초). 취소·화면 이탈 때 signal로 멈춘다.
// 오류 문구는 http.ts의 aiErrorMessage (ai_unavailable 503, ai_failed 502, too_many_requests 429, payload_too_large 413).
export const aiApi = {
  /** 저장하지 않는다. 제안값만 반환. text(붙여넣은 본문)가 있으면 서버는 페이지를 가져오지 않는다 */
  extract: (body: { url: string; text?: string }, signal?: AbortSignal) =>
    request<AiExtractResponse>('POST', '/ai/extract', body, { signal }),
  search: (body: { query: string }, signal?: AbortSignal) =>
    request<AiSearchResponse>('POST', '/ai/search', body, { signal }),
}
