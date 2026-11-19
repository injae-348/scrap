// 자주 쓰는 Tailwind 클래스 묶음

/** 너비 지정 없는 입력칸 스타일 (select, date 등 내용 너비로 쓸 때) */
export const fieldCls =
  'rounded-lg border border-line bg-bg px-3 min-h-11 text-fg placeholder:text-muted/70 ' +
  'focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/25 disabled:opacity-60'

export const inputCls = 'w-full ' + fieldCls

export const textareaCls =
  'w-full rounded-lg border border-line bg-bg px-3 py-2.5 text-fg placeholder:text-muted/70 leading-relaxed ' +
  'focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/25'

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(' ')
}
