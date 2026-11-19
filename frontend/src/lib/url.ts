/** http/https 주소만 링크로 허용 (javascript: 등 차단) */
export function safeHref(url: string): string | undefined {
  try {
    const u = new URL(url)
    return u.protocol === 'http:' || u.protocol === 'https:' ? u.href : undefined
  } catch {
    return undefined
  }
}

export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

export function isValidHttpUrl(s: string): boolean {
  return safeHref(s.trim()) !== undefined
}

/** 붙여넣은 텍스트에서 첫 번째 URL을 뽑는다 (공유 문구에 URL이 섞여 있는 경우 대비) */
export function extractUrl(text: string): string | null {
  const m = text.match(/https?:\/\/[^\s<>"']+/)
  return m ? m[0] : null
}
