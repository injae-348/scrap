// 코드 전체 검사: 제목·메모·URL을 HTML로 끼워 넣는 경로가 없어야 한다.
import { describe, expect, it } from 'vitest'

const sources = import.meta.glob(['./**/*.{ts,tsx}', '!./**/*.test.{ts,tsx}'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

/** 주석은 빼고 검사한다 (규칙을 설명하는 주석에 같은 단어가 나온다). 문자열 안의 // 뒤도 잘리지만 검사 목적에는 충분하다 */
function stripComments(code: string): string {
  return code.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1')
}

const code = Object.fromEntries(Object.entries(sources).map(([f, c]) => [f, stripComments(c)]))

describe('렌더링 안전 (소스 검사)', () => {
  it('소스 파일을 읽었다', () => {
    expect(Object.keys(sources).length).toBeGreaterThan(20)
  })

  it.each(['dangerouslySetInnerHTML', 'innerHTML', 'outerHTML', 'insertAdjacentHTML', 'document.write', 'rehype-raw', 'eval('])(
    '%s 사용 0건',
    (needle) => {
      const hits = Object.entries(code)
        .filter(([, c]) => c.includes(needle))
        .map(([file]) => file)
      expect(hits).toEqual([])
    },
  )

  it('인증 토큰을 브라우저 저장소에 두지 않는다', () => {
    const hits = Object.entries(code)
      .filter(([, c]) => /localStorage|sessionStorage|indexedDB|document\.cookie/.test(c))
      .map(([file]) => file)
    expect(hits).toEqual([])
  })
})
