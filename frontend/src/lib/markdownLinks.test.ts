import { describe, expect, it } from 'vitest'
import { hastText, hostsInLinkText, linkHostInfo, linkTextHasUserinfo } from './markdownLinks'

describe('hostsInLinkText', () => {
  it.each([
    ['https://good.example/path', ['good.example']],
    ['공식 사이트 https://good.example에서 확인', ['good.example']],
    ['www.good.example/login 바로가기', ['www.good.example']],
    ['bank.example.com', ['bank.example.com']],
    ['example.com/login', ['example.com']],
    ['https://good.example.', ['good.example']],
    ['두 개: https://a.example, https://b.example', ['a.example', 'b.example']],
  ])('%s → %j', (text, hosts) => {
    expect(hostsInLinkText(text)).toEqual(hosts)
  })

  it.each(['여기', '공식 문서', 'Node.js', 'README.md', 'v1.2', '[이미지: 설명]', '3.14'])('주소처럼 보이지 않음: %s', (text) => {
    expect(hostsInLinkText(text)).toEqual([])
  })

  it('국제화 도메인은 퓨니코드로 바꿔 비교한다', () => {
    expect(hostsInLinkText('https://한글.example')).toEqual([])
    // 한글 음절은 주소 조각에서 빼므로(조사 대비) 글자만으로는 호스트를 만들지 않는다. 키릴 문자 등은 퓨니코드로
    expect(hostsInLinkText('https://exаmple.com')).toEqual(['xn--exmple-4nf.com'])
  })
})

describe('linkHostInfo', () => {
  it('일반 글자 링크: 실제 호스트를 보여 준다', () => {
    expect(linkHostInfo('https://docs.example.com/a', '공식 문서')).toEqual({
      host: 'docs.example.com',
      mismatch: false,
      showHost: true,
    })
  })

  it('글자가 주소인데 호스트가 다르면 경고', () => {
    const info = linkHostInfo('https://evil.example/login', 'https://bank.example.com')
    expect(info).toEqual({ host: 'evil.example', mismatch: true, showHost: true })
  })

  it('스킴 없는 도메인 글자도 비교한다', () => {
    expect(linkHostInfo('https://evil.example', 'bank.example.com')!.mismatch).toBe(true)
    expect(linkHostInfo('https://paypa1.example', 'paypal.example')!.mismatch).toBe(true)
  })

  it('글자가 같은 호스트의 주소(자동 링크)면 호스트를 반복하지 않는다', () => {
    expect(linkHostInfo('https://example.org/b', 'https://example.org/b')).toEqual({
      host: 'example.org',
      mismatch: false,
      showHost: false,
    })
  })

  it('www. 차이는 경고하지 않지만 글자에 없는 호스트이므로 보여 준다', () => {
    expect(linkHostInfo('https://www.example.com/', 'https://example.com')).toEqual({
      host: 'www.example.com',
      mismatch: false,
      showHost: true,
    })
  })

  it('비슷한 글자(키릴 а) 주소는 같은 호스트여도 퓨니코드를 보여 준다', () => {
    const info = linkHostInfo('https://exаmple.com/', 'https://exаmple.com/')!
    expect(info.host).toBe('xn--exmple-4nf.com')
    expect(info.mismatch).toBe(false)
    expect(info.showHost).toBe(true)
  })

  it('호스트는 대소문자를 정규화한 값, 사용자 정보는 빠진다', () => {
    expect(linkHostInfo('https://user:pw@EXAMPLE.com/x', '링크')!.host).toBe('example.com')
  })

  it('http/https가 아니면 null', () => {
    expect(linkHostInfo('javascript:alert(1)', 'x')).toBeNull()
    expect(linkHostInfo('/relative', 'x')).toBeNull()
  })
})

describe('hastText', () => {
  it('중첩된 노드의 글자를 모은다', () => {
    const node = {
      type: 'element',
      children: [
        { type: 'text', value: 'https://' },
        { type: 'element', children: [{ type: 'text', value: 'bank.example' }] },
      ],
    }
    expect(hastText(node)).toBe('https://bank.example')
    expect(hastText(undefined)).toBe('')
  })
})

describe('위장 글자', () => {
  it('방향 서식 문자를 지운 뒤 판정한다', () => {
    expect(hostsInLinkText('\u202Ehttps://bank.example.com')).toEqual(['bank.example.com'])
    expect(linkHostInfo('https://evil.example', '\u2066https://bank.example.com\u2069')!.mismatch).toBe(true)
  })

  it('사용자 정보 형태는 다른 주소로 본다', () => {
    expect(linkTextHasUserinfo('https://good.example:x@evil.example/p')).toBe(true)
    expect(linkTextHasUserinfo('https://good.example/p?mail=a@b.example')).toBe(false)
    expect(linkHostInfo('https://evil.example/', 'https://good.example:x@evil.example')).toEqual({
      host: 'evil.example',
      mismatch: true,
      showHost: true,
    })
  })
})
