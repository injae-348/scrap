import { describe, expect, it } from 'vitest'
import { BODY_MAX, cleanPastedBody, matchTopicSuggestions, planAiFill } from './aiSuggest'

const topics = [
  { id: 1, name: 'Claude' },
  { id: 2, name: '공모전' },
  { id: 3, name: 'docker' },
]

describe('cleanPastedBody', () => {
  it('\\t \\n \\r 외 제어문자(NUL·C1·DEL)를 지우고 앞뒤 공백을 뺀다', () => {
    expect(cleanPastedBody('  첫 줄\u0000\n\t둘째\r\n셋\u0007째\u007f\u0085  ')).toBe('첫 줄\n\t둘째\r\n셋째')
  })

  it('공백뿐이면 빈 문자열 (보내지 않음)', () => {
    expect(cleanPastedBody(' \n\t ')).toBe('')
  })

  it('최대 길이는 50,000자', () => {
    expect(BODY_MAX).toBe(50_000)
  })
})

describe('matchTopicSuggestions', () => {
  it('기존 주제는 대소문자 무시로 맞추고, 없는 이름은 새 주제 제안으로만 돌려준다', () => {
    const r = matchTopicSuggestions(['claude', ' DOCKER ', '보안'], topics)
    expect(r.matchedIds).toEqual([1, 3])
    expect(r.newNames).toEqual(['보안'])
  })

  it('중복(대소문자 무시)·빈 이름·30자 초과는 뺀다', () => {
    const r = matchTopicSuggestions(['Claude', 'CLAUDE', '', '   ', 'New', 'new', 'x'.repeat(31), 'y'.repeat(30)], topics)
    expect(r.matchedIds).toEqual([1])
    expect(r.newNames).toEqual(['New', 'y'.repeat(30)])
  })

  it('서버가 기존 이름으로 정규화해 준 값도 그대로 맞는다', () => {
    expect(matchTopicSuggestions(['공모전'], topics)).toEqual({ matchedIds: [2], newNames: [] })
  })
})

describe('planAiFill (이미 입력한 칸 덮어쓰기 확인)', () => {
  const res = { title: 'AI 제목', memo: '## 요약\n- 내용', due_date: '2026-12-31' }

  it('빈 칸은 바로 채운다', () => {
    const p = planAiFill({ title: '', memo: '  ', due_date: '' }, [], res)
    expect(p.apply).toEqual({ title: 'AI 제목', memo: '## 요약\n- 내용', due_date: '2026-12-31' })
    expect(p.pending).toEqual({})
  })

  it('이미 입력한 칸은 덮어쓰지 않고 확인용 제안으로 둔다', () => {
    const p = planAiFill({ title: '내가 쓴 제목', memo: '내 메모', due_date: '' }, [], res)
    expect(p.apply).toEqual({ due_date: '2026-12-31' })
    expect(p.pending).toEqual({ title: 'AI 제목', memo: '## 요약\n- 내용' })
  })

  it('이전 AI 제안으로 채우고 손대지 않은 칸은 새 제안으로 바꾼다', () => {
    const p = planAiFill({ title: '이전 AI 제목', memo: '내 메모', due_date: '' }, ['title'], res)
    expect(p.apply.title).toBe('AI 제목')
    expect(p.pending).toEqual({ memo: '## 요약\n- 내용' })
  })

  it('제안이 없거나(null·빈 문자열) 지금 값과 같으면 아무것도 하지 않는다', () => {
    const p = planAiFill({ title: 'AI 제목', memo: '', due_date: '' }, [], { title: 'AI 제목', memo: null, due_date: '' })
    expect(p).toEqual({ apply: {}, pending: {} })
  })
})
