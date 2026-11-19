/** 로컬 시간 기준 YYYY-MM-DD */
export function toISODate(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export function todayISO(): string {
  return toISODate(new Date())
}

export function addDaysISO(days: number, from = new Date()): string {
  const d = new Date(from)
  d.setDate(d.getDate() + days)
  return toISODate(d)
}

function parseISODate(s: string): Date {
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y, m - 1, d)
}

/** 오늘부터 마감일까지 남은 일수 (지났으면 음수) */
export function daysUntil(due: string): number {
  const t = parseISODate(todayISO()).getTime()
  const d = parseISODate(due).getTime()
  return Math.round((d - t) / 86_400_000)
}

/** 마감 임박 기준 (일) */
export const DUE_SOON_DAYS = 7

export type DueStatus = 'past' | 'soon' | 'later'

export function dueStatus(due: string | null): DueStatus | null {
  if (!due) return null
  const n = daysUntil(due)
  if (n < 0) return 'past'
  if (n <= DUE_SOON_DAYS) return 'soon'
  return 'later'
}

export function dueLabel(due: string): string {
  const n = daysUntil(due)
  if (n < 0) return `${-n}일 지남`
  if (n === 0) return '오늘 마감'
  if (n <= DUE_SOON_DAYS) return `D-${n}`
  return formatDate(due)
}

export function formatDate(iso: string): string {
  const d = iso.length <= 10 ? parseISODate(iso) : new Date(iso)
  const sameYear = d.getFullYear() === new Date().getFullYear()
  return d.toLocaleDateString('ko-KR', {
    year: sameYear ? undefined : 'numeric',
    month: 'long',
    day: 'numeric',
  })
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString('ko-KR', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** "3분 전", "어제" 같은 상대 시간 */
export function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const min = Math.floor(diff / 60_000)
  if (min < 1) return '방금 전'
  if (min < 60) return `${min}분 전`
  const h = Math.floor(min / 60)
  if (h < 24) return `${h}시간 전`
  const d = Math.floor(h / 24)
  if (d === 1) return '어제'
  if (d < 30) return `${d}일 전`
  return formatDate(iso)
}
