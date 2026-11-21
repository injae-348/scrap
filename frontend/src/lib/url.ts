import { displayText } from './text'

// URL 표시·링크 처리. 링크로 만드는 것은 http/https뿐이다 (javascript:, data: 등은 링크로 만들지 않음).

function parseHttp(url: string): URL | null {
  try {
    const u = new URL(url.trim())
    return u.protocol === 'http:' || u.protocol === 'https:' ? u : null
  } catch {
    return null
  }
}

/** http/https 주소만 링크로 허용한다. 사용자 정보(user:pass@)는 지운 주소를 돌려준다 */
export function safeHref(url: string): string | undefined {
  const u = parseHttp(url)
  if (!u) return undefined
  u.username = ''
  u.password = ''
  return u.href
}

/** 목록용 짧은 호스트 (www. 제거). 해석할 수 없으면 빈 문자열 */
export function hostOf(url: string): string {
  const u = parseHttp(url)
  return u ? u.hostname.replace(/^www\./, '') : ''
}

export interface DisplayUrl {
  /** 강조할 호스트 (해석 불가면 '') */
  host: string
  /** 호스트 앞(스킴) */
  prefix: string
  /** 호스트 뒤(포트·경로·쿼리·해시) */
  rest: string
  /** 사용자 정보가 있어서 가렸는지 */
  maskedCredentials: boolean
}

/**
 * 표시용 URL: 호스트를 따로 떼어 강조할 수 있게 하고, 사용자 정보(user:pass@)는 가린다.
 * http/https가 아니면 host는 ''이고 rest에 원문을 그대로 둔다 (텍스트로만 표시).
 */
export function displayUrl(url: string): DisplayUrl {
  const u = parseHttp(url)
  if (!u) return { host: '', prefix: '', rest: url, maskedCredentials: false }
  const masked = !!(u.username || u.password)
  const port = u.port ? ':' + u.port : ''
  const path = u.pathname === '/' && !u.search && !u.hash ? '' : u.pathname
  let rest = port + path + u.search + u.hash
  try {
    // 한글 경로 등을 읽기 쉽게 풀고, 글자 방향 서식 문자는 지운다
    rest = displayText(decodeURI(rest))
  } catch {
    // 잘못된 퍼센트 인코딩은 그대로 둔다
  }
  // 호스트는 URL 파서가 정규화한 값(국제화 도메인은 xn-- 형식)을 그대로 쓴다
  return { host: u.hostname, prefix: u.protocol + '//' + (masked ? '***@' : ''), rest, maskedCredentials: masked }
}

export function isValidHttpUrl(s: string): boolean {
  return parseHttp(s) !== null
}

/** 붙여넣은 텍스트에서 첫 번째 URL을 뽑는다 (공유 문구에 URL이 섞여 있는 경우 대비) */
export function extractUrl(text: string): string | null {
  const m = text.match(/https?:\/\/[^\s<>"']+/i)
  return m ? m[0] : null
}

/**
 * 출처 도메인 패턴 입력을 호스트 이름으로 정리한다.
 * "https://www.example.com/path" 처럼 주소를 붙여넣어도 호스트만 남긴다.
 * 형식이 틀린 항목이 있으면 invalid에 담는다.
 */
export function parseDomainPatterns(input: string): { patterns: string[]; invalid: string[] } {
  const patterns: string[] = []
  const invalid: string[] = []
  for (const raw of input.split(/[,\s]+/)) {
    const t = raw.trim().toLowerCase()
    if (!t) continue
    let host = t
    if (/^[a-z][a-z0-9+.-]*:\/\//.test(t)) {
      const u = parseHttp(t)
      host = u ? u.hostname : ''
    }
    host = host.replace(/\.$/, '')
    if (host && host.length <= 253 && /^[a-z0-9-]+(\.[a-z0-9-]+)*$/.test(host)) {
      if (!patterns.includes(host)) patterns.push(host)
    } else invalid.push(raw.trim())
  }
  return { patterns, invalid }
}
