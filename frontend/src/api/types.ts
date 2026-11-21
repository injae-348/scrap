// docs/API.md(v1.5)의 데이터 형식을 그대로 옮긴 타입.

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

/** GET /scraps 목록 항목 (v1.4): memo 대신 memo_preview(앞 최대 300자). 전문은 GET /scraps/{id} */
export type ScrapListItem = Omit<Scrap, 'memo'> & { memo_preview: string }

export interface ScrapListResponse {
  items: ScrapListItem[]
  /** 다음 페이지 커서. 서버 내부 형식이므로 그대로 저장해 다시 보낸다 */
  next_cursor: string | null
}

/** POST /scraps 요청 본문. title이 비면 서버가 url로 저장, source_id를 빼면 서버가 자동 판별 */
export interface ScrapCreate {
  url: string
  title?: string
  memo?: string
  source_id?: number
  topic_ids?: number[]
  /** 선택, 기본 false */
  liked?: boolean
  due_date?: string | null
}

/** PATCH /scraps/{id} 본문 — 바뀐 필드만. liked는 받지 않는다 (좋아요는 PUT /scraps/{id}/like로만) */
export interface ScrapPatch {
  url?: string
  title?: string
  memo?: string
  source_id?: number
  topic_ids?: number[]
  due_date?: string | null
}

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

/** POST /ai/extract 응답 (v1.5). 저장되지 않은 제안값. topic_suggestions는 기존 주제면 실제 이름으로 정규화돼 온다 */
export interface AiExtractResponse {
  title: string | null
  due_date: string | null
  memo: string | null
  topic_suggestions: string[]
  content_fetched: boolean
}

/** POST /ai/search 응답 (v1.5). scrap은 목록과 같은 ScrapListItem(memo_preview) */
export interface AiSearchResponse {
  answer: string
  results: { scrap: ScrapListItem; reason: string }[]
}
