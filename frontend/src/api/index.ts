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
  ScrapPatch,
  Session,
  Source,
  SourceInput,
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
  /** POST /auth/totp/reset */
  totpReset: (body: { password: string; code: string }): Promise<TotpSetupInfo> => mockAuth.totpReset(body),
  /** POST /auth/totp/reset/verify */
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
  /** PATCH /scraps/{id} (liked 제외) */
  update: (id: number, body: ScrapPatch): Promise<Scrap> => mockScraps.update(id, body),
  /** DELETE /scraps/{id} */
  remove: (id: number): Promise<void> => mockScraps.remove(id),
  /** PUT /scraps/{id}/like { liked } — 값 지정 방식 */
  setLike: (id: number, liked: boolean): Promise<{ liked: boolean }> => mockScraps.setLike(id, { liked }),
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
  create: (body: SourceInput): Promise<Source> => mockSources.create(body),
  /** PATCH /sources/{id} */
  update: (id: number, body: Partial<SourceInput>): Promise<Source> => mockSources.update(id, body),
  /** DELETE /sources/{id} (기본 출처는 403) */
  remove: (id: number): Promise<void> => mockSources.remove(id),
  /** PUT /sources/order { ids } → 204 */
  reorder: (ids: number[]): Promise<void> => mockSources.reorder({ ids }),
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
  /** PUT /topics/order { ids } → 204 */
  reorder: (ids: number[]): Promise<void> => mockTopics.reorder({ ids }),
}

// ---------------------------------------------------------------- /api/ai
export const aiApi = {
  /** POST /ai/extract — 저장하지 않는다. 제안값만 반환 */
  extract: (body: { url: string; text?: string }): Promise<AiExtractResponse> => mockAi.extract(body),
  /** POST /ai/search */
  search: (body: { query: string }): Promise<AiSearchResponse> => mockAi.search(body),
}
