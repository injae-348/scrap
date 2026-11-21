/**
 * 마크다운 링크·이미지 주소 중 링크로 만들어도 되는 것만 돌려준다: 절대 주소의 http/https만.
 * 그 밖(javascript:, data:, vbscript:, file:, mailto:, 상대 경로, 해석 불가)은 undefined → 일반 텍스트.
 * 앞뒤 공백·제어문자·대소문자 섞기(JaVaScRiPt:) 같은 우회도 URL 파서가 정규화한 스킴으로 판정한다.
 */
export function markdownLinkHref(raw: string): string | undefined {
  if (typeof raw !== 'string' || !raw) return undefined
  let u: URL
  try {
    u = new URL(raw.trim())
  } catch {
    return undefined
  }
  if (u.protocol !== 'http:' && u.protocol !== 'https:') return undefined
  // 사용자 정보(user:pass@)는 링크에서 뺀다
  u.username = ''
  u.password = ''
  return u.href
}
