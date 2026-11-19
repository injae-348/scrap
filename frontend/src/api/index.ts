// API 호출은 모두 이 파일을 거친다.
// Phase 1(지금): src/mocks/의 메모리 목 서버를 호출한다.
// Phase 6: 각 함수 본문을 주석의 request(...) 호출로 바꾸면 된다. (http.ts의 request는 credentials: 'include')

import {
  mockAi,
  mockAuth,
  mockMeta,
  mockScraps,
  mockSources,
  mockTopics,
} from '../mocks/server'
import type {
  AiExtractResponse,
  AiSearchResponse,
  AuthStatus,
  LoginChallenge,
  LoginVerifyRequest,
  MetaPreview,
  RecoveryCodesResponse,
  Scrap,
  ScrapInput,
  ScrapListParams,
  ScrapListResponse,
  Session,
  Source,
  Topic,
  TotpSetupInfo,
} from './types'

/** 목록 쿼리 문자열 (실제 API 연동 시 사용) */
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
  /** GET /auth/status */
  status: (): Promise<AuthStatus> => mockAuth.status(),
  /** POST /auth/setup */
  setup: (body: { username: string; password: string }): Promise<TotpSetupInfo> => mockAuth.setup(body),
  /** POST /auth/setup/verify */
  setupVerify: (body: { code: string }): Promise<RecoveryCodesResponse> => mockAuth.setupVerify(body),
  /** POST /auth/login */
  login: (body: { username: string; password: string }): Promise<LoginChallenge> => mockAuth.login(body),
  /** POST /auth/login/verify */
  loginVerify: (body: LoginVerifyRequest): Promise<void> => mockAuth.loginVerify(body),
  /** POST /auth/logout */
  logout: (): Promise<void> => mockAuth.logout(),
  /** POST /auth/logout-all */
  logoutAll: (): Promise<void> => mockAuth.logoutAll(),
  /** GET /auth/sessions */
  sessions: (): Promise<Session[]> => mockAuth.sessions(),
  /** DELETE /auth/sessions/{id} */
  deleteSession: (id: number): Promise<void> => mockAuth.deleteSession(id),
  /** [API.md에 없음 — 제안] POST /auth/totp/reset */
  totpReset: (body: { password: string; code: string }): Promise<TotpSetupInfo> => mockAuth.totpReset(body),
  /** [API.md에 없음 — 제안] POST /auth/totp/reset/verify */
  totpResetVerify: (body: { code: string }): Promise<RecoveryCodesResponse> => mockAuth.totpResetVerify(body),
}

// ---------------------------------------------------------------- /api/scraps
export const scrapsApi = {
  /** GET /scraps */
  list: (p: ScrapListParams): Promise<ScrapListResponse> => mockScraps.list(p),
  /** GET /scraps/{id} */
  get: (id: number): Promise<Scrap> => mockScraps.get(id),
  /** POST /scraps */
  create: (body: ScrapInput): Promise<Scrap> => mockScraps.create(body),
  /** PATCH /scraps/{id} */
  update: (id: number, body: Partial<ScrapInput>): Promise<Scrap> => mockScraps.update(id, body),
  /** DELETE /scraps/{id} */
  remove: (id: number): Promise<void> => mockScraps.remove(id),
  /** POST /scraps/{id}/like */
  toggleLike: (id: number): Promise<{ liked: boolean }> => mockScraps.toggleLike(id),
}

// ---------------------------------------------------------------- 보조 기능
export const metaApi = {
  /** POST /meta/preview */
  preview: (body: { url: string }): Promise<MetaPreview> => mockMeta.preview(body),
}

export const sourcesApi = {
  /** GET /sources */
  list: (): Promise<Source[]> => mockSources.list(),
  /** POST /sources */
  create: (body: { name: string; domain_patterns: string[] }): Promise<Source> => mockSources.create(body),
  /** PATCH /sources/{id} */
  update: (id: number, body: Partial<Omit<Source, 'id'>>): Promise<Source> => mockSources.update(id, body),
  /** DELETE /sources/{id} */
  remove: (id: number): Promise<void> => mockSources.remove(id),
  /** [API.md에 없음 — 제안] PUT /sources/order { ids } */
  reorder: (ids: number[]): Promise<Source[]> => mockSources.reorder(ids),
}

export const topicsApi = {
  /** GET /topics */
  list: (): Promise<Topic[]> => mockTopics.list(),
  /** POST /topics */
  create: (body: { name: string }): Promise<Topic> => mockTopics.create(body),
  /** PATCH /topics/{id} */
  update: (id: number, body: { name: string }): Promise<Topic> => mockTopics.update(id, body),
  /** DELETE /topics/{id} */
  remove: (id: number): Promise<void> => mockTopics.remove(id),
  /** [API.md에 없음 — 제안] PUT /topics/order { ids } */
  reorder: (ids: number[]): Promise<Topic[]> => mockTopics.reorder(ids),
}

// ---------------------------------------------------------------- /api/ai
export const aiApi = {
  /** POST /ai/extract — 저장하지 않는다. 제안값만 반환 */
  extract: (body: { url: string; text?: string }): Promise<AiExtractResponse> => mockAi.extract(body),
  /** POST /ai/search */
  search: (body: { query: string }): Promise<AiSearchResponse> => mockAi.search(body),
}
