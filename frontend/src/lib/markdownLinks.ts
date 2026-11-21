import { displayText } from './text'

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

// ------------------------------------------------ 링크 옆 실제 호스트 표시 (위장 링크 대비)
// 메모(특히 AI가 외부 페이지를 읽고 제안한 메모)에서 `[https://good.example](https://evil.example)`처럼
// 보이는 글자와 실제 주소가 다를 수 있다. 링크 옆에 실제 호스트(퓨니코드 그대로)를 보여 주고,
// 글자가 주소처럼 생겼는데 호스트가 다르면 경고한다.

/** 글자 안의 주소 조각: 스킴이 있는 것(…://) 또는 www.로 시작하는 것. 한글 조사(…에서)는 주소에 넣지 않는다 */
const URL_TOKEN_RE = /(?:\b[a-z][a-z0-9+.-]*:\/\/|\bwww\.)[^\s<>"'()[\]{}ᄀ-ᇿ㄰-㆏가-힣]+/giu

/** 글자 전체가 스킴 없는 도메인(뒤에 경로 가능)인지. 예: bank.example.com, example.com/login */
const BARE_DOMAIN_RE = /^(?:[\p{L}\p{N}](?:[\p{L}\p{N}-]*[\p{L}\p{N}])?\.)+(\p{L}{2,63})\.?(?::\d{1,5})?(?:[/?#][^\s]*)?$/u

/** 도메인처럼 보이지만 보통 파일·기술 이름인 끝부분 (예: Node.js, README.md). 경고만 하지 않을 뿐 호스트는 그대로 보여 준다 */
const NOT_TLD = new Set([
  'js', 'mjs', 'cjs', 'ts', 'tsx', 'jsx', 'md', 'py', 'rb', 'rs', 'go', 'java', 'kt', 'swift', 'php', 'sh',
  'json', 'yml', 'yaml', 'toml', 'xml', 'csv', 'txt', 'html', 'htm', 'css', 'scss', 'pdf', 'png', 'jpg',
  'jpeg', 'gif', 'svg', 'webp', 'zip', 'gz', 'tar', 'exe', 'dmg', 'apk', 'dll', 'so', 'mp3', 'mp4', 'mov',
  'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'hwp',
])

/** 비교용 호스트: 소문자, 끝의 점·앞의 www. 제거 */
function comparableHost(host: string): string {
  return host.toLowerCase().replace(/\.$/, '').replace(/^www\./, '')
}

function hostFromToken(token: string): string | null {
  // 문장 끝 구두점은 주소에서 뺀다
  const t = token.replace(/[.,;:!?…。、]+$/u, '')
  const withScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(t) ? t : 'http://' + t
  try {
    const h = new URL(withScheme).hostname
    return h ? h : null
  } catch {
    return null
  }
}

/** 주소 조각의 authority(스킴 뒤 ~ 첫 / ? #)에 사용자 정보(@)가 있는지. 예: https://good.example:x@evil.example */
function tokenHasUserinfo(token: string): boolean {
  const rest = token.replace(/^[a-z][a-z0-9+.-]*:\/\//i, '')
  const authority = rest.split(/[/?#]/, 1)[0]
  return authority.includes('@')
}

/** 링크 글자에 사용자 정보 형태의 주소가 있는지 (앞부분을 다른 주소처럼 보이게 하는 위장) */
export function linkTextHasUserinfo(text: string): boolean {
  return [...displayText(text).trim().matchAll(URL_TOKEN_RE)].some((m) => tokenHasUserinfo(m[0]))
}

/** 링크 글자에서 주소처럼 보이는 부분의 호스트들 (퓨니코드로 정규화). 글자 방향 서식 문자는 먼저 지운다 */
export function hostsInLinkText(text: string): string[] {
  const hosts: string[] = []
  const s = displayText(text).trim()
  for (const m of s.matchAll(URL_TOKEN_RE)) {
    const h = hostFromToken(m[0])
    if (h) hosts.push(h)
  }
  if (hosts.length === 0) {
    const m = BARE_DOMAIN_RE.exec(s)
    if (m && !NOT_TLD.has(m[1].toLowerCase())) {
      const h = hostFromToken(s)
      if (h) hosts.push(h)
    }
  }
  return hosts
}

export interface LinkHostInfo {
  /** 실제로 열리는 호스트 (URL 파서가 정규화한 값: 소문자, 국제화 도메인은 xn-- 퓨니코드) */
  host: string
  /** 링크 글자가 주소처럼 생겼는데 실제 호스트와 다르다 */
  mismatch: boolean
  /** 링크 옆에 호스트를 보여 줄지. 글자가 이미 같은 호스트를 그대로 담고 있을 때만 생략한다 */
  showHost: boolean
}

/**
 * href(markdownLinkHref를 통과한 http/https 주소)와 링크 글자로 표시할 호스트 정보를 만든다.
 * href가 http/https가 아니면 null.
 */
export function linkHostInfo(href: string, text: string): LinkHostInfo | null {
  const safe = markdownLinkHref(href)
  if (!safe) return null
  const host = new URL(safe).hostname
  const shown = displayText(text)
  const textHosts = hostsInLinkText(shown)
  // 사용자 정보 형태(https://good.example:x@evil.example)는 앞부분이 다른 주소처럼 읽히므로 다른 주소로 본다
  const mismatch =
    linkTextHasUserinfo(shown) || textHosts.some((h) => comparableHost(h) !== comparableHost(host))
  // 글자에 실제 호스트가 글자 그대로 들어 있으면(자동 링크 등) 같은 말을 반복하지 않는다.
  // 국제화 도메인처럼 글자와 퓨니코드가 다르면 퓨니코드를 보여 준다 (비슷한 글자 위장 대비).
  const redundant = textHosts.length > 0 && !mismatch && shown.toLowerCase().includes(host)
  return { host, mismatch, showHost: mismatch || !redundant }
}

/** react-markdown이 넘겨주는 hast 노드의 글자만 모은다 */
export function hastText(node: unknown): string {
  if (!node || typeof node !== 'object') return ''
  const n = node as { type?: unknown; value?: unknown; children?: unknown }
  if (n.type === 'text' && typeof n.value === 'string') return n.value
  if (Array.isArray(n.children)) return n.children.map(hastText).join('')
  return ''
}
