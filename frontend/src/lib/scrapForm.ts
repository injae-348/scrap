// 저장 화면의 입력값 → API 요청 본문 (docs/API.md v1.3 "스크랩 입력")
import type { Scrap, ScrapCreate, ScrapPatch } from '../api/types'

export interface ScrapFormValues {
  url: string
  title: string
  memo: string
  /** null = 고르지 않음 (새 스크랩이면 서버가 자동 판별) */
  sourceId: number | null
  topicIds: number[]
  /** '' = 마감일 없음 */
  due: string
}

export function sameIds(a: number[], b: number[]): boolean {
  if (a.length !== b.length) return false
  const sb = new Set(b)
  return a.every((x) => sb.has(x))
}

/** POST /scraps: 빈 제목은 보내지 않는다(서버가 url로 저장). 출처를 안 골랐으면 서버가 자동 판별 */
export function buildScrapCreate(v: ScrapFormValues): ScrapCreate {
  const body: ScrapCreate = { url: v.url.trim() }
  const t = v.title.trim()
  if (t) body.title = t
  if (v.memo) body.memo = v.memo
  if (v.sourceId !== null) body.source_id = v.sourceId
  if (v.topicIds.length) body.topic_ids = v.topicIds
  if (v.due) body.due_date = v.due
  return body
}

/**
 * PATCH /scraps/{id}: 바뀐 필드만, source_id/topic_ids 형태로. liked는 절대 넣지 않는다
 * (좋아요는 PUT /like로만 — 다른 기기의 변경을 덮어쓰지 않게). 바뀐 것이 없으면 빈 객체.
 */
export function buildScrapPatch(initial: Scrap, v: ScrapFormValues): ScrapPatch {
  const body: ScrapPatch = {}
  const url = v.url.trim()
  const title = v.title.trim()
  if (url !== initial.url) body.url = url
  if (title !== initial.title) body.title = title
  if (v.memo !== initial.memo) body.memo = v.memo
  if (v.sourceId !== null && v.sourceId !== initial.source.id) body.source_id = v.sourceId
  const initTopics = initial.topics.map((t) => t.id)
  if (!sameIds(v.topicIds, initTopics)) body.topic_ids = v.topicIds
  const due = v.due || null
  if (due !== initial.due_date) body.due_date = due
  return body
}

export interface SelectionFix {
  sourceId: number | null
  topicIds: number[]
  /** 목록에 없어 뺀 주제 수 */
  removedTopics: number
  /** 출처가 목록에 없어 바꾼 경우: 'auto'(새 스크랩, 자동 판별) / 'default'(수정, 기본 출처) */
  sourceChanged: 'auto' | 'default' | null
}

/**
 * 고른 주제·출처를 지금 목록에 있는 id로 맞춘다 (다른 기기에서 지운 경우).
 * 출처가 없어졌으면 새 스크랩은 자동 판별(null), 수정은 기본 출처로 바꾼다.
 * 출처 목록이 비어 있으면(아직 못 받음) 출처는 건드리지 않는다.
 */
export function reconcileSelection(
  sel: { sourceId: number | null; topicIds: number[] },
  current: { topics: { id: number }[]; sources: { id: number; is_default: boolean }[] },
  mode: 'create' | 'edit',
): SelectionFix {
  const topicSet = new Set(current.topics.map((t) => t.id))
  const topicIds = sel.topicIds.filter((id) => topicSet.has(id))
  let sourceId = sel.sourceId
  let sourceChanged: SelectionFix['sourceChanged'] = null
  if (sourceId !== null && current.sources.length > 0 && !current.sources.some((s) => s.id === sourceId)) {
    if (mode === 'create') {
      sourceId = null
      sourceChanged = 'auto'
    } else {
      sourceId = current.sources.find((s) => s.is_default)?.id ?? null
      sourceChanged = 'default'
    }
  }
  return { sourceId, topicIds, removedTopics: sel.topicIds.length - topicIds.length, sourceChanged }
}

/** 사용자에게 보여 줄 정리 안내. 바뀐 것이 없으면 null */
export function selectionFixMessage(fix: SelectionFix, defaultSourceName?: string): string | null {
  const parts: string[] = []
  if (fix.removedTopics > 0) parts.push(`다른 곳에서 지워진 주제 ${fix.removedTopics}개를 뺐어요`)
  if (fix.sourceChanged === 'auto') parts.push('지워진 출처 대신 링크로 자동 판별해요')
  if (fix.sourceChanged === 'default') parts.push(`지워진 출처를 '${defaultSourceName ?? '기본 출처'}'(으)로 바꿨어요`)
  return parts.length ? parts.join('. ') + '.' : null
}
