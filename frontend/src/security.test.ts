// 코드 전체 검사: 제목·메모·URL을 HTML로 끼워 넣는 경로가 없어야 한다.
import ts from 'typescript'
import { describe, expect, it } from 'vitest'

const sources = import.meta.glob(['./**/*.{ts,tsx}', '!./**/*.test.{ts,tsx}'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

/**
 * 주석만 빼고 검사한다 (규칙을 설명하는 주석에 같은 단어가 나온다).
 * TypeScript 파서로 읽어 주석 없이 다시 출력하므로 문자열·JSX 텍스트 안의 // 는 그대로 남는다.
 */
function stripComments(code: string, file = 'x.tsx'): string {
  const sf = ts.createSourceFile(file, code, ts.ScriptTarget.Latest, false, file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS)
  return ts.createPrinter({ removeComments: true }).printFile(sf)
}

const code = Object.fromEntries(Object.entries(sources).map(([f, c]) => [f, stripComments(c, f)]))

describe('주석 제거', () => {
  it('주석은 지우고 문자열·JSX 텍스트 안의 // 는 남긴다', () => {
    const out = stripComments(
      [
        '// innerHTML 설명 주석',
        '/* outerHTML 설명 */',
        "const a = 'x//y'; el.innerHTML = a",
        'const b = <p>https://example.com // dangerouslySetInnerHTML</p>',
      ].join('\n'),
    )
    expect(out).not.toContain('설명')
    expect(out).toContain('x//y')
    expect(out).toContain('el.innerHTML = a')
    expect(out).toContain('// dangerouslySetInnerHTML')
  })
})

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
