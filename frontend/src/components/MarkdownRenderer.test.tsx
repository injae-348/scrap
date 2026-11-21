// 메모 마크다운 렌더링 안전 규칙 테스트 (원시 HTML·위험한 링크·이미지).
import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import MarkdownRenderer from './MarkdownRenderer'

afterEach(cleanup)

function renderMd(md: string) {
  const { container } = render(<MarkdownRenderer>{md}</MarkdownRenderer>)
  return container
}

/** 렌더링 결과 전체에 대한 공통 검사: 실행될 수 있는 요소·속성이 없어야 한다 */
function expectInert(container: HTMLElement) {
  expect(container.querySelector('script, iframe, object, embed, img, style, svg, form, input')).toBeNull()
  for (const el of container.querySelectorAll('*')) {
    for (const attr of el.getAttributeNames()) {
      expect(attr.startsWith('on'), `${el.tagName} has ${attr}`).toBe(false)
      expect(attr).not.toBe('style')
      expect(attr).not.toBe('srcdoc')
    }
  }
  for (const a of container.querySelectorAll('a')) {
    const href = a.getAttribute('href') ?? ''
    expect(href).toMatch(/^https?:\/\//)
    expect(a.getAttribute('target')).toBe('_blank')
    const rel = (a.getAttribute('rel') ?? '').split(/\s+/)
    expect(rel).toContain('noopener')
    expect(rel).toContain('noreferrer')
  }
}

describe('MarkdownRenderer: 원시 HTML', () => {
  it('<img onerror>를 렌더링하지 않는다', () => {
    const c = renderMd('앞 <img src=x onerror=alert(1)> 뒤\n\n<img src=x onerror=alert(1)>')
    expect(c.querySelector('img')).toBeNull()
    expect(c.innerHTML).not.toContain('onerror')
    expect(c.textContent).toContain('앞')
    expect(c.textContent).toContain('뒤')
    expectInert(c)
  })

  it('<script>를 렌더링하지 않는다', () => {
    const c = renderMd('<script>alert(1)</script>\n\n문단 <script>alert(2)</script> 끝')
    expect(c.querySelector('script')).toBeNull()
    expect(c.innerHTML).not.toContain('<script')
    expectInert(c)
  })

  it('그 밖의 HTML 태그(iframe, a, svg, style 속성)도 렌더링하지 않는다', () => {
    const c = renderMd(
      [
        '<iframe src="https://example.com"></iframe>',
        '<a href="javascript:alert(1)">링크</a>',
        '<svg onload=alert(1)></svg>',
        '<p style="color:red" onclick="alert(1)">x</p>',
        '<details open ontoggle=alert(1)>',
      ].join('\n\n'),
    )
    expect(c.querySelector('a')).toBeNull()
    expectInert(c)
  })
})

describe('MarkdownRenderer: 링크 스킴', () => {
  it.each([
    ['javascript 소문자', '[x](javascript:alert(1))'],
    ['JAVASCRIPT 대문자', '[x](JAVASCRIPT:alert(1))'],
    ['대소문자 섞기', '[x](JaVaScRiPt:alert(1))'],
    ['앞 공백·꺾쇠', '[x](< javascript:alert(1)>)'],
    ['HTML 엔티티', '[x](&#106;avascript:alert(1))'],
    ['탭 섞기', '[x](java\tscript:alert(1))'],
    ['data:text/html', '[x](data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)'],
    ['data: 평문', '[x](data:text/html,hello)'],
    ['vbscript', '[x](vbscript:msgbox(1))'],
    ['file', '[x](file:///etc/passwd)'],
    ['mailto(링크로 만들지 않음)', '[x](mailto:someone@example.com)'],
    ['상대 경로', '[x](/settings)'],
    ['참조식 링크', '[x][r]\n\n[r]: javascript:alert(1)'],
  ])('%s → 링크가 아니라 텍스트', (_name, md) => {
    const c = renderMd(md)
    expect(c.querySelector('a')).toBeNull()
    expect(c.textContent).toContain('x')
    expect(c.innerHTML.toLowerCase()).not.toContain('javascript:')
    expect(c.innerHTML.toLowerCase()).not.toContain('vbscript:')
    expect(c.innerHTML.toLowerCase()).not.toContain('href="data:')
    expectInert(c)
  })

  it('정상 https 링크는 새 창 + rel="noopener noreferrer"', () => {
    const c = renderMd('[예시](https://example.com/path?q=1)')
    const a = c.querySelector('a')
    expect(a).not.toBeNull()
    expect(a!.getAttribute('href')).toBe('https://example.com/path?q=1')
    expect(a!.getAttribute('target')).toBe('_blank')
    expect(a!.getAttribute('rel')).toBe('noopener noreferrer')
    expect(a!.textContent).toBe('예시')
    expectInert(c)
  })

  it('http 링크도 허용', () => {
    const c = renderMd('[예시](http://example.com)')
    expect(c.querySelector('a')!.getAttribute('href')).toBe('http://example.com/')
    expectInert(c)
  })

  it('자동 링크(<https://…>, GFM 맨 주소, www.)는 안전한 링크가 된다', () => {
    const c = renderMd('<https://example.com/a>\n\nhttps://example.org/b\n\nwww.example.net/c')
    const hrefs = [...c.querySelectorAll('a')].map((a) => a.getAttribute('href'))
    expect(hrefs).toEqual(['https://example.com/a', 'https://example.org/b', 'http://www.example.net/c'])
    expectInert(c)
  })

  it('자동 링크 형태의 javascript:는 링크가 되지 않는다', () => {
    const c = renderMd('<javascript:alert(1)>')
    expect(c.querySelector('a')).toBeNull()
    expectInert(c)
  })

  it('주소의 사용자 정보(user:pass@)는 링크에서 뺀다', () => {
    const c = renderMd('[x](https://user:secret@example.com/p)')
    const href = c.querySelector('a')!.getAttribute('href')!
    expect(href).toBe('https://example.com/p')
    expect(href).not.toContain('secret')
  })
})

describe('MarkdownRenderer: 이미지', () => {
  it('이미지 문법은 <img>가 아니라 링크로만 보여 준다', () => {
    const c = renderMd('![설명](https://example.com/a.png)')
    expect(c.querySelector('img')).toBeNull()
    const a = c.querySelector('a')!
    expect(a.getAttribute('href')).toBe('https://example.com/a.png')
    expect(a.textContent).toBe('[이미지: 설명]')
    expectInert(c)
  })

  it('위험한 스킴의 이미지는 링크도 만들지 않는다', () => {
    const c = renderMd('![설명](javascript:alert(1))\n\n![d](data:image/png;base64,AAAA)')
    expect(c.querySelector('img')).toBeNull()
    expect(c.querySelector('a')).toBeNull()
    expect(c.textContent).toContain('[이미지: 설명]')
    expectInert(c)
  })

  it('링크 안의 이미지도 <img>가 아니다', () => {
    const c = renderMd('[![a](https://example.com/i.png)](https://example.com)')
    expect(c.querySelector('img')).toBeNull()
    expectInert(c)
  })
})

describe('MarkdownRenderer: 일반 마크다운', () => {
  it('제목·목록·코드·표는 그대로 렌더링한다', () => {
    const c = renderMd('# 제목\n\n- 하나\n- 둘\n\n`code`\n\n| a | b |\n|---|---|\n| 1 | 2 |')
    expect(c.querySelector('h1')!.textContent).toBe('제목')
    expect(c.querySelectorAll('li')).toHaveLength(2)
    expect(c.querySelector('code')!.textContent).toBe('code')
    expect(c.querySelector('table')).not.toBeNull()
    expectInert(c)
  })
})

describe('MarkdownRenderer: 링크 옆 실제 호스트', () => {
  it('글자 링크 옆에 실제 호스트를 링크 밖에 작게 보여 준다', () => {
    const c = renderMd('[공식 문서](https://docs.example.com/guide)')
    const a = c.querySelector('a')!
    expect(a.textContent).toBe('공식 문서')
    const host = c.querySelector('[data-link-host]')!
    expect(host.textContent).toBe('(docs.example.com)')
    expect(a.contains(host)).toBe(false)
    expect(host.getAttribute('data-link-host')).toBe('')
    expectInert(c)
  })

  it('주소처럼 생긴 글자와 실제 호스트가 다르면 경고한다', () => {
    const c = renderMd('[https://bank.example.com](https://evil.example/login)')
    const host = c.querySelector('[data-link-host]')!
    expect(host.getAttribute('data-link-host')).toBe('mismatch')
    expect(host.textContent).toContain('글자와 다른 주소')
    expect(host.textContent).toContain('evil.example')
    expectInert(c)
  })

  it('스킴 없는 도메인 글자도 다르면 경고', () => {
    const c = renderMd('[bank.example.com](https://evil.example)')
    expect(c.querySelector('[data-link-host="mismatch"]')).not.toBeNull()
  })

  it('강조 안의 주소 글자도 읽는다', () => {
    const c = renderMd('[**https://bank.example.com**](https://evil.example)')
    expect(c.querySelector('[data-link-host="mismatch"]')).not.toBeNull()
  })

  it('국제화 도메인은 퓨니코드 그대로 보여 준다', () => {
    const c = renderMd('[은행](https://exаmple.com/)')
    expect(c.querySelector('[data-link-host]')!.textContent).toBe('(xn--exmple-4nf.com)')
  })

  it('자동 링크처럼 글자에 같은 호스트가 있으면 반복하지 않는다', () => {
    const c = renderMd('<https://example.com/a>\n\nhttps://example.org/b')
    expect(c.querySelectorAll('a')).toHaveLength(2)
    expect(c.querySelector('[data-link-host]')).toBeNull()
  })

  it('이미지 링크에도 호스트를 보여 준다', () => {
    const c = renderMd('![설명](https://cdn.example.net/a.png)')
    expect(c.querySelector('[data-link-host]')!.textContent).toBe('(cdn.example.net)')
  })

  it('링크가 되지 않는 스킴은 호스트도 없다', () => {
    const c = renderMd('[https://bank.example.com](javascript:alert(1))')
    expect(c.querySelector('a')).toBeNull()
    expect(c.querySelector('[data-link-host]')).toBeNull()
  })
})

describe('MarkdownRenderer: 글자 방향 서식 문자 (위장 링크)', () => {
  it('RLO로 뒤집어 다른 주소처럼 보이게 한 링크 글자도 경고하고, 방향 문자는 남기지 않는다', () => {
    // 화면에서는 https://good.example 처럼 보이는 뒤집힌 글자
    const c = renderMd('[\u202Eelpmaxe.doog//:sptth](https://evil.example)\n\n[\u202Ehttps://bank.example.com](https://evil.example/x)')
    expect(c.textContent).not.toMatch(/[\u202A-\u202E\u2066-\u2069\u200E\u200F\u061C]/)
    const hosts = [...c.querySelectorAll('[data-link-host]')]
    expect(hosts).toHaveLength(2)
    // 뒤집힌 글자는 주소로 읽히지 않으므로 호스트를 보여 주고, 방향 문자를 지운 주소 글자는 경고한다
    expect(hosts[0].textContent).toContain('evil.example')
    expect(hosts[1].getAttribute('data-link-host')).toBe('mismatch')
    expectInert(c)
  })

  it('링크와 호스트 표시는 각각 <bdi>로 격리한다', () => {
    const c = renderMd('[공식 문서](https://docs.example.com/guide)')
    const a = c.querySelector('a')!
    expect(a.parentElement!.tagName).toBe('BDI')
    expect(c.querySelector('[data-link-host]')!.tagName).toBe('BDI')
  })

  it('본문 텍스트의 방향 문자도 지운다 (U+061C, U+2066~2069 포함)', () => {
    const c = renderMd('앞\u061C\u2067뒤\u2069 \u200F끝')
    expect(c.textContent).toBe('앞뒤 끝')
  })

  it('사용자 정보 형태의 링크 글자(…@evil.example)는 호스트 표시를 생략하지 않고 경고한다', () => {
    const c = renderMd('[https://www.good-bank.example:login;verify=true@evil.example](https://evil.example)')
    const host = c.querySelector('[data-link-host]')!
    expect(host.getAttribute('data-link-host')).toBe('mismatch')
    expect(host.textContent).toContain('evil.example')
  })
})
