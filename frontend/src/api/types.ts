// docs/API.md(v1 확정본)의 데이터 형식을 그대로 옮긴 타입.

export interface SourceRef {
  id: number
  name: string
}

export interface Source {
  id: number
  name: string
  domain_patterns: string[]
  /** 기본 출처(일반사이트). 정확히 1개, 삭제 불가 */
  is_default: boolean
}

/** POST /sources, PATCH /sources/{id} 본문 */
export interface SourceInput {
  name: string
  domain_patterns: string[]
}

export interface Topic {
  id: number
  name: string
}

export interface Scrap {
  id: number
  url: string
  title: string
  memo: string
  source: SourceRef
  topics: Topic[]
  liked: boolean
  due_date: string | null
  created_at: string
  updated_at: string
}

export interface ScrapListParams {
  q?: string
  source_id?: number
  topic_ids?: number[]
  liked?: boolean
  due?: 'upcoming' | 'past'
  sort?: 'created' | 'due'
  cursor?: string
  limit?: number
}

export interface ScrapListResponse {
  items: Scrap[]
  next_cursor: string | null
}

/** POST /scraps 요청 본문 (Scrap에서 id·날짜 제외, source_id, topic_ids 사용). title이 빈 문자열이면 서버가 url로 저장 */
export interface ScrapInput {
  url: string
  title: string
  memo: string
  source_id: number
  topic_ids: number[]
  /** 선택, 기본 false */
  liked?: boolean
  due_date: string | null
}

/** PATCH /scraps/{id} 본문 — liked는 받지 않는다 (좋아요는 PUT /scraps/{id}/like로만) */
export type ScrapPatch = Partial<Omit<ScrapInput, 'liked'>>

export interface AuthStatus {
  setup_required: boolean
  logged_in: boolean
}

/** POST /auth/setup 응답: TOTP 등록 정보 */
export interface TotpSetupInfo {
  qr_data_url: string
  secret: string
}

export interface RecoveryCodesResponse {
  recovery_codes: string[]
}

export interface LoginChallenge {
  totp_required: true
  challenge_id: string
}

export type LoginVerifyRequest =
  | { challenge_id: string; code: string }
  | { challenge_id: string; recovery_code: string }

/** GET /auth/sessions 항목 */
export interface Session {
  id: number
  user_agent: string
  created_at: string
  last_seen_at: string
  current: boolean
}

export interface MetaPreview {
  title: string | null
  source_id: number
}

export interface AiExtractResponse {
  title: string | null
  due_date: string | null
  memo: string | null
  topic_suggestions: string[]
  content_fetched: boolean
}

export interface AiSearchResponse {
  answer: string
  results: { scrap: Scrap; reason: string }[]
}
