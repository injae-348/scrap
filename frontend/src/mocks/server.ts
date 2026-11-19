// 메모리 기반 목 서버. src/api/의 함수들이 지금은 이 함수들을 호출한다.
// 요청·응답 형태는 docs/API.md를 따르고, 오류는 ApiError(서버 오류 응답 형식과 동일)로 던진다.

import { ApiError } from '../api/http'
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
} from '../api/types'
import { addDaysISO, daysUntil, DUE_SOON_DAYS } from '../lib/date'
import {
  buildInitialScraps,
  DEFAULT_SOURCE_ID,
  initialSessions,
  initialSources,
  initialTopics,
} from './data'
import { mockFlags, type FailTarget } from './flags'

// ---------------------------------------------------------------- 상태

const db = {
  sources: structuredClone(initialSources),
  topics: structuredClone(initialTopics),
  scraps: mockFlags.empty ? [] : buildInitialScraps(),
  sessions: structuredClone(initialSessions),
  auth: {
    setupRequired: mockFlags.auth === 'setup',
    loggedIn: mockFlags.auth !== 'login' && mockFlags.auth !== 'setup',
    challenge: null as string | null,
    failedLogins: 0,
  },
}

let nextId = 1000
const newId = () => nextId++

// ---------------------------------------------------------------- 공통

function delay(): Promise<void> {
  const ms = mockFlags.slow ? 1500 : 200 + Math.random() * 300
  return new Promise((r) => setTimeout(r, ms))
}

async function respond<T>(value: T, ms?: number): Promise<T> {
  if (ms) await new Promise((r) => setTimeout(r, ms))
  else await delay()
  return structuredClone(value)
}

function failIf(target: FailTarget, message: string) {
  if (mockFlags.fail.has(target)) throw new ApiError(500, 'mock_failure', message)
}

function requireLogin() {
  if (!db.auth.loggedIn) throw new ApiError(401, 'unauthorized', '로그인이 필요합니다.')
}

function notFound(): never {
  throw new ApiError(404, 'not_found', '스크랩을 찾을 수 없습니다.')
}

// ---------------------------------------------------------------- 인증

function randomCode(len: number, chars: string) {
  let s = ''
  for (let i = 0; i < len; i++) s += chars[Math.floor(Math.random() * chars.length)]
  return s
}

function makeRecoveryCodes(): string[] {
  const chars = 'abcdefghjkmnpqrstuvwxyz23456789'
  return Array.from({ length: 10 }, () => `${randomCode(4, chars)}-${randomCode(4, chars)}`)
}

