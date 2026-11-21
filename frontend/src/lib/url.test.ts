import { describe, expect, it } from 'vitest'
import { displayUrl, extractUrl, hostOf, parseDomainPatterns, safeHref } from './url'

describe('safeHref', () => {
  it('http/https만 링크로 허용', () => {
    expect(safeHref('https://example.com/a')).toBe('https://example.com/a')
    expect(safeHref('http://example.com')).toBe('http://example.com/')
    expect(safeHref('javascript:alert(1)')).toBeUndefined()
    expect(safeHref('JAVASCRIPT:alert(1)')).toBeUndefined()
    expect(safeHref('data:text/html,x')).toBeUndefined()
    expect(safeHref('/relative')).toBeUndefined()
    expect(safeHref('not a url')).toBeUndefined()
  })
  it('사용자 정보를 뺀다', () => {
    expect(safeHref('https://user:pass@example.com/p')).toBe('https://example.com/p')
  })
})

describe('displayUrl', () => {
  it('호스트를 따로 떼고 경로를 뒤에 둔다', () => {
    expect(displayUrl('https://www.example.com/path?q=1#h')).toEqual({
      host: 'www.example.com',
      prefix: 'https://',
      rest: '/path?q=1#h',
      maskedCredentials: false,
    })
  })
  it('사용자 정보는 가린다', () => {
    const d = displayUrl('https://user:secret@example.com/p')
    expect(d.host).toBe('example.com')
    expect(d.prefix).toBe('https://***@')
    expect(d.maskedCredentials).toBe(true)
    expect(JSON.stringify(d)).not.toContain('secret')
    expect(JSON.stringify(d)).not.toContain('user')
  })
  it('http/https가 아니면 텍스트로만', () => {
    expect(displayUrl('javascript:alert(1)')).toEqual({
      host: '',
      prefix: '',
      rest: 'javascript:alert(1)',
      maskedCredentials: false,
    })
  })
  it('경로의 글자 방향 서식 문자는 지운다', () => {
    expect(displayUrl('https://example.com/a%E2%80%AEfdp.exe').rest).toBe('/afdp.exe')
    expect(displayUrl('https://example.com/a%D8%9Cb%E2%81%A6c%E2%80%8Fd').rest).toBe('/abcd')
  })
  it('한글 경로는 읽기 쉽게 푼다', () => {
    expect(displayUrl('https://example.com/%ED%95%9C%EA%B8%80').rest).toBe('/한글')
  })
  it('루트 경로는 생략', () => {
    expect(displayUrl('https://example.com/').rest).toBe('')
    expect(displayUrl('https://example.com:8443/').rest).toBe(':8443')
  })
})

describe('hostOf / extractUrl', () => {
  it('www.를 뺀 호스트', () => {
    expect(hostOf('https://www.example.com/x')).toBe('example.com')
    expect(hostOf('javascript:alert(1)')).toBe('')
  })
  it('공유 문구에서 첫 링크를 뽑는다', () => {
    expect(extractUrl('이거 봐 https://example.com/a?b=1 좋아')).toBe('https://example.com/a?b=1')
    expect(extractUrl('링크 없음')).toBeNull()
  })
})

describe('parseDomainPatterns', () => {
  it('호스트 이름만 남기고 소문자·중복 정리', () => {
    expect(parseDomainPatterns('Example.com, www.example.com example.com')).toEqual({
      patterns: ['example.com', 'www.example.com'],
      invalid: [],
    })
  })
  it('주소를 붙여넣으면 호스트만 쓴다', () => {
    expect(parseDomainPatterns('https://m.example.org/path?x=1').patterns).toEqual(['m.example.org'])
  })
  it('주소의 쿼리에 있는 쉼표로 나누지 않는다', () => {
    expect(parseDomainPatterns('https://www.example.com/watch?v=1,2,3, other.example.org')).toEqual({
      patterns: ['www.example.com', 'other.example.org'],
      invalid: [],
    })
    expect(parseDomainPatterns('https://a.example.com,https://b.example.com/x?q=1,2').patterns).toEqual([
      'a.example.com',
      'b.example.com',
    ])
    expect(parseDomainPatterns('https://a.example.com,b.example.com').patterns).toEqual(['a.example.com', 'b.example.com'])
  })
  it('호스트가 아닌 값은 invalid', () => {
    expect(parseDomainPatterns('example.com/path, exa_mple.com, ftp://x.com').invalid).toEqual([
      'example.com/path',
      'exa_mple.com',
      'ftp://x.com',
    ])
  })
})
