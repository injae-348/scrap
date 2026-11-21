import { describe, expect, it } from 'vitest'
import type { Scrap } from '../api/types'
import { buildScrapCreate, buildScrapPatch, reconcileSelection, selectionFixMessage, type ScrapFormValues } from './scrapForm'

const initial: Scrap = {
  id: 7,
  url: 'https://example.com/a',
  title: '가상 제목',
  memo: '메모',
  source: { id: 3, name: '일반사이트' },
  topics: [
    { id: 1, name: 'alpha' },
    { id: 2, name: 'beta' },
  ],
  liked: true,
  due_date: '2026-12-31',
  created_at: '2026-11-20T10:00:00+09:00',
  updated_at: '2026-11-20T10:00:00+09:00',
}

const same: ScrapFormValues = {
  url: initial.url,
  title: initial.title,
  memo: initial.memo,
  sourceId: 3,
  topicIds: [2, 1],
  due: '2026-12-31',
}

describe('buildScrapPatch', () => {
  it('바뀐 것이 없으면 빈 본문 (주제 순서만 달라도 같음)', () => {
    expect(buildScrapPatch(initial, same)).toEqual({})
  })
  it('바뀐 필드만 보낸다', () => {
    expect(buildScrapPatch(initial, { ...same, title: '  새 제목 ' })).toEqual({ title: '새 제목' })
    expect(buildScrapPatch(initial, { ...same, topicIds: [1] })).toEqual({ topic_ids: [1] })
    expect(buildScrapPatch(initial, { ...same, due: '' })).toEqual({ due_date: null })
    expect(buildScrapPatch(initial, { ...same, sourceId: 5, memo: '새 메모' })).toEqual({ source_id: 5, memo: '새 메모' })
  })
  it('liked·id·source·topics·날짜는 절대 넣지 않는다', () => {
    const body = buildScrapPatch(initial, { ...same, url: 'https://example.com/b', title: '', memo: '', topicIds: [], due: '' })
    expect(Object.keys(body).sort()).toEqual(['due_date', 'memo', 'title', 'topic_ids', 'url'])
    expect(body).not.toHaveProperty('liked')
  })
})

describe('buildScrapCreate', () => {
  it('url만 있으면 url만 보낸다 (제목·출처는 서버가 정함)', () => {
    expect(buildScrapCreate({ url: ' https://example.com/x ', title: ' ', memo: '', sourceId: null, topicIds: [], due: '' })).toEqual({
      url: 'https://example.com/x',
    })
  })
  it('입력한 값은 source_id/topic_ids 형태로', () => {
    expect(
      buildScrapCreate({ url: 'https://example.com/x', title: '제목', memo: 'm', sourceId: 2, topicIds: [4], due: '2026-12-01' }),
    ).toEqual({ url: 'https://example.com/x', title: '제목', memo: 'm', source_id: 2, topic_ids: [4], due_date: '2026-12-01' })
  })
})

describe('reconcileSelection', () => {
  const sources = [
    { id: 1, is_default: false },
    { id: 3, is_default: true },
  ]
  const topics = [{ id: 1 }, { id: 2 }]

  it('목록에 있는 것만 있으면 그대로', () => {
    expect(reconcileSelection({ sourceId: 1, topicIds: [1, 2] }, { topics, sources }, 'edit')).toEqual({
      sourceId: 1,
      topicIds: [1, 2],
      removedTopics: 0,
      sourceChanged: null,
    })
  })
  it('지워진 주제는 뺀다', () => {
    const fix = reconcileSelection({ sourceId: null, topicIds: [1, 9, 2, 8] }, { topics, sources }, 'create')
    expect(fix.topicIds).toEqual([1, 2])
    expect(fix.removedTopics).toBe(2)
    expect(selectionFixMessage(fix)).toBe('다른 곳에서 지워진 주제 2개를 뺐어요.')
  })
  it('새 스크랩에서 출처가 지워졌으면 자동 판별(null)', () => {
    const fix = reconcileSelection({ sourceId: 7, topicIds: [] }, { topics, sources }, 'create')
    expect(fix.sourceId).toBeNull()
    expect(fix.sourceChanged).toBe('auto')
    expect(buildScrapCreate({ url: 'https://example.com', title: '', memo: '', sourceId: fix.sourceId, topicIds: [], due: '' })).not.toHaveProperty('source_id')
  })
  it('수정에서 출처가 지워졌으면 기본 출처', () => {
    const fix = reconcileSelection({ sourceId: 7, topicIds: [1] }, { topics, sources }, 'edit')
    expect(fix.sourceId).toBe(3)
    expect(fix.sourceChanged).toBe('default')
    expect(selectionFixMessage(fix, '일반사이트')).toBe("지워진 출처를 '일반사이트'(으)로 바꿨어요.")
  })
  it('출처 목록을 아직 못 받았으면 출처는 그대로', () => {
    expect(reconcileSelection({ sourceId: 7, topicIds: [] }, { topics, sources: [] }, 'edit').sourceId).toBe(7)
  })
})
