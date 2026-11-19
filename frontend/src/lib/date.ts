// 날짜 판정(마감 임박·지남, 오늘)은 API.md 규칙대로 Asia/Seoul 기준이다.
// 브라우저 시간대가 달라도(해외 출장 등) 서버와 같은 결과가 나오게 한다.

export const APP_TIME_ZONE = 'Asia/Seoul'

const isoDateFmt = new Intl.DateTimeFormat('en-CA', {
  timeZone: APP_TIME_ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})

/** 주어진 시각의 Asia/Seoul 날짜 (YYYY-MM-DD) */
export function toISODate(d: Date): string {
  return isoDateFmt.format(d)
}

/** Asia/Seoul 기준 오늘 (YYYY-MM-DD) */
export function todayISO(): string {
  return toISODate(new Date())
}

/** YYYY-MM-DD → 그 날짜의 UTC 자정 (날짜 계산 전용, 시간대 영향 없음) */
function dateOnlyToUTC(s: string): number {
  const [y, m, d] = s.split('-').map(Number)
  return Date.UTC(y, m - 1, d)
}

function utcToDateOnly(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10)
}

/** Asia/Seoul 기준 오늘에서 days일 뒤 (YYYY-MM-DD) */
export function addDaysISO(days: number): string {
  return utcToDateOnly(dateOnlyToUTC(todayISO()) + days * 86_400_000)
}

/** Asia/Seoul 기준 오늘부터 마감일까지 남은 일수 (지났으면 음수) */
export function daysUntil(due: string): number {
  return Math.round((dateOnlyToUTC(due) - dateOnlyToUTC(todayISO())) / 86_400_000)
}

/** 마감 임박 기준 (일) — API.md의 due=upcoming(오늘~오늘+7일)과 같다 */
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

/** 날짜(YYYY-MM-DD) 또는 일시(ISO)를 "11월 22일" 형식으로. 올해가 아니면 연도 포함 */
export function formatDate(iso: string): string {
  const dateOnly = iso.length <= 10
  const d = dateOnly ? new Date(dateOnlyToUTC(iso)) : new Date(iso)
  // 날짜만 있는 값은 UTC 자정으로 만들었으니 UTC로 표시해야 하루가 밀리지 않는다
  const tz = dateOnly ? 'UTC' : APP_TIME_ZONE
  const year = (dateOnly ? iso : toISODate(d)).slice(0, 4)
  const sameYear = year === todayISO().slice(0, 4)
  return d.toLocaleDateString('ko-KR', {
    timeZone: tz,
    year: sameYear ? undefined : 'numeric',
    month: 'long',
    day: 'numeric',
  })
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString('ko-KR', {
    timeZone: APP_TIME_ZONE,
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