/** 스캔할 수 없는 가짜 QR 이미지 (모양만) */
function fakeQrDataUrl(): string {
  const n = 25
  const cell = 8
  let rects = ''
  const finder = (x: number, y: number) =>
    `<rect x="${x * cell}" y="${y * cell}" width="${7 * cell}" height="${7 * cell}" fill="#000"/>` +
    `<rect x="${(x + 1) * cell}" y="${(y + 1) * cell}" width="${5 * cell}" height="${5 * cell}" fill="#fff"/>` +
    `<rect x="${(x + 2) * cell}" y="${(y + 2) * cell}" width="${3 * cell}" height="${3 * cell}" fill="#000"/>`
  for (let y = 0; y < n; y++) {
    for (let x = 0; x < n; x++) {
      const inFinder = (x < 8 && y < 8) || (x >= n - 8 && y < 8) || (x < 8 && y >= n - 8)
      if (!inFinder && (x * 7 + y * 13 + x * y) % 3 === 0) {
        rects += `<rect x="${x * cell}" y="${y * cell}" width="${cell}" height="${cell}" fill="#000"/>`
      }
    }
  }
  const size = n * cell
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="-16 -16 ${size + 32} ${size + 32}">` +
    `<rect x="-16" y="-16" width="${size + 32}" height="${size + 32}" fill="#fff"/>` +
    rects +
    finder(0, 0) +
    finder(n - 7, 0) +
    finder(0, n - 7) +
    `</svg>`
  return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg)
}

const FAKE_SECRET = 'MOCKMOCKMOCKMOCK2345'

function checkTotp(code: string) {
  if (!/^\d{6}$/.test(code)) throw new ApiError(400, 'invalid_code', '6자리 숫자를 입력해 주세요.')
  if (code === '000000') throw new ApiError(400, 'invalid_code', '코드가 맞지 않습니다. 앱에 표시된 최신 코드를 입력해 주세요.')
}

export const mockAuth = {
  async status(): Promise<AuthStatus> {
    return respond({ setup_required: db.auth.setupRequired, logged_in: db.auth.loggedIn }, 150)
  },

  async setup(body: { username: string; password: string }): Promise<TotpSetupInfo> {
    if (body.password.length < 10)
      throw new ApiError(400, 'weak_password', '비밀번호는 10자 이상이어야 합니다.')
    return respond({ qr_data_url: fakeQrDataUrl(), secret: FAKE_SECRET })
  },

  async setupVerify(body: { code: string }): Promise<RecoveryCodesResponse> {
    await delay()
    checkTotp(body.code)
    db.auth.setupRequired = false
    db.auth.loggedIn = true
    return { recovery_codes: makeRecoveryCodes() }
  },

  async login(body: { username: string; password: string }): Promise<LoginChallenge> {
    await delay()
    if (db.auth.failedLogins >= 5)
      throw new ApiError(429, 'too_many_attempts', '로그인 시도가 너무 많습니다. 15분 후 다시 시도해 주세요.')
    if (!body.username || body.password === 'wrong') {
      db.auth.failedLogins++
      throw new ApiError(401, 'invalid_credentials', '아이디 또는 비밀번호가 올바르지 않습니다.')
    }
    db.auth.challenge = 'mock-challenge-' + newId()
    return { totp_required: true, challenge_id: db.auth.challenge }
  },

  async loginVerify(body: LoginVerifyRequest): Promise<void> {
    await delay()
    if (body.challenge_id !== db.auth.challenge)
      throw new ApiError(400, 'challenge_expired', '인증 시간이 지났습니다. 처음부터 다시 로그인해 주세요.')
    if ('code' in body) checkTotp(body.code)
    else if (!/^[a-z0-9]{4}-[a-z0-9]{4}$/i.test(body.recovery_code.trim()))
      throw new ApiError(400, 'invalid_recovery_code', '복구 코드가 올바르지 않습니다.')
    db.auth.loggedIn = true
    db.auth.failedLogins = 0
    db.auth.challenge = null
  },

  async logout(): Promise<void> {
    await delay()
    db.auth.loggedIn = false
  },

  async logoutAll(): Promise<void> {
    await delay()
    db.sessions = db.sessions.filter((s) => s.current)
  },

  async sessions(): Promise<Session[]> {
    requireLogin()
    return respond(db.sessions)
  },

  async deleteSession(id: number): Promise<void> {
    await delay()
    db.sessions = db.sessions.filter((s) => s.id !== id)
  },

  // ---- API.md에 없음: 2차 인증 재설정 (API 변경 제안)
  async totpReset(body: { password: string; code: string }): Promise<TotpSetupInfo> {
    await delay()
    if (!body.password) throw new ApiError(400, 'invalid_password', '현재 비밀번호를 입력해 주세요.')
    checkTotp(body.code)
    return { qr_data_url: fakeQrDataUrl(), secret: FAKE_SECRET }
  },

  async totpResetVerify(body: { code: string }): Promise<RecoveryCodesResponse> {
    await delay()
    checkTotp(body.code)
    return { recovery_codes: makeRecoveryCodes() }
  },
}

// ---------------------------------------------------------------- 스크랩

function sourceRef(id: number) {
  const s = db.sources.find((x) => x.id === id) ?? db.sources.find((x) => x.id === DEFAULT_SOURCE_ID)!
  return { id: s.id, name: s.name }
}

function topicsOf(ids: number[]): Topic[] {
  return db.topics.filter((t) => ids.includes(t.id))
}

function matchesQuery(s: Scrap, q: string) {
  const hay = [s.title, s.memo, s.url, ...s.topics.map((t) => t.name)].join(' ').toLowerCase()
  return q
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((w) => hay.includes(w))
}

export const mockScraps = {
  async list(p: ScrapListParams): Promise<ScrapListResponse> {
    await delay()
    requireLogin()
    failIf('list', '목록을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.')
    let items = db.scraps.slice()
    if (p.q) items = items.filter((s) => matchesQuery(s, p.q!))
    if (p.source_id) items = items.filter((s) => s.source.id === p.source_id)
    if (p.topic_ids?.length)
      items = items.filter((s) => p.topic_ids!.every((id) => s.topics.some((t) => t.id === id)))
    if (p.liked) items = items.filter((s) => s.liked)
    if (p.due === 'upcoming')
      items = items.filter((s) => s.due_date && daysUntil(s.due_date) >= 0 && daysUntil(s.due_date) <= DUE_SOON_DAYS)
    if (p.due === 'past') items = items.filter((s) => s.due_date && daysUntil(s.due_date) < 0)

    if (p.sort === 'due') {
      // 마감일 빠른 순, 마감일 없는 항목은 뒤로
      items.sort((a, b) => {
        if (!a.due_date && !b.due_date) return b.created_at.localeCompare(a.created_at)
        if (!a.due_date) return 1
        if (!b.due_date) return -1
        return a.due_date.localeCompare(b.due_date)
      })
    } else {
      items.sort((a, b) => b.created_at.localeCompare(a.created_at))
    }

    const limit = p.limit ?? 20
    const start = p.cursor ? Number(p.cursor) : 0
    const page = items.slice(start, start + limit)
    const next = start + limit < items.length ? String(start + limit) : null
    return structuredClone({ items: page, next_cursor: next })
  },

  async get(id: number): Promise<Scrap> {
    await delay()
    const s = db.scraps.find((x) => x.id === id)
    if (!s) notFound()
    return structuredClone(s)
  },

  async create(body: ScrapInput): Promise<Scrap> {
    await delay()
    failIf('save', '저장하지 못했습니다. 잠시 후 다시 시도해 주세요.')
    const now = new Date().toISOString()
    const scrap: Scrap = {
      id: newId(),
      url: body.url,
      title: body.title,
      memo: body.memo,
      source: sourceRef(body.source_id),
      topics: topicsOf(body.topic_ids),
      liked: body.liked,
      due_date: body.due_date,
      created_at: now,
      updated_at: now,
    }
    db.scraps.unshift(scrap)
    return structuredClone(scrap)
  },

  async update(id: number, body: Partial<ScrapInput>): Promise<Scrap> {
    await delay()
    failIf('save', '저장하지 못했습니다. 잠시 후 다시 시도해 주세요.')
    const s = db.scraps.find((x) => x.id === id)
    if (!s) notFound()
    if (body.url !== undefined) s.url = body.url
    if (body.title !== undefined) s.title = body.title
    if (body.memo !== undefined) s.memo = body.memo
    if (body.source_id !== undefined) s.source = sourceRef(body.source_id)
    if (body.topic_ids !== undefined) s.topics = topicsOf(body.topic_ids)
    if (body.liked !== undefined) s.liked = body.liked
    if (body.due_date !== undefined) s.due_date = body.due_date
    s.updated_at = new Date().toISOString()
    return structuredClone(s)
  },

  async remove(id: number): Promise<void> {
    await delay()
    db.scraps = db.scraps.filter((x) => x.id !== id)
  },

  async toggleLike(id: number): Promise<{ liked: boolean }> {
    await delay()
    const s = db.scraps.find((x) => x.id === id)
    if (!s) notFound()
    s.liked = !s.liked
    return { liked: s.liked }
  },
}

// ---------------------------------------------------------------- 메타

export function detectSourceId(url: string): number {
  let host = ''
  try {
    host = new URL(url).hostname.toLowerCase()
  } catch {
    return DEFAULT_SOURCE_ID
  }
  for (const s of db.sources) {
    if (s.domain_patterns.some((p) => host === p || host.endsWith('.' + p))) return s.id
  }
  return DEFAULT_SOURCE_ID
}

export const mockMeta = {
  async preview(body: { url: string }): Promise<MetaPreview> {
    await delay()
    const source_id = detectSourceId(body.url)
    // 목: 일부 출처는 제목을 못 가져오는 상황을 흉내 낸다
    const blocked = source_id === 2 || source_id === 4
    return { title: blocked ? null : '[가상 제목] 붙여넣은 링크의 페이지 제목', source_id }
  },
}

// ---------------------------------------------------------------- 출처·주제

function reorder<T extends { id: number }>(list: T[], ids: number[]): T[] {
  return ids.map((id) => list.find((x) => x.id === id)).filter((x): x is T => !!x)
}

function checkName(name: string, list: { id: number; name: string }[], selfId?: number) {
  const n = name.trim()
  if (!n) throw new ApiError(400, 'invalid_name', '이름을 입력해 주세요.')
  if (list.some((x) => x.name.toLowerCase() === n.toLowerCase() && x.id !== selfId))
    throw new ApiError(400, 'duplicate_name', '같은 이름이 이미 있습니다.')
  return n
}

export const mockSources = {
  async list(): Promise<Source[]> {
    return respond(db.sources)
  },
  async create(body: { name: string; domain_patterns: string[] }): Promise<Source> {
    await delay()
    const s: Source = { id: newId(), name: checkName(body.name, db.sources), domain_patterns: body.domain_patterns }
    db.sources.push(s)
    return structuredClone(s)
  },
  async update(id: number, body: Partial<Omit<Source, 'id'>>): Promise<Source> {
    await delay()
    const s = db.sources.find((x) => x.id === id)
    if (!s) throw new ApiError(404, 'not_found', '출처를 찾을 수 없습니다.')
    if (body.name !== undefined) s.name = checkName(body.name, db.sources, id)
    if (body.domain_patterns !== undefined) s.domain_patterns = body.domain_patterns
    db.scraps.forEach((sc) => {
      if (sc.source.id === id) sc.source = { id, name: s.name }
    })
    return structuredClone(s)
  },
  async remove(id: number): Promise<void> {
    await delay()
    if (id === DEFAULT_SOURCE_ID)
      throw new ApiError(400, 'default_source', '기본 출처(일반사이트)는 삭제할 수 없습니다.')
    db.sources = db.sources.filter((x) => x.id !== id)
    // 삭제된 출처의 스크랩은 기본 출처로 옮긴다 (제안 동작)
    db.scraps.forEach((sc) => {
      if (sc.source.id === id) sc.source = sourceRef(DEFAULT_SOURCE_ID)
    })
  },
  // API.md에 없음: 순서 변경 (API 변경 제안)
  async reorder(ids: number[]): Promise<Source[]> {
    await delay()
    db.sources = reorder(db.sources, ids)
    return structuredClone(db.sources)
  },
}

export const mockTopics = {
  async list(): Promise<Topic[]> {
    return respond(db.topics)
  },
  async create(body: { name: string }): Promise<Topic> {
    await delay()
    const t: Topic = { id: newId(), name: checkName(body.name, db.topics) }
    db.topics.push(t)
    return structuredClone(t)
  },
  async update(id: number, body: { name: string }): Promise<Topic> {
    await delay()
    const t = db.topics.find((x) => x.id === id)
    if (!t) throw new ApiError(404, 'not_found', '주제를 찾을 수 없습니다.')
    t.name = checkName(body.name, db.topics, id)
    db.scraps.forEach((sc) => {
      sc.topics = sc.topics.map((x) => (x.id === id ? { ...t } : x))
    })
    return structuredClone(t)
  },
  async remove(id: number): Promise<void> {
    await delay()
    db.topics = db.topics.filter((x) => x.id !== id)
    db.scraps.forEach((sc) => {
      sc.topics = sc.topics.filter((x) => x.id !== id)
    })
  },
  // API.md에 없음: 순서 변경 (API 변경 제안)
  async reorder(ids: number[]): Promise<Topic[]> {
    await delay()
    db.topics = reorder(db.topics, ids)
    return structuredClone(db.topics)
  },
}

// ---------------------------------------------------------------- AI

const SYNONYMS: Record<string, string[]> = {
  공모전: ['공모전', '해커톤', '어워드', '지원금', '모집', '접수'],
  대회: ['공모전', '해커톤', '어워드'],
  보안: ['보안', 'security', '쿠키', '비밀번호', 'totp', 'argon2'],
  도커: ['도커', 'docker', 'compose', '컨테이너'],
  요리: ['요리', '레시피', '집밥', '찌개', '덮밥'],
  클로드: ['claude', '클로드'],
}

export const mockAi = {
  async extract(body: { url: string; text?: string }): Promise<AiExtractResponse> {
    await respond(null, mockFlags.slow ? 2500 : 1200)
    failIf('ai', 'AI 응답을 받지 못했습니다. 잠시 후 다시 시도해 주세요.')
    const sourceId = detectSourceId(body.url)
    const hasText = !!body.text?.trim()
    // 목: X·당근은 로그인 벽 때문에 본문을 못 가져오는 상황을 흉내 낸다
    if ((sourceId === 2 || sourceId === 4) && !hasText) {
      return { title: null, due_date: null, memo: null, topic_suggestions: [], content_fetched: false }
    }
    const looksLikeContest = /contest|award|grant|hackathon|공모|모집/i.test(body.url + (body.text ?? ''))
    return {
      title: looksLikeContest ? '[AI 제안] 가상 공모전 참가 안내' : '[AI 제안] 가상 페이지 핵심 정리',
      due_date: looksLikeContest ? addDaysISO(14) : null,
      memo: looksLikeContest
        ? '## 요약\n- 대상: 누구나 (가상)\n- 제출물: 기획서, 시연 영상\n- 상금: 미정'
        : '## 요약\n- 본문의 핵심 내용 1 (가상)\n- 본문의 핵심 내용 2 (가상)',
      topic_suggestions: looksLikeContest ? ['공모전', '기획'] : ['claude', '읽을거리'],
      content_fetched: true,
    }
  },

  async search(body: { query: string }): Promise<AiSearchResponse> {
    await respond(null, mockFlags.slow ? 3000 : 1500)
    failIf('ai', 'AI 검색에 실패했습니다. 잠시 후 다시 시도해 주세요.')
    const words = body.query.toLowerCase().split(/\s+/).filter((w) => w.length >= 2)
    const terms = new Set<string>()
    for (const w of words) {
      terms.add(w.replace(/(을|를|이|가|은|는|좀|찾아줘|알려줘)$/, ''))
      for (const [k, syn] of Object.entries(SYNONYMS)) if (w.includes(k)) syn.forEach((s) => terms.add(s))
    }
    const results = db.scraps
      .map((s) => {
        const hay = [s.title, s.memo, s.url, ...s.topics.map((t) => t.name)].join(' ').toLowerCase()
        const hits = [...terms].filter((t) => t && hay.includes(t.toLowerCase()))
        return { s, hits }
      })
      .filter((x) => x.hits.length > 0)
      .sort((a, b) => b.hits.length - a.hits.length)
      .slice(0, 6)
      .map(({ s, hits }) => ({
        scrap: structuredClone(s),
        reason:
          `'${hits.slice(0, 3).join("', '")}' 관련 내용이 있어요.` +
          (s.due_date && daysUntil(s.due_date) >= 0 ? ` 마감까지 ${daysUntil(s.due_date)}일 남았어요.` : ''),
      }))
    return {
      answer:
        results.length > 0
          ? `질문과 관련된 스크랩 ${results.length}개를 찾았어요. (목 데이터 결과)`
          : '관련된 스크랩을 찾지 못했어요. 다른 표현으로 다시 물어봐 주세요.',
      results,
    }
  },
}

// ---------------------------------------------------------------- 개발용 토글 (설정 화면)

export const mockDev = {
  flags: mockFlags,
  setFail(target: FailTarget, on: boolean) {
    if (on) mockFlags.fail.add(target)
    else mockFlags.fail.delete(target)
  },
  setEmpty(on: boolean) {
    mockFlags.empty = on
    db.scraps = on ? [] : buildInitialScraps()
  },
  setSlow(on: boolean) {
    mockFlags.slow = on
  },
  setSetupRequired() {
    db.auth.setupRequired = true
    db.auth.loggedIn = false
  },
}
