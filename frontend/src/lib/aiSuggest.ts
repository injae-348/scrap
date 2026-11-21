// AI로 채우기(POST /ai/extract) 요청·응답 처리 규칙. 계약: docs/API.md "AI 세부 규칙 (v1.5)"
import type { AiExtractResponse, Topic } from '../api/types'

/** 붙여넣은 본문 최대 길이 (서버: 앞뒤 공백 제거 후 50,000자) */
export const BODY_MAX = 50_000

/** 주제 이름 길이 (서버 규칙: 앞뒤 공백 제거 후 1~30자) */
const TOPIC_NAME_MAX = 30

/** \t \n \r 를 뺀 제어문자 (C0, DEL, C1). 서버는 이런 글자가 든 본문을 400으로 거부한다 */
// eslint-disable-next-line no-control-regex
const BODY_CONTROL_RE = /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F]/g

/**
 * 보낼 본문으로 정리한다: 허용되지 않는 제어문자를 지우고 앞뒤 공백을 뺀다.
 * 빈 문자열이면 서버는 "본문 없음"으로 보므로 호출한 쪽에서 보내지 않는다.
 */
export function cleanPastedBody(text: string): string {
  return text.replace(BODY_CONTROL_RE, '').trim()
}

const fold = (s: string) => s.trim().toLowerCase()

/**
 * AI가 제안한 주제 이름을 기존 주제와 대소문자 무시로 맞춘다.
 * - matchedIds: 이미 있는 주제 (제안 순서, 중복 없음)
 * - newNames: 없는 이름. 자동으로 만들지 않고 "새 주제 제안"으로만 보여 준다 (중복·빈 이름·30자 초과 제외)
 */
export function matchTopicSuggestions(suggestions: string[], topics: Topic[]): { matchedIds: number[]; newNames: string[] } {
  const matchedIds: number[] = []
  const newNames: string[] = []
  const seen = new Set<string>()
  for (const raw of suggestions) {
    if (typeof raw !== 'string') continue
    const name = raw.trim()
    const key = fold(name)
    if (!name || name.length > TOPIC_NAME_MAX || seen.has(key)) continue
    seen.add(key)
    const existing = topics.find((t) => fold(t.name) === key)
    if (existing) {
      if (!matchedIds.includes(existing.id)) matchedIds.push(existing.id)
    } else newNames.push(name)
  }
  return { matchedIds, newNames }
}

export type AiField = 'title' | 'memo' | 'due_date'

/**
 * 제안값을 어느 칸에 바로 채우고, 어느 칸은 확인을 받을지 정한다.
 * - 빈 칸이거나, 이전 AI 제안으로 채운 뒤 손대지 않은 칸(prevFilled) → 바로 채움 (apply)
 * - 이미 입력한 칸 → 덮어쓰지 않고 "이 제안으로 바꾸기" 확인 (pending)
 * - 제안이 없거나(null·빈 문자열) 지금 값과 같으면 아무것도 하지 않는다
 */
export function planAiFill(
  current: Record<AiField, string>,
  prevFilled: AiField[],
  res: Pick<AiExtractResponse, 'title' | 'memo' | 'due_date'>,
): { apply: Partial<Record<AiField, string>>; pending: Partial<Record<AiField, string>> } {
  const apply: Partial<Record<AiField, string>> = {}
  const pending: Partial<Record<AiField, string>> = {}
  const fields: AiField[] = ['title', 'due_date', 'memo']
  for (const f of fields) {
    const v = res[f]
    if (typeof v !== 'string' || !v.trim()) continue
    const cur = current[f]
    if (cur.trim() === '' || prevFilled.includes(f)) apply[f] = v
    else if (cur !== v) pending[f] = v
  }
  return { apply, pending }
}
